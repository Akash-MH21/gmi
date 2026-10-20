"""Catalogue and request queue support for GMI media models."""
from __future__ import annotations
import json, mimetypes, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
import httpx
from . import __version__
from .config import GMIError, config_path
BASE='https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey'
TERMINAL={'success','failed','error','cancelled','completed'}
PROMPT_NAMES=('prompt','text','lyrics')
JUNK_WORDS=re.compile(r'capture|probe|ssrf|test|hunt|bypass',re.I)
UUID=re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',re.I)
def filter_junk_ids(ids):
 return [s for value in (ids or []) if (s:=str(value).strip()) and not JUNK_WORDS.search(s) and not UUID.fullmatch(s)]
def price_info(record):
 info=record.get('price_info') or {}
 try: dollars=f"${Decimal(str(info.get('price')))/Decimal(1000000):.3f}".rstrip('0').rstrip('.')
 except (InvalidOperation,TypeError): return '-'
 unit=str(info.get('unit') or 'unit').replace('per_','').replace('_',' ')
 unit = {'images': 'image', 'seconds': 'second', 'characters': 'character', 'requests': 'request'}.get(unit, unit)
 return f"{dollars} / {unit}"

def _unit(record):
 unit = str((record.get('price_info') or {}).get('unit') or 'unit').strip().lower().replace('_', ' ')
 return unit

def estimate_cost(record, params, prompt):
 """Return (USD estimate or None, human-readable estimate text)."""
 info = record.get('price_info') or {}
 try: rate = Decimal(str(info.get('price'))) / Decimal(1000000)
 except (InvalidOperation, TypeError, ValueError): return None, 'Cost unavailable'
 unit = _unit(record)
 if unit in {'image', 'images', 'generation', 'generations', 'video', 'videos', 'request', 'requests'} or unit.startswith('song'):
  noun = unit.rstrip('s')
  return float(rate), f"${rate:.4f} per {noun}"
 if unit in {'second', 'seconds'}:
  spec = next((p for p in (record.get('parameters') or []) if p.get('name') == 'duration'), {})
  duration = (params or {}).get('duration', spec.get('default_value'))
  if duration is None:
   return None, f"${rate:.3f} / second, cost depends on duration"
  try:
   total = rate * Decimal(str(duration))
   return float(total), f"${total:.4f} for {duration} seconds (${rate:.3f} / second)"
  except (InvalidOperation, TypeError, ValueError):
   return None, f"${rate:.3f} / second, cost depends on duration"
 if unit in {'character', 'characters'}:
  count = len(prompt or ''); total = rate * count
  return float(total), f"${total:.4f} for {count} characters (${rate:.3f} / character)"
 if unit in {'1k character', '1k characters', '1000 character', '1000 characters'}:
  count = len(prompt or ''); total = rate * Decimal(count) / Decimal(1000)
  return float(total), f"${total:.5f} for {count} characters (${rate:.2f} / 1k characters)"
 return float(rate), f"${rate:.4f}"
def grouped_models(records):
 groups={}
 for record in records: groups.setdefault(record.get('model_type','other'),[]).append(record)
 return groups
def usable(record, output_type=None):
 if record.get('status')!='active' or int(record.get('qworkers') or 0)<=0:return False
 if str((record.get('model_metadata') or {}).get('visibility','')).lower()=='hidden':return False
 if output_type is None:return True
 return any((x.get('type') if isinstance(x,dict) else x)==output_type for x in ((record.get('modalities') or {}).get('output') or []))
def _specs(parameters): return {p.get('name'):p for p in (parameters or []) if p.get('name')}
def _convert(value, typ):
 if typ in ('integer','int'):return int(value)
 if typ in ('float','number'):return float(value)
 if typ in ('boolean','bool'):
  text=str(value).lower()
  if text not in {'true','false','1','0','yes','no','on','off'}:raise ValueError
  return text in {'true','1','yes','on'}
 return value
def validate_payload(payload, parameters):
 params=parameters.get('parameters',[]) if isinstance(parameters,dict) else parameters; specs=_specs(params)
 for name,value in list(payload.items()):
  spec=specs.get(name)
  if not spec: raise GMIError(f"Unknown parameter '{name}'. Valid parameters: {', '.join(specs) or '(prompt only)'}")
  typ=spec.get('type','string')
  if typ in {'image','audio','video'} and isinstance(value,str) and not value.startswith(('http://','https://')): raise GMIError(f"Local media files are not supported for '{name}' yet; provide an http(s) URL.")
  options=spec.get('options') or spec.get('enum') or []; option_values=[x.get('value') if isinstance(x,dict) else x for x in options]
  try: converted=_convert(value,typ)
  except (TypeError,ValueError): raise GMIError(f'Parameter {name} must be a {typ}.') from None
  if option_values and converted not in option_values:
   shown=', '.join(map(str,option_values[:10])); more=f' ({len(option_values)} total)' if len(option_values)>10 else ''
   raise GMIError(f'Invalid value for {name}: {value}. Valid values: {shown}{more}')
  payload[name]=converted
 for name,spec in specs.items():
  if spec.get('required') and name not in payload:
   if 'default_value' in spec and spec.get('default_value') is not None: payload[name]=_convert(spec['default_value'],spec.get('type','string'))
   else: raise GMIError(f"Missing required parameter '{name}'.")
 return payload
def build_payload(schema,prompt,extras=None):
 parameters=schema.get('parameters',[]) if isinstance(schema,dict) else schema; specs=_specs(parameters); prompt_name=next((n for n in PROMPT_NAMES if n in specs),None)
 if prompt_name is None: raise GMIError('This model has no supported prompt parameter (prompt, text or lyrics).')
 payload={prompt_name:prompt}; payload.update(extras or {}); return validate_payload(payload,parameters)
def default_model(records,kind):
 candidates=[r for r in records if r.get('model_type')==kind and usable(r,kind)]
 def eligible(r):
  inputs=(r.get('modalities') or {}).get('input') or []
  if any((x.get('type') if isinstance(x,dict) else x) in {'image','audio','video'} and (x.get('required',True) if isinstance(x,dict) else True) for x in inputs): return False
  params=r.get('parameters') or []; prompts={p.get('name') for p in params if p.get('name') in PROMPT_NAMES}
  if any(p.get('required') and p.get('type') in {'image','audio','video'} for p in params): return False
  return bool(prompts) and all(not p.get('required') or p.get('name') in prompts or p.get('default_value') is not None for p in params)
 candidates=[r for r in candidates if eligible(r)]
 return min(candidates,key=lambda r:Decimal(str((r.get('price_info') or {}).get('price','1e99')))) if candidates else None
def cache_path(): return config_path().parent/'cache'/'media-models.json'
def extract_urls(outcome):
 found=[]; thumbs=[]
 def add(v,thumb=False):
  if isinstance(v,str) and v.startswith(('http://','https://')):(thumbs if thumb else found).append(v)
 for key,value in (outcome or {}).items():
  if key=='thumbnail_image_url':add(value,True)
  elif key in {'audio_url','video_url'}:add(value)
  elif key in {'media_urls','media','medias'} and isinstance(value,list):
   for item in value:add(item.get('url') if isinstance(item,dict) else item)
 result=list(dict.fromkeys(found)); return result or list(dict.fromkeys(thumbs))
class MediaClient:
 def __init__(self,key,transport=None):
  self.key=key; self.client=transport or httpx.Client(base_url=os.environ.get('GMI_MEDIA_BASE_URL',BASE).rstrip('/')+'/',headers={'Authorization':f'Bearer {key}','User-Agent':f'gmi-cli/{__version__}'},timeout=120); self._owned=transport is None
 def close(self):
  if self._owned:self.client.close()
 def _response(self,response):
  if response.status_code>=400:
   detail=''
   try:
    body=response.json(); detail=body.get('error','')
    limit_info=body.get('rate_limit') or {}
    if response.status_code == 429 and limit_info.get('type') == 'rate_limit_error' and limit_info.get('limit_type') == 'RPD':
     from datetime import timedelta
     wait_ms=limit_info.get('retry_after_ms'); when='unknown time'
     if wait_ms is not None: when=(datetime.now().astimezone()+timedelta(milliseconds=int(wait_ms))).strftime('%H:%M')
     model=body.get('model',getattr(self,'_model_for_error','the selected model'))
     raise GMIError(f"Daily limit reached for {model}: {limit_info.get('limit','?')} requests per day (UTC). It resets at {when}. Try another model: gmi media models --type {getattr(self,'media_type','image')}")
   except GMIError: raise
   except Exception:pass
   raise GMIError(f"Media API returned HTTP {response.status_code}{(': '+str(detail)) if detail else ''}")
  return response.json()
 def get(self,path):return self._response(self.client.get(path))
 def _get(self,path): return self.get(path)
 def catalogue(self,refresh=False,progress=None):
  path=cache_path()
  if not refresh and path.exists() and time.time()-path.stat().st_mtime<86400:
   try:return json.loads(path.read_text())
   except (OSError,ValueError):pass
  ids=filter_junk_ids(self.get('models').get('model_ids',[])); records=[]
  with ThreadPoolExecutor(max_workers=8) as pool:
   futures={pool.submit(self.get,'models/'+i):i for i in ids}
   for n,future in enumerate(as_completed(futures),1):
    try:
     record=future.result(); record=record.get('data',record) if isinstance(record,dict) else record
     if record.get('model') and usable(record):records.append(record)
    except Exception:pass
    if progress:progress(n,len(ids))
  records.sort(key=lambda r:r.get('model','')); data={'models':records,'grouped':grouped_models(records),'fetched_at':datetime.now(timezone.utc).isoformat()}; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); path.write_text(json.dumps(data,ensure_ascii=False)); path.chmod(0o600); return data
 def submit(self,model,payload):
  self._model_for_error=model
  return self._response(self.client.post('requests',json={'model':model,'payload':payload}))
 def _get_post(self,path,body): return self._response(self.client.post(path,json=body))
 def run(self,model,payload,timeout=600,on_status=None,sleep=time.sleep):
  for attempt in range(3):
   try:
    result=self.submit(model,payload)
    if result.get('status') in TERMINAL:return result
    return self.poll(result.get('request_id') or result.get('id'),timeout,on_status,sleep)
   except GMIError as error:
    if 'HTTP 500' not in str(error) or 'Upstream provider temporarily unavailable' not in str(error) or attempt==2:raise
    sleep(3 if attempt==0 else 6)
 def poll(self,request_id,timeout=600,on_status=None,sleep=time.sleep):
  started=time.monotonic(); delay=1.0
  while True:
   result=self.get('requests/'+request_id); state=result.get('status','unknown')
   if on_status:on_status(state,time.monotonic()-started)
   if state in TERMINAL:
    if state=='failed':
     error=(result.get('outcome') or {}).get('error') or result.get('error') or result.get('message') or 'unknown error'; raise GMIError(f"Media request {request_id} failed for model {result.get('model','')}: {error}")
    return result
   if time.monotonic()-started>=timeout:raise GMIError(f'Media request {request_id} timed out; resume with gmi media get {request_id}.')
   sleep(delay); delay=min(delay*1.5,5)
 def download(self,outcome,output_dir='gmi-output',model='media'):
  urls=extract_urls(outcome); directory=Path(output_dir); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); paths=[]
  for index,url in enumerate(urls):
   with httpx.stream('GET',url,timeout=120) as stream:
    stream.raise_for_status(); suffix=Path(urlparse(url).path).suffix or mimetypes.guess_extension(stream.headers.get('content-type','').split(';',1)[0]) or '.bin'; path=directory/f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]','_',model)}-{index+1}{suffix}"
    with path.open('wb') as handle:
     for chunk in stream.iter_bytes():handle.write(chunk)
   paths.append(path)
  return paths

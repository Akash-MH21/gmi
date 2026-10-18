"""GMI media catalogue and asynchronous request queue client."""
from __future__ import annotations

import json
import mimetypes
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import __version__
from .config import GMIError, config_path

BASE = "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey"
JUNK_RE = re.compile(r"(?:capture|probe|ssrf|test)", re.I)
PROMPT_NAMES = ("prompt", "text", "lyrics")


def filter_junk_ids(ids):
    """Remove internal ids which the public catalogue endpoint exposes."""
    result = []
    for value in ids or []:
        value = str(value)
        if not value or JUNK_RE.search(value) or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,}", value, re.I):
            continue
        result.append(value)
    return result


def price_info(record):
    info = record.get("price_info") or {}
    try:
        dollars = Decimal(str(info.get("price", 0))) / Decimal(1_000_000)
        price = f"${dollars:.3f}".rstrip("0").rstrip(".")
    except Exception:
        price = "-"
    unit = str(info.get("unit") or "unit").replace("per_", "").replace("_", " ")
    unit = {"image": "image", "second": "second", "seconds": "second", "1k characters": "1k characters"}.get(unit, unit)
    return f"{price} / {unit}" if price != "-" else "-"


def usable(record, output_type):
    if record.get("status") != "active" or str((record.get("model_metadata") or {}).get("visibility", "")).lower() == "hidden":
        return False
    outputs = record.get("modalities", {}).get("output", [])
    return any((x.get("type") if isinstance(x, dict) else x) == output_type for x in outputs)


def grouped_models(records):
    groups = {}
    for record in records:
        groups.setdefault(record.get("model_type", "other"), []).append(record)
    return groups


def build_payload(schema, prompt, extras=None):
    extras = extras or {}
    params = schema.get("parameters", schema if isinstance(schema, list) else []) or []
    by_name = {p.get("name"): p for p in params if p.get("name")}
    prompt_param = next((name for name in PROMPT_NAMES if name in by_name), None)
    if not prompt_param:
        prompt_param = next((name for name in PROMPT_NAMES if (by_name.get(name) or {}).get("required")), "prompt")
    values = {prompt_param: prompt}
    values.update(extras)
    validate_payload(values, params)
    return values


def _convert(value, typ):
    if typ in ("integer", "int"): return int(value)
    if typ in ("number", "float"): return float(value)
    if typ in ("boolean", "bool"): return str(value).lower() in ("1", "true", "yes", "on")
    return value


def validate_payload(payload, parameters):
    params = parameters.get("parameters", parameters) if isinstance(parameters, dict) else parameters
    params = params or []
    specs = {p.get("name"): p for p in params if p.get("name")}
    for p in params:
        name = p.get("name")
        if p.get("required") and name not in payload:
            raise GMIError(f"Missing required parameter '{name}'.")
    for name, value in payload.items():
        spec = specs.get(name)
        if not spec:
            raise GMIError(f"Unknown parameter '{name}'. Valid parameters: {', '.join(specs) or '(prompt only)'}")
        options = spec.get("enum") or spec.get("options")
        if options and value not in options:
            raise GMIError(f"Invalid value for {name}: {value}. Valid values: {', '.join(map(str, options))}")
        typ = spec.get("type", "string")
        if typ in ("integer", "number", "float", "boolean", "int", "bool"):
            try: payload[name] = _convert(value, typ)
            except (TypeError, ValueError): raise GMIError(f"Parameter {name} must be a {typ}.") from None
        if isinstance(value, str) and (typ in ("image", "audio", "video") or name in ("image", "audio", "video", "image_url", "audio_url", "video_url")) and Path(value).exists():
            raise GMIError(f"Local media files are not supported for '{name}' yet; provide a URL instead.")
    return payload


def cache_path():
    return config_path().parent / "cache" / "media-models.json"


class MediaClient:
    def __init__(self, key, transport=None):
        self.key = key
        self.client = transport or httpx.Client(base_url=BASE + "/", headers={"Authorization": f"Bearer {key}", "User-Agent": f"gmi-cli/{__version__}"}, timeout=120)
        self._owned = transport is None

    def close(self):
        if self._owned: self.client.close()

    def _get(self, path):
        response = self.client.get(path)
        if response.status_code >= 400: raise GMIError(f"Media API returned HTTP {response.status_code}; check your key and request.")
        return response.json()

    def catalogue(self, refresh=False):
        path = cache_path()
        if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
            try: return json.loads(path.read_text())
            except (OSError, ValueError): pass
        ids = filter_junk_ids(self._get("models").get("model_ids", []))
        records = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self._get, "models/" + model_id): model_id for model_id in ids}
            for future in as_completed(futures):
                try:
                    record = future.result()
                    if isinstance(record.get("data"), dict): record = record["data"]
                    if record.get("model") and record.get("status") == "active" and str((record.get("model_metadata") or {}).get("visibility", "")).lower() != "hidden": records.append(record)
                except Exception: continue
        records.sort(key=lambda r: r.get("model", ""))
        data = {"models": records, "grouped": grouped_models(records), "fetched_at": datetime.now(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def submit(self, model, payload):
        value = self._get_post("requests", {"model": model, "payload": payload})
        return value

    def _get_post(self, path, body):
        response = self.client.post(path, json=body)
        if response.status_code >= 400: raise GMIError(f"Media API returned HTTP {response.status_code}; check your request.")
        return response.json()

    def poll(self, request_id, timeout=600, on_status=None, sleep=time.sleep):
        started = time.monotonic(); delay = 1.0
        while True:
            result = self._get("requests/" + request_id); state = result.get("status", "unknown")
            if on_status: on_status(state, time.monotonic() - started)
            if state in ("success", "completed"): return result
            if state in ("failed", "error", "cancelled"): raise GMIError(f"Media request {request_id} failed: {result.get('error') or result.get('message') or state}")
            if time.monotonic() - started >= timeout: raise GMIError(f"Media request {request_id} timed out; resume with gmi media get {request_id}.")
            sleep(delay); delay = min(delay * 1.5, 10)

    def download(self, outcome, output_dir="gmi-output", model="media"):
        urls = [v for v in outcome.values() if isinstance(v, str) and v.startswith(("http://", "https://"))]
        directory = Path(output_dir); directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        paths = []
        for index, url in enumerate(urls):
            response = self.client.get(url) if url.startswith(BASE) else httpx.get(url, timeout=120)
            response.raise_for_status(); suffix = Path(urlparse(url).path).suffix or mimetypes.guess_extension(response.headers.get("content-type", "").split(";")[0]) or ".bin"
            path = directory / f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', model)}{'' if index == 0 else f'-{index}'}{suffix}"; path.write_bytes(response.content); paths.append(path)
        return paths


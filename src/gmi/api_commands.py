"""Generated OpenAPI operation commands backed by the committed manifest."""
import json, os, sys, re
from pathlib import Path
from urllib.parse import quote, urlencode
import click, httpx
from .config import GMIError, mask_key, resolve_key

_MANIFEST = None
def manifest():
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = json.loads((Path(__file__).with_name("api_manifest.json")).read_text())
    return _MANIFEST

def _ops(service=None):
    return [o for o in manifest()["operations"] if service is None or o["service"] == service]

def _auth_label(o):
    return o["security_scheme"]

class LazyApiGroup(click.Group):
    def _load(self):
        if not getattr(self, "_loaded", False):
            self._loaded = True
            register_operations()
    def get_command(self, ctx, name):
        self._load(); return super().get_command(ctx, name)
    def list_commands(self, ctx):
        self._load(); return super().list_commands(ctx)

@click.group("api", cls=LazyApiGroup)
def api_group():
    """Call every operation in GMI's published OpenAPI APIs."""

@api_group.command("list")
@click.option("--service", type=click.Choice(["iam","idc","sandbox","cluster"]))
@click.option("--method")
@click.option("--search", default="")
@click.option("--json", "as_json", is_flag=True)
def api_list(service, method, search, as_json):
    """List generated API operations."""
    rows = _ops(service)
    if method: rows = [o for o in rows if o["method"] == method.upper()]
    if search: rows = [o for o in rows if search.casefold() in json.dumps(o).casefold()]
    if as_json: click.echo(json.dumps({"operations": rows, "total": len(rows)}, separators=(",", ":"))); return
    for o in rows: click.echo(f"{o['service']}\t{o['group']}\t{o['name']}\t{o['method']}\t{o['path']}\t{o['security_scheme']}")
    click.echo(f"Total: {len(rows)}")

@api_group.command("check")
@click.option("--service", type=click.Choice(["iam","idc","sandbox","cluster"]))
@click.option("--json", "as_json", is_flag=True)
def api_check(service, as_json):
    """Probe safe GET operations and classify access."""
    key = resolve_key(None); rows = _ops(service); results=[]; skipped=[]
    for o in rows:
        reasons=[]
        if o["method"] != "GET": reasons.append("not a GET")
        if o["path_parameters"]: reasons.append("needs a path parameter")
        if any(p.get("required") for p in o["query_parameters"]): reasons.append("needs a required query parameter")
        if reasons: skipped.append({"operation":o["name"],"service":o["service"],"reasons":reasons}); continue
        try:
            with httpx.Client(headers={"Authorization":"Bearer "+key,"User-Agent":"gmi-cli/0.1.0"},timeout=30) as c: r=c.get(o["server"].rstrip("/")+o["path"])
            verdict="ok" if r.status_code < 400 else "needs another key type" if r.status_code in (401,403) else "not found" if r.status_code==404 else "server error" if r.status_code>=500 else "ok"
            results.append({"service":o["service"],"group":o["group"],"operation":o["name"],"status":r.status_code,"verdict":verdict})
        except httpx.RequestError: results.append({"service":o["service"],"group":o["group"],"operation":o["name"],"status":None,"verdict":"network error"})
    scope={}
    try:
        with httpx.Client(headers={"Authorization":"Bearer "+key,"User-Agent":"gmi-cli/0.1.0"},timeout=30) as c:
            r=c.get("https://console.gmicloud.ai/api/v1/me/api-keys/current"); value=r.json(); scope={"scope":value.get("scope"),"product":value.get("product")}
    except Exception: scope={"scope":None,"product":None}
    report={"key":scope,"results":results,"skipped":skipped,"summary":{"generated":len(rows),"run":len(results),"not_run":len(skipped)}}
    if as_json: click.echo(json.dumps(report, separators=(",",":"))); return
    click.echo(f"Key scope: {scope.get('scope')} product: {scope.get('product')}")
    for x in results: click.echo(f"{x['service']} {x['operation']} {x['status']} {x['verdict']}")
    click.echo(f"Generated {len(rows)} of {len(manifest()['operations'])}; run live {len(results)}; not run {len(skipped)}")

def _coerce(value, spec):
    typ = spec.get("type", "string")
    if spec.get("enum") and value not in [str(x) for x in spec["enum"]]: raise click.BadParameter(f"must be one of: {', '.join(map(str,spec['enum']))}")
    if typ in ("integer", "number"): return int(value) if typ == "integer" else float(value)
    if typ == "boolean":
        if value.lower() not in ("true","false"): raise click.BadParameter("must be true or false")
        return value.lower() == "true"
    return value

def _body(data, sets, spec):
    if data:
        raw = sys.stdin.read() if data == "-" else Path(data[1:]).read_text() if data.startswith("@") else data
        try: value = json.loads(raw)
        except Exception as e: raise click.ClickException(f"Invalid JSON body: {e}")
    else: value = {}
    if not isinstance(value, dict): raise click.ClickException("JSON body must be an object")
    known = {x["name"]: x for x in (spec or {}).get("properties", [])}
    for item in sets:
        if "=" not in item: raise click.ClickException("--set expects key=value")
        key, val = item.split("=", 1); value[key] = _coerce(val, known.get(key, {}))
    missing = [x["name"] for x in (spec or {}).get("properties", []) if x.get("required") and x["name"] not in value]
    if missing: raise click.ClickException("Missing required body fields: " + ", ".join(missing))
    return value

def _request(o, path_values, query, headers, data, sets, token, access_token, host, output, as_json, yes, dry_run):
    path = o["path"]
    for p, v in zip(o["path_parameters"], path_values): path = path.replace("{" + p["name"] + "}", quote(v, safe=""))
    base = host.rstrip("/") if host else o["server"].rstrip("/")
    url = base + path
    query = {k:v for k,v in query.items() if v is not None}
    full = url + (("?" + urlencode(query, doseq=True)) if query else "")
    scheme = o["security_scheme"]; req_headers = {k:v for k,v in headers.items() if v is not None}
    if scheme in ("bearerAuth", "bearerAPIKey"):
        if token or not dry_run: req_headers["Authorization"] = "Bearer " + (token or resolve_key(None))
    elif scheme == "bearerEmailVerificationToken":
        if not token: raise click.ClickException("This operation requires --token")
        req_headers["Authorization"] = "Bearer " + token
    elif scheme == "sandboxAccessToken":
        if not access_token: raise click.ClickException("This operation requires --access-token or GMI_SANDBOX_TOKEN")
        req_headers["X-Access-Token"] = access_token
    body = _body(data, sets, o.get("request_body")) if o.get("request_body") else None
    shown = {k:(mask_key(v) if k.lower() in ("authorization","x-access-token") else v) for k,v in req_headers.items()}
    if dry_run:
        click.echo(json.dumps({"method":o["method"],"url":full,"headers":shown,"body":body}, indent=2, ensure_ascii=False)); return
    if o["method"] != "GET":
        if o["method"] == "DELETE": click.echo("This deletes data.")
        if not yes and not sys.stdin.isatty(): raise click.ClickException("Refusing without a terminal; use --yes")
        if not yes and not click.confirm("Continue?", default=False): raise click.ClickException("Cancelled.")
    try:
        with httpx.Client(headers={"User-Agent":"gmi-cli/0.1.0", **req_headers}, timeout=120) as client:
            response = client.request(o["method"], full, json=body)
    except httpx.RequestError as e: raise click.ClickException(f"Network error: {e}")
    if response.status_code >= 400:
        try: payload=response.json(); msg=payload.get("message") or payload.get("error") or payload
        except Exception: msg=response.text[:200]
        extra = " This key type may not be allowed for this operation: see gmi api check." if response.status_code == 401 else ""
        raise click.ClickException(f"HTTP {response.status_code}: {msg}{extra}")
    if o.get("returns_binary"):
        if not output: raise click.ClickException("This operation returns binary data; use --out FILE")
        Path(output).write_bytes(response.content); click.echo(output); return
    try: payload=response.json()
    except Exception: payload=response.text
    click.echo(json.dumps(payload, separators=(",", ":") if as_json else None, indent=None if as_json else 2, ensure_ascii=False))

def _operation_command(o):
    params=[]
    for p in reversed(o["path_parameters"]): params.append(click.argument(p["name"]))
    def dest(name): return re.sub(r"\W", "_", name).strip("_")
    for p in reversed(o["query_parameters"]): params.append(click.option("--" + re.sub(r"[^A-Za-z0-9_-]", "-", p["name"]), dest(p["name"]), default=p.get("default"), required=p.get("required",False)))
    for p in reversed(o["header_parameters"]): params.append(click.option("--" + re.sub(r"[^A-Za-z0-9_-]", "-", p["name"]), dest(p["name"])))
    params += [click.option("--data"), click.option("--set", "sets", multiple=True), click.option("--token", envvar="GMI_TOKEN"), click.option("--access-token", envvar="GMI_SANDBOX_TOKEN"), click.option("--host"), click.option("--out", "output"), click.option("--yes", is_flag=True), click.option("--dry-run", is_flag=True), click.option("--json", "as_json", is_flag=True)]
    def callback(*args, **kwargs):
        names=[p["name"] for p in o["path_parameters"]]; vals=[kwargs.pop(n) for n in names]
        reserved={"data","sets","token","access_token","host","output","yes","dry_run","as_json"}; query={}; headers={}
        for p in o["query_parameters"]:
            value = kwargs.pop(dest(p["name"]))
            query[p["name"]] = _coerce(str(value), p) if value is not None else None
        for p in o["header_parameters"]: headers[p["name"]]=kwargs.pop(dest(p["name"]))
        return _request(o, vals, query, headers, kwargs.pop("data"), kwargs.pop("sets"), kwargs.pop("token"), kwargs.pop("access_token"), kwargs.pop("host"), kwargs.pop("output"), kwargs.pop("as_json"), kwargs.pop("yes"), kwargs.pop("dry_run"))
    for param in params: callback=param(callback)
    callback.__name__=o["name"]; callback.__doc__=f"{o['summary']}\n\n{ o['method']} {o['path']}\nAuth: {o['security_scheme']}"
    return click.command(o["name"])(callback)

def register_operations():
    for service in sorted({o["service"] for o in manifest()["operations"]}):
        sg=click.Group(service, help=f"{service} API operations")
        for group in sorted({o["group"] for o in _ops(service)}):
            gg=click.Group(group)
            for o in [x for x in _ops(service) if x["group"]==group]: gg.add_command(_operation_command(o))
            sg.add_command(gg)
        api_group.add_command(sg)


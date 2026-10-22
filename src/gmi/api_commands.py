"""Generated OpenAPI operation commands backed by the committed manifest."""
import json, os, sys, re
from pathlib import Path
from urllib.parse import quote, urlencode
import click, httpx
from .config import GMIError, mask_key, resolve_key, read_key

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

def _masked_header(value):
    if value.startswith("Bearer "):
        return "Bearer " + mask_key(value[7:])
    return mask_key(value)

def _credential(service, explicit=None, allow_missing=False):
    """Return (value, source, scope hint) using service-specific precedence."""
    if explicit:
        return explicit, "--token", "explicit"
    token = os.environ.get("GMI_TOKEN")
    if token:
        return token, "GMI_TOKEN", "explicit"
    if service in ("sandbox", "cluster"):
        for name in ("GMI_COMPUTE_API_KEY", "GMI_SANDBOX_API_KEY"):
            value = os.environ.get(name)
            if value:
                return value, name, "compute"
    value = os.environ.get("GMI_API_KEY")
    if value:
        return value, "GMI_API_KEY", "normal"
    value = read_key()
    if value:
        return value, "setting NAME", "normal"
    if allow_missing:
        return None, None, None
    raise GMIError("Missing API key; run gmi auth login or set GMI_API_KEY.")

def _auth_for(o, token=None, allow_missing=False):
    return _credential(o["service"], token, allow_missing=allow_missing)

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
@click.option("--token")
@click.option("--idc-name", envvar="GMI_SANDBOX_IDC_NAME")
@click.option("--markdown", type=click.Path(dir_okay=False, writable=True))
@click.option("--json", "as_json", is_flag=True)
def api_check(service, token, idc_name, markdown, as_json):
    """Probe safe GET operations and classify access."""
    token = token or os.environ.get("GMI_TOKEN")
    rows = _ops(service); results=[]; skipped=[]; credentials={}
    for o in rows:
        reasons=[]
        if o["method"] != "GET": reasons.append("not a GET")
        if o["path_parameters"]: reasons.append("needs a path parameter")
        missing_query = [p for p in o["query_parameters"] if p.get("required") and not (p["name"] == "idc_name" and idc_name)]
        if missing_query: reasons.append("needs a required query parameter")
        if reasons: skipped.append({"operation":o["name"],"service":o["service"],"reasons":reasons}); continue
        try:
            auth_headers={"User-Agent":"gmi-cli/0.1.0"}
            key, source, _ = _auth_for(o, token, allow_missing=True)
            if key and o["security_scheme"] in ("bearerAuth", "bearerAPIKey"):
                auth_headers["Authorization"]="Bearer "+key
                credentials.setdefault(key, {"source": source, "services": set()})["services"].add(o["service"])
            query = {"idc_name": idc_name} if idc_name and any(p["name"] == "idc_name" for p in o["query_parameters"]) else {}
            with httpx.Client(headers=auth_headers,timeout=30) as c: r=c.get(o["server"].rstrip("/")+o["path"], params=query)
            verdict="ok" if r.status_code < 400 else "needs another key type" if r.status_code in (401,403) else "bad request" if r.status_code==400 else "not found" if r.status_code==404 else "server error"
            results.append({"service":o["service"],"group":o["group"],"operation":o["name"],"status":r.status_code,"verdict":verdict})
        except httpx.RequestError: results.append({"service":o["service"],"group":o["group"],"operation":o["name"],"status":None,"verdict":"network error"})
    keys=[]
    for value, info in credentials.items():
        scope = {"scope": None, "product": None}
        try:
            with httpx.Client(headers={"Authorization":"Bearer "+value,"User-Agent":"gmi-cli/0.1.0"},timeout=30) as c:
                payload=c.get("https://console.gmicloud.ai/api/v1/me/api-keys/current").json()
                payload=payload.get("key", payload); scope={"scope":payload.get("scope"),"product":payload.get("product")}
        except Exception: pass
        keys.append({"services": sorted(info["services"]), "source": info["source"], **scope})
    by_service={}; by_verdict={}
    for item in results:
        by_service.setdefault(item["service"], {"run":0,"ok":0,"needs another key type":0,"bad request":0,"not found":0,"server error":0,"network error":0})
        by_service[item["service"]]["run"] += 1; by_service[item["service"]][item["verdict"]] += 1
        by_verdict[item["verdict"]] = by_verdict.get(item["verdict"], 0) + 1
    report={"keys":keys,"results":results,"skipped":skipped,"summary":{"generated":len(rows),"run":len(results),"not_run":len(skipped),"by_service":by_service,"by_verdict":by_verdict}}
    if markdown:
        Path(markdown).write_text(render_markdown(report), encoding="utf-8")
    if as_json: click.echo(json.dumps(report, separators=(",",":"))); return
    click.echo(f"Keys: {len(keys)}")
    for x in results: click.echo(f"{x['service']} {x['operation']} {x['status']} {x['verdict']}")
    click.echo(f"Generated {len(rows)} of {len(manifest()['operations'])}; run live {len(results)}; not run {len(skipped)}")

def render_markdown(report):
    from datetime import date
    lines=[f"# API coverage ({date.today().isoformat()})", "", "Generated by `gmi api check --markdown FILE`.", "", "## Keys", "", "| Source | Services | Scope | Product |", "|---|---|---|---|"]
    for key in report.get("keys", []): lines.append(f"| {key.get('source')} | {', '.join(key.get('services', []))} | {key.get('scope') or ''} | {key.get('product') or ''} |")
    lines += ["", "## Results", "", "| Service | Operation | Status | Verdict |", "|---|---|---:|---|"]
    for row in report.get("results", []): lines.append(f"| {row['service']} | `{row['operation']}` | {row['status'] if row['status'] is not None else ''} | {row['verdict']} |")
    lines += ["", "## Summary by service", "", "| Service | Run | OK | Needs another key type | Bad request |", "|---|---:|---:|---:|---:|"]
    for service, summary in report.get("summary", {}).get("by_service", {}).items(): lines.append(f"| {service} | {summary.get('run',0)} | {summary.get('ok',0)} | {summary.get('needs another key type',0)} | {summary.get('bad request',0)} |")
    lines += ["", "## Verdict totals", ""]
    for verdict, count in report.get("summary", {}).get("by_verdict", {}).items(): lines.append(f"- {verdict}: {count}")
    lines += ["", "## Not run", "", "| Service | Operation | Reasons |", "|---|---|---|"]
    for row in report.get("skipped", []): lines.append(f"| {row['service']} | `{row['operation']}` | {'; '.join(row['reasons'])} |")
    return "\n".join(lines)+"\n"

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
        key, _, _ = _auth_for(o, token, allow_missing=dry_run)
        if key: req_headers["Authorization"] = "Bearer " + key
    elif scheme == "bearerEmailVerificationToken":
        if not token: raise click.ClickException("This operation requires --token")
        req_headers["Authorization"] = "Bearer " + token
    elif scheme == "sandboxAccessToken":
        if not host: raise click.ClickException("This operation requires --host https://{sandbox_key}.{domain}")
        if not access_token: raise click.ClickException("This operation requires --access-token or GMI_SANDBOX_TOKEN")
        req_headers["X-Access-Token"] = access_token
    body = _body(data, sets, o.get("request_body")) if o.get("request_body") else None
    shown = {k:(_masked_header(v) if k.lower() in ("authorization","x-access-token") else v) for k,v in req_headers.items()}
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
        extra = " Set GMI_COMPUTE_API_KEY or GMI_SANDBOX_API_KEY to a console API key with compute scope; see gmi api check." if response.status_code == 401 and o["service"] in ("sandbox", "cluster") else ""
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
    for p in reversed(o["query_parameters"]):
        kwargs = {"default": p.get("default"), "required": p.get("required", False)}
        if p["name"] == "idc_name":
            kwargs.update(envvar="GMI_SANDBOX_IDC_NAME", required=False)
        params.append(click.option("--" + re.sub(r"[^A-Za-z0-9_-]", "-", p["name"]), dest(p["name"]), **kwargs))
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
            for o in [x for x in _ops(service) if x["group"]==group]:
                command = _operation_command(o)
                gg.add_command(command)
                # Keep tag groups while allowing the service-level operation form.
                if command.name in sg.commands:
                    raise ValueError(f"Duplicate operation name in {service}: {command.name}")
                sg.add_command(command)
            sg.add_command(gg)
        api_group.add_command(sg)


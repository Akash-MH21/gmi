#!/usr/bin/env python3
"""Generate the committed API manifest from the vendored OpenAPI documents."""
import argparse, json, re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = {"iam":"ias-public-api.yaml", "idc":"ids-public-api.yaml", "sandbox":"sandbox_api.yaml", "cluster":"service_api.yaml"}

def kebab(value):
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return value.lower().replace("id-cs", "idcs")

def schema_type(schema):
    if not schema: return "string"
    if "$ref" in schema: return schema["$ref"].rsplit("/", 1)[-1]
    return schema.get("type", "string")

def parameter(p):
    s = p.get("schema") or {}
    out = {"name": p.get("name"), "type": schema_type(s), "required": bool(p.get("required"))}
    if "enum" in s: out["enum"] = s["enum"]
    if "default" in s: out["default"] = s["default"]
    return out

def deref(schema, doc):
    if isinstance(schema, dict) and "$ref" in schema:
        return (doc.get("components", {}).get("schemas", {}).get(schema["$ref"].rsplit("/", 1)[-1]) or {})
    return schema or {}

def body_info(op, doc):
    body = op.get("requestBody") or {}
    content = body.get("content") or {}
    if not content: return None
    ctype = sorted(content)[0]; schema = deref(content[ctype].get("schema"), doc)
    props = []
    for name, value in (schema.get("properties") or {}).items():
        value = deref(value, doc)
        item = {"name": name, "type": schema_type(value), "required": name in (schema.get("required") or [])}
        if "enum" in value: item["enum"] = value["enum"]
        props.append(item)
    return {"content_type": ctype, "required": bool(body.get("required")), "properties": props}

def generate():
    operations = []
    for service, filename in FILES.items():
        doc = yaml.safe_load((ROOT / "specs" / filename).read_text())
        server = (doc.get("servers") or [{"url": ""}])[0].get("url", "")
        global_security = doc.get("security")
        used = {}
        for path, path_item in sorted((doc.get("paths") or {}).items()):
            for method, op in sorted(path_item.items()):
                if method.lower() not in {"get","post","put","patch","delete","head","options","trace"}: continue
                op = op or {}; tag = (op.get("tags") or [service])[0]
                base = kebab(op.get("operationId") or (method + " " + path))
                used.setdefault(tag, {})
                name = base; n = 2
                while name in used[tag]: name = f"{base}-{n}"; n += 1
                used[tag][name] = True
                params = list(path_item.get("parameters") or []) + list(op.get("parameters") or [])
                paths = [parameter(p) for p in params if p.get("in") == "path"]
                query = [parameter(p) for p in params if p.get("in") == "query"]
                headers = [parameter(p) for p in params if p.get("in") == "header" and p.get("name", "").lower() not in {"authorization", "x-access-token"}]
                security = op.get("security", global_security)
                scheme = "none" if security == [] or not security else next(iter((security[0] or {}).keys()), "none")
                # The IAM password reset operation is documented as public in
                # the server contract used for the Day 3 auth matrix.
                if service == "iam" and path == "/users/password-reset": scheme = "bearerAuth"
                binary = any(ct.startswith("application/octet-stream") or ct.startswith("application/zip") for r in (op.get("responses") or {}).values() for ct in (r.get("content") or {}))
                description = (op.get("description") or op.get("summary") or "").split(".", 1)[0].strip()
                operations.append({"service":service,"group":tag,"name":name,"method":method.upper(),"path":path,"summary":op.get("summary", ""),"description":description,"path_parameters":paths,"query_parameters":query,"header_parameters":headers,"request_body":body_info(op, doc),"security_scheme":scheme,"server":server,"returns_binary":binary})
    operations.sort(key=lambda x: (x["service"], x["group"], x["name"], x["method"], x["path"]))
    return {"operations": operations, "total": len(operations)}

def main():
    p = argparse.ArgumentParser(); p.add_argument("--check", action="store_true"); args = p.parse_args()
    text = json.dumps(generate(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = ROOT / "src/gmi/api_manifest.json"
    if args.check:
        if not target.exists() or target.read_text() != text: print("api_manifest.json is out of date"); return 1
        return 0
    target.write_text(text); return 0
if __name__ == "__main__": raise SystemExit(main())

"""Day 1 CLI commands."""

from decimal import Decimal, InvalidOperation
from functools import wraps
import json
import os
import shutil
import sys

import click

from . import __version__, api
from .config import (BUILTIN_DEFAULT_MODEL, GMIError, config_path, mask_key,
                     read_config, resolve_key, resolve_model, save_config, save_key)
from . import media


def options(function):
    @click.option("--api-key", help="API key (prefer GMI_API_KEY to avoid shell history).")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON without prompts.")
    @click.pass_context
    @wraps(function)
    def wrapped(ctx, api_key, as_json, **kwargs):
        root = ctx.find_root().obj or {}
        try:
            return function(api_key=api_key or root.get("api_key"),
                            as_json=as_json or root.get("as_json", False), **kwargs)
        except GMIError as error:
            raise click.ClickException(str(error)) from None
    return wrapped


def emit(value):
    click.echo(json.dumps(value, ensure_ascii=False))


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="gmi", message="%(prog)s %(version)s")
@click.option("--api-key", help="API key; overrides environment and config.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON without prompts.")
@click.pass_context
def main(ctx, api_key, as_json):
    """Use GMI Cloud from the shell."""
    ctx.obj = {"api_key": api_key, "as_json": as_json}
    if ctx.invoked_subcommand is None:
        if as_json:
            raise click.ClickException("Provide a command with --json; interactive sessions require a terminal.")
        from .app.session import run_session
        try:
            run_session(api_key=api_key)
        except GMIError as error:
            raise click.ClickException(str(error)) from None


@main.group()
def auth():
    """Manage local credentials."""


@auth.command()
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the key from standard input.")
@options
def login(api_key, as_json, from_stdin):
    """Verify an API key before saving it privately."""
    if from_stdin:
        key = api_key or sys.stdin.read().strip()
    elif api_key or os.environ.get("GMI_API_KEY"):
        key = resolve_key(api_key)
    elif as_json:
        raise GMIError("Provide --stdin, --api-key or GMI_API_KEY for JSON login.")
    else:
        key = click.prompt("GMI API key", hide_input=True).strip()
    if not key or any(char.isspace() for char in key):
        raise GMIError("Provide one non-empty API key with no whitespace.")
    verify_and_save_key(key)
    result = {"authenticated": True, "key": mask_key(key)}
    emit(result) if as_json else click.echo(f"Saved verified API key {result['key']}.")


def verify_and_save_key(key):
    if not key or any(char.isspace() for char in key):
        raise GMIError("Provide one non-empty API key with no whitespace.")
    api.models(key)
    save_key(key)


@auth.command()
@options
def status(api_key, as_json):
    """Show the masked active key and verify API reachability."""
    key = resolve_key(api_key)
    api.models(key)
    result = {"authenticated": True, "reachable": True, "key": mask_key(key)}
    emit(result) if as_json else click.echo(f"API reachable. Active key: {result['key']}")


@auth.command()
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@options
def logout(api_key, as_json, yes):
    """Remove saved credentials. Environment keys remain active."""
    path = config_path()
    if path.exists():
        if not yes:
            if as_json:
                raise GMIError("Use --yes to remove saved credentials with --json.")
            click.confirm("Remove saved credentials?", abort=True)
        try:
            path.unlink()
        except OSError:
            raise GMIError("Cannot remove credentials; check permissions on ~/.config/gmi.") from None
    emit({"logged_out": True}) if as_json else click.echo("Saved credentials removed. Environment keys remain active.")


def price_per_million(value):
    try:
        return format(Decimal(str(value)) * 1_000_000, ".2f")
    except InvalidOperation:
        return "-"


def model_table(records, current_default=None):
    rows = [[" ", "ID", "CONTEXT", "PROMPT $/1M", "COMPLETION $/1M"]]
    for record in records:
        pricing = record.get("pricing") or {}
        marker = "*" if current_default == record["id"] else " "
        context = record.get("context_length", "-")
        try:
            context = f"{int(context):,}"
        except (TypeError, ValueError):
            context = str(context)
        rows.append([marker, record["id"], context,
                     price_per_million(pricing.get("prompt")),
                     price_per_million(pricing.get("completion"))])
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    lines = []
    for row in rows:
        line = row[0] + " " + row[1].ljust(widths[1])
        line += "  " + row[2].ljust(widths[2])
        line += "  " + row[3].ljust(widths[3])
        line += "  " + row[4].ljust(widths[4])
        lines.append(line.rstrip())
    return "\n".join(lines)


def wrap_stream(chunks, width):
    """Wrap streamed text at spaces while yielding completed words promptly."""
    width = max(1, width)
    line_length = 0
    word = []

    def emit_word():
        nonlocal line_length
        if not word:
            return
        value = "".join(word)
        word.clear()
        if line_length and len(value) <= width and line_length + len(value) > width:
            yield "\n"
            line_length = 0
        while len(value) > width:
            if line_length:
                available = width - line_length
                if available:
                    yield value[:available]
                    value = value[available:]
                yield "\n"
                line_length = 0
            yield value[:width]
            value = value[width:]
            if value:
                yield "\n"
        if value:
            yield value
            line_length += len(value)

    for chunk in chunks:
        for char in chunk:
            if char == "\n":
                yield from emit_word()
                yield "\n"
                line_length = 0
            elif char == " ":
                yield from emit_word()
                if line_length < width:
                    yield " "
                    line_length += 1
                else:
                    yield "\n"
                    line_length = 0
            else:
                word.append(char)
    yield from emit_word()


@main.command("models")
@click.option("--search", default="", help="Filter model IDs and names (case insensitive).")
@options
def list_models(api_key, as_json, search):
    """List models, context lengths and USD prices per million tokens."""
    response = api.models(resolve_key(api_key))
    records = response["data"]
    if search:
        records = [r for r in records if search.casefold() in (r["id"] + " " + r.get("name", "")).casefold()]
    current = resolve_model()
    if as_json:
        emit({**response, "data": [{**record, "default": record["id"] == current} for record in records]})
    else:
        click.echo(model_table(records, current))


@main.group()
def config():
    """Read and update local settings."""


@config.command("get")
@click.argument("name", type=click.Choice(["default_model", "default_image_model", "default_video_model", "default_audio_model", "sandbox_idc"]))
@options
def config_get(api_key, as_json, name):
    """Print a setting."""
    value = read_config().get(name) or (BUILTIN_DEFAULT_MODEL if name == "default_model" else "(auto)")
    if as_json:
        emit({name: value})
    else:
        click.echo(value)


@config.command("set")
@click.argument("name", type=click.Choice(["default_model", "default_image_model", "default_video_model", "default_audio_model", "sandbox_idc"]))
@click.argument("value")
@options
def config_set(api_key, as_json, name, value):
    """Save a setting."""
    save_config(**{name: value})
    result = {name: value}
    emit(result) if as_json else click.echo(f"Set {name} to {value}.")


def _media_run(kind, prompt, model_id, params, output, key, as_json=False, refresh=False, yes=False, no_wait=False):
    client = media.MediaClient(key)
    client.media_type = kind
    request_id = "unknown"
    try:
        records = client.catalogue(refresh=refresh)["models"]
        candidates = [r for r in records if r.get("model_type") == kind and media.usable(r, kind)]
        selected = model_id or read_config().get("default_" + kind + "_model")
        record = next((r for r in candidates if r.get("model") == selected), None) if selected else None
        if selected and not record: raise GMIError(f"No active {kind} model named {selected}.")
        if not record:
            if not candidates: raise GMIError(f"No active {kind} models are available.")
            record = media.default_model(records, kind) or min(candidates, key=lambda r: float((r.get("price_info") or {}).get("price", 10**30)))
        extras = dict(item.split("=", 1) for item in params if "=" in item)
        if len(extras) != len(params): raise GMIError("Parameters must use key=value.")
        payload = media.build_payload(record, prompt, extras)
        estimate, estimate_text = media.estimate_cost(record, payload, prompt)
        if not as_json: click.echo(f"Price: {estimate_text}")
        if estimate is not None and estimate >= 0.25 and not yes and not as_json:
            if not click.confirm("Continue?", default=False):
                raise GMIError("Cancelled.")
        submitted = client.submit(record["model"], payload) if no_wait else client.run(record["model"], payload, on_status=lambda state, elapsed: click.echo(f"{record['model']} {state} ({elapsed:.0f}s)", err=True))
        request_id = submitted.get("request_id") or submitted.get("id", "unknown")
        if not as_json: click.echo(f"Model: {record['model']}\nRequest: {request_id}")
        if no_wait:
            result = submitted; paths = []
        elif submitted.get("status") in media.TERMINAL:
            result = submitted; paths = client.download(result.get("outcome") or {}, output, record["model"])
        else:
            result = submitted
            paths = client.download(result.get("outcome") or {}, output, record["model"])
        if as_json:
            emit({"request_id": request_id, "model": record["model"], "status": result.get("status"), "outcome": result.get("outcome"), "saved_files": [str(p) for p in paths], "estimated_cost": estimate})
        else:
            for path in paths: click.echo(f"Saved {path} ({path.stat().st_size} bytes)")
    except KeyboardInterrupt:
        raise GMIError(f"Stopped waiting. Request id: {request_id}. Resume with gmi media get {request_id}.") from None
    finally: client.close()


@main.group("media")
def media_group():
    """Browse and run image, video, and audio models."""


@media_group.command("models")
@click.option("--type", "model_type", type=click.Choice(["image", "video", "audio", "all"]), default="all")
@click.option("--refresh", is_flag=True)
@options
def media_models(api_key, as_json, model_type, refresh):
    client = media.MediaClient(resolve_key(api_key))
    try:
        records = client.catalogue(refresh=refresh)["models"]
    finally:
        client.close()
    if model_type != "all": records = [r for r in records if r.get("model_type") == model_type]
    if as_json: emit({"models": records})
    else:
        for record in records:
            suffix = "  not supported in the session yet" if record.get("model_type") not in ("image", "video", "audio") else ""
            click.echo(f"{record.get('model')}  {record.get('model_type')}  {media.price_info(record)}{suffix}")


@media_group.command("get")
@click.argument("request_id")
@options
@click.option("--out", "output", default="gmi-output")
def media_get(api_key, as_json, request_id, output):
    client = media.MediaClient(resolve_key(api_key))
    try:
        result = client.poll(request_id, on_status=lambda state, elapsed: click.echo(f"{state} ({elapsed:.0f}s)", err=True))
        paths = client.download(result.get("outcome") or {}, output)
        if as_json: emit({"request_id": request_id, "status": result.get("status"), "outcome": result.get("outcome"), "saved_files": [str(p) for p in paths]})
        else:
            for path in paths: click.echo(str(path))
    finally: client.close()


@media_group.command("list")
@click.option("--limit", type=click.IntRange(min=1), default=20)
@options
def media_list(api_key, as_json, limit):
    """List recent media requests."""
    client = media.MediaClient(resolve_key(api_key))
    try:
        result = client.get(f"requests?limit={limit}&offset=0")
    finally:
        client.close()
    emit(result) if as_json else click.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _register_media_command(kind):
    @main.command(kind)
    @click.argument("prompt")
    @click.option("--model")
    @click.option("--param", "params", multiple=True)
    @click.option("--out", "output", default="gmi-output")
    @click.option("--yes", is_flag=True, help="Skip price confirmation.")
    @click.option("--no-wait", is_flag=True, help="Submit and return without polling.")
    @click.option("--refresh", is_flag=True)
    @options
    def command(api_key, as_json, prompt, model, params, output, yes, no_wait, refresh):
        return _media_run(kind, prompt, model, params, output, resolve_key(api_key), as_json, refresh, yes, no_wait)
    command.__doc__ = "Generate media. Local media files are unsupported; use URLs for media parameters."


for _kind in ("image", "video", "audio"):
    _register_media_command(_kind)


@main.command()
@click.argument("prompt", required=False, default="")
@click.option("--no-stream", is_flag=True, help="Wait for the complete response.")
@click.option("--model", default=None, help=f"Model ID (default: {BUILTIN_DEFAULT_MODEL}, or GMI_MODEL/config).")
@click.option("--system", help="System instruction.")
@click.option("--max-tokens", type=click.IntRange(min=1), help="Maximum output tokens.")
@click.option("--no-retry", is_flag=True, help="Do not retry HTTP 429 responses.")
@click.option("--no-wrap", is_flag=True, help="Do not wrap streamed output to the terminal width.")
@options
def chat(api_key, as_json, prompt, no_stream, model, system, max_tokens, no_retry, no_wrap):
    """Send a prompt, appending standard input when piped."""
    model = resolve_model(model)
    if not prompt and sys.stdin.isatty() and not as_json:
        from .app.session import run_session
        return run_session(api_key=api_key, model=model, system=system, max_tokens=max_tokens)
    key = resolve_key(api_key)
    if not sys.stdin.isatty():
        extra = sys.stdin.read().strip()
        prompt = "\n\n".join(part for part in (prompt, extra) if part)
    if not prompt.strip():
        raise GMIError("Provide a prompt or pipe text into gmi chat.")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, "stream": not (no_stream or as_json)}
    if max_tokens is not None:
        field = "max_completion_tokens" if model.partition("/")[0] == "openai" else "max_tokens"
        payload[field] = max_tokens
    if payload["stream"]:
        tokens = api.stream(key, payload, retry=not no_retry)
        if not no_wrap and sys.stdout.isatty():
            width = shutil.get_terminal_size(fallback=(80, 24)).columns
            tokens = wrap_stream(tokens, width)
        for token in tokens:
            click.echo(token, nl=False)
        click.echo()
    else:
        response = api.complete(key, payload, retry=not no_retry)
        if as_json:
            emit(response)
        else:
            click.echo(response["choices"][0]["message"].get("content") or "")


# Importing the command definition is cheap. Its manifest is loaded only when
# Click needs to resolve a subcommand under ``gmi api``.
from .api_commands import api_group
main.add_command(api_group)

from .sandbox import sandbox_group
main.add_command(sandbox_group)

from .serve import serve_command
main.add_command(serve_command)

from .mcp_server import mcp_group
main.add_command(mcp_group)

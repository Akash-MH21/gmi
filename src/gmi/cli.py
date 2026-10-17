"""Day 1 CLI commands."""

from decimal import Decimal, InvalidOperation
from functools import wraps
import json
import os
import sys

import click

from . import __version__, api
from .config import GMIError, config_path, mask_key, resolve_key, save_key


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


@click.group()
@click.version_option(__version__)
@click.option("--api-key", help="API key; overrides environment and config.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON without prompts.")
@click.pass_context
def main(ctx, api_key, as_json):
    """Use GMI Cloud from the shell."""
    ctx.obj = {"api_key": api_key, "as_json": as_json}


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
    api.models(key)
    save_key(key)
    result = {"authenticated": True, "key": mask_key(key)}
    emit(result) if as_json else click.echo(f"Saved verified API key {result['key']}.")


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
        return format(Decimal(str(value)) * 1_000_000, ".6f").rstrip("0").rstrip(".") or "0"
    except InvalidOperation:
        return "-"


def model_table(records):
    rows = [["ID", "CONTEXT", "PROMPT $/1M", "COMPLETION $/1M"]]
    for record in records:
        pricing = record.get("pricing") or {}
        rows.append([record["id"], str(record.get("context_length", "-")),
                     price_per_million(pricing.get("prompt")),
                     price_per_million(pricing.get("completion"))])
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows)


@main.command("models")
@click.option("--search", default="", help="Filter model IDs and names (case insensitive).")
@options
def list_models(api_key, as_json, search):
    """List models, context lengths and USD prices per million tokens."""
    response = api.models(resolve_key(api_key))
    records = response["data"]
    if search:
        records = [r for r in records if search.casefold() in (r["id"] + " " + r.get("name", "")).casefold()]
    if as_json:
        emit({**response, "data": records})
    else:
        click.echo(model_table(records))


@main.command()
@click.argument("prompt", required=False, default="")
@click.option("--no-stream", is_flag=True, help="Wait for the complete response.")
@click.option("--model", default="openai/gpt-5.4-mini", show_default=True)
@click.option("--system", help="System instruction.")
@click.option("--max-tokens", type=click.IntRange(min=1), help="Maximum output tokens.")
@options
def chat(api_key, as_json, prompt, no_stream, model, system, max_tokens):
    """Send a prompt, appending standard input when piped."""
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
        field = "max_completion_tokens" if model.startswith("openai/") else "max_tokens"
        payload[field] = max_tokens
    if payload["stream"]:
        for token in api.stream(key, payload):
            click.echo(token, nl=False)
        click.echo()
    else:
        response = api.complete(key, payload)
        if as_json:
            emit(response)
        else:
            click.echo(response["choices"][0]["message"].get("content") or "")

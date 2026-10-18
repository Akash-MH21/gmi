"""Rich Markdown streaming in normal terminal scrollback."""

import time
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from .. import api


def render_reply(console, key, payload):
    started = time.monotonic()
    text = ""
    usage = None
    cancelled = False
    events = api.stream_events(key, {**payload, "stream": True, "stream_options": {"include_usage": True}}, retry=False)
    try:
        with Live(Spinner("dots", text="Waiting for reply"), console=console,
                  refresh_per_second=12, vertical_overflow="visible") as live:
            try:
                for chunk in events:
                    if chunk.get("usage") is not None:
                        usage = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        content = choice.get("delta", {}).get("content")
                        if content:
                            text += content
                            live.update(Markdown(text, code_theme="monokai"))
            except KeyboardInterrupt:
                # Clear the live frame before printing the partial reply once.
                cancelled = True
                live.transient = True
            finally:
                if not cancelled:
                    live.update(Markdown(text) if text else Text(""), refresh=True)
        if cancelled:
            raise KeyboardInterrupt
    finally:
        events.close()
    return text, usage, time.monotonic() - started


def status(console, model, usage, elapsed):
    usage = usage or {}
    incoming = usage.get("prompt_tokens")
    outgoing = usage.get("completion_tokens")
    console.print(f"{model} | tokens in {incoming if incoming is not None else 'unknown'}, "
                  f"out {outgoing if outgoing is not None else 'unknown'} | {elapsed:.2f}s", style="dim grey62", markup=False)

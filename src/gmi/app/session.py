"""Inline terminal session, with command behavior supplied by the registry."""

import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .. import __version__
from ..config import GMIError, config_path, mask_key, resolve_key, resolve_model
from .commands import SlashCompleter, registry
from .renderer import render_reply, status
from .state import Conversation


def input_bindings():
    bindings = KeyBindings()

    @bindings.add("enter")
    def send(event):
        buffer = event.current_buffer
        if buffer.text.endswith("\\"):
            buffer.delete_before_cursor(1)
            buffer.insert_text("\n")
        else:
            buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    @bindings.add("escape", "[", "1", ";", "2", "u")
    @bindings.add("escape", "[", "1", "3", ";", "2", "u")
    def newline(event):
        event.current_buffer.insert_text("\n")

    return bindings


class Session:
    def __init__(self, api_key=None, model=None, system=None, max_tokens=None):
        self.api_key = api_key
        self.state = Conversation(model=resolve_model(model), system=system or "")
        self.max_tokens = max_tokens
        self.running = True
        self._models = None
        self.console = Console(highlight=False)
        directory = config_path().parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        history = directory / "history"
        history.touch(mode=0o600, exist_ok=True)
        os.chmod(history, 0o600)
        self.prompt = PromptSession(
            history=FileHistory(str(history)), multiline=True,
            completer=SlashCompleter(registry), complete_while_typing=True,
            key_bindings=input_bindings(),
            style=Style.from_dict({"prompt": "bold ansicyan"}),
        )

    def say(self, text):
        self.console.print(text, markup=False)

    def key(self):
        return resolve_key(self.api_key)

    def secret_prompt(self):
        return PromptSession().prompt("GMI API key: ", is_password=True).strip()

    def confirm(self, text):
        return PromptSession().prompt(text + " [y/N] ").lower() in ("y", "yes")

    def model_records(self):
        if self._models is None:
            from .. import api
            self._models = api.models(self.key())["data"]
        return self._models

    def pick_model(self):
        from .picker import pick_model
        return pick_model(self.model_records(), self.state.model)

    def media_records(self, refresh=False):
        from ..media import MediaClient
        client = MediaClient(self.key())
        try:
            return client.catalogue(refresh=refresh, progress=lambda done, total: self.say(f"Reading model details {done}/{total}"))["models"]
        finally: client.close()

    def run_media(self, kind, argument):
        from ..cli import _media_run
        parts = argument.split()
        if not parts: raise GMIError(f"Usage: /{kind} <prompt> [key=value ...]")
        model = None
        kept = []
        index = 0
        while index < len(parts):
            if parts[index] == "--model" and index + 1 < len(parts): model = parts[index + 1]; index += 2; continue
            kept.append(parts[index]); index += 1
        extras = [item for item in kept if "=" in item]
        prompt = " ".join(item for item in kept if "=" not in item)
        _media_run(kind, prompt, model, extras, "gmi-output", self.key(), False)

    def pick(self, label, choices):
        if not choices:
            self.say("No entries available.")
            return None
        bindings = KeyBindings()

        @bindings.add("enter")
        def select(event):
            buffer = event.current_buffer
            selected = buffer.text if buffer.text in choices else next(
                (choice for choice in choices if buffer.text.casefold() in choice.casefold()), None)
            if selected is not None:
                buffer.text = selected
                buffer.validate_and_handle()
            else:
                buffer.start_completion(select_first=False)

        @bindings.add("escape")
        @bindings.add("c-c")
        @bindings.add("c-d")
        def cancel(event):
            event.app.exit(result=None)

        picker = PromptSession(completer=WordCompleter(choices, ignore_case=True, match_middle=True),
                               complete_while_typing=True, key_bindings=bindings)
        return picker.prompt(f"{label} (type to filter, arrows to select): ",
                             pre_run=lambda: picker.default_buffer.start_completion(select_first=False))

    def reply(self, text):
        key = self.key()
        messages = self.state.messages + [{"role": "user", "content": text}]
        payload = {"model": self.state.model, "messages": messages}
        if self.state.system:
            payload["messages"] = [{"role": "system", "content": self.state.system}] + messages
        if self.max_tokens is not None:
            field = "max_completion_tokens" if self.state.model.partition("/")[0] == "openai" else "max_tokens"
            payload[field] = self.max_tokens
        answer, usage, elapsed = render_reply(self.console, key, payload)
        self.state.messages = messages + [{"role": "assistant", "content": answer}]
        self.state.usage.add(usage)
        status(self.console, self.state.model, usage, elapsed)

    def run(self):
        try:
            key_label = mask_key(self.key())
        except GMIError:
            key_label = "not logged in, run /login"
        banner = Text(f"gmi {__version__}\n{self.state.model} | {key_label}\n{os.getcwd()}\n")
        banner.append("/help for commands, Ctrl+D to quit", style="dim grey62")
        self.console.print(Panel(banner, expand=False, padding=(0, 1)))
        while self.running:
            try:
                text = self.prompt.prompt([("class:prompt", "gmi> ")]).strip()
                if not text:
                    continue
                if text.startswith("/"):
                    registry.dispatch(self, text)
                else:
                    self.reply(text)
            except EOFError:
                break
            except KeyboardInterrupt:
                self.console.print("Cancelled. Ready for your next message.", style="dim yellow", markup=False)
            except GMIError as error:
                self.console.print(f"Error: {error}", style="red", markup=False)
            except OSError:
                self.console.print("Error: Cannot read or write local files; check permissions.", style="red")
        self.say("Goodbye.")


def run_session(**kwargs):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise GMIError("Interactive sessions require a terminal; provide a prompt or use --json with a command.")
    Session(**kwargs).run()

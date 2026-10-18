"""Extensible slash command registry and built-in commands."""

from dataclasses import dataclass
from difflib import get_close_matches

from prompt_toolkit.completion import Completer, Completion

from ..config import GMIError, mask_key
from .state import session_directory


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    handler: object


class Registry:
    def __init__(self):
        self.commands = {}

    def command(self, name, description):
        def register(handler):
            if name in self.commands:
                raise ValueError(f"Duplicate command: {name}")
            self.commands[name] = Command(name, description, handler)
            return handler
        return register

    def dispatch(self, app, text):
        name, argument = parse_command(text)
        command = self.commands.get(name)
        if command is None:
            matches = get_close_matches(name, self.commands, n=1, cutoff=0.5)
            hint = f" Did you mean /{matches[0]}?" if matches else " Use /help."
            raise GMIError(f"Unknown command /{name}.{hint}")
        return command.handler(app, argument)


def parse_command(text):
    parts = text.strip().removeprefix("/").split(maxsplit=1)
    return (parts[0].lower(), parts[1].strip() if len(parts) > 1 else "") if parts else ("", "")


class SlashCompleter(Completer):
    def __init__(self, registry):
        self.registry = registry

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or any(c.isspace() for c in text):
            return
        for name, command in self.registry.commands.items():
            if ("/" + name).startswith(text):
                yield Completion("/" + name, start_position=-len(text), display_meta=command.description)


registry = Registry()


@registry.command("help", "List commands")
def help_command(app, argument):
    for command in registry.commands.values():
        app.say(f"/{command.name:<10} {command.description}")


@registry.command("model", "Search models or switch with /model <id>")
def model(app, argument):
    if not argument:
        argument = app.pick_model()
    if argument:
        app.state.model = argument
        app.say(f"Active model: {argument}")


@registry.command("models", "List live models, optionally filter")
def models(app, argument):
    from ..cli import model_table
    records = app.model_records()
    records = [r for r in records if argument.casefold() in (r["id"] + " " + r.get("name", "")).casefold()]
    app.say(model_table(records, app.state.model))


@registry.command("system", "Show, set, or clear the system prompt")
def system(app, argument):
    if argument:
        app.state.system = "" if argument == "clear" else argument
    app.say("System: " + (app.state.system or "(none)"))


@registry.command("clear", "Start a new conversation")
def clear(app, argument):
    app.state.messages.clear()
    app.say("New conversation.")


@registry.command("save", "Save conversation with an optional name")
def save(app, argument):
    name = argument
    if name:
        from .state import session_path
        if session_path(name).exists() and not app.confirm("Replace saved session?"):
            return
    app.say(f"Saved session: {app.state.save(name)}")


@registry.command("load", "Load a saved conversation or pick one")
def load(app, argument):
    if not argument:
        argument = app.pick("Session", sorted(p.stem for p in session_directory().glob("*.json")))
    if argument:
        app.state.load(argument)
        app.say(f"Loaded session: {argument}; model: {app.state.model}")


@registry.command("usage", "Show API token totals for this session")
def usage(app, argument):
    u = app.state.usage
    app.say(f"Session usage: tokens in {u.input}, out {u.output}; replies with unknown usage {u.unknown_replies}")


@registry.command("login", "Verify and save an API key with hidden input")
def login(app, argument):
    from ..cli import verify_and_save_key
    key = app.secret_prompt()
    verify_and_save_key(key)
    app.api_key = key
    app.say(f"Saved verified API key {mask_key(key)}.")


@registry.command("exit", "Quit")
def exit_command(app, argument):
    app.running = False

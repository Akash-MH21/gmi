"""Substring model search and an inline keyboard picker."""

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.styles import Style


def rank_models(records, text, active):
    query = text.strip().casefold()
    terms = query.split()
    matches = [r for r in records if all(term in r["id"].casefold() for term in terms)]

    def rank(record):
        identifier = record["id"].casefold()
        if not query:
            group = 0 if record["id"] == active else 1
        elif identifier == query:
            group = 0
        elif identifier.partition("/")[2].startswith(query):
            group = 1
        else:
            group = 2
        return group, identifier

    return sorted(matches, key=rank)


def pick_model(records, active):
    from ..cli import price_per_million

    selected = 0
    bindings = KeyBindings()

    def changed(buffer):
        nonlocal selected
        selected = 0

    buffer = Buffer(on_text_changed=changed)

    def matches():
        return rank_models(records, buffer.text, active)

    def rows():
        records = matches()
        if not records:
            return [("class:muted", "No models match. Enter or Esc keeps the current model.")]
        fragments = []
        start = max(0, selected - 9)
        for index in range(start, min(start + 10, len(records))):
            record = records[index]
            pricing = record.get("pricing") or {}
            context = record.get("context_length")
            context = f"{context:,}" if isinstance(context, int) else str(context or "-")
            marker = "*" if record["id"] == active else " "
            style = "reverse" if index == selected else ""
            fragments.append((style, f"{'>' if index == selected else ' '} {marker} {record['id']}"))
            fragments.append((style + " class:muted", f"  {context} ctx  $/1M {price_per_million(pricing.get('prompt'))}/{price_per_million(pricing.get('completion'))}"))
            fragments.append(("", "\n"))
        return fragments[:-1]

    @bindings.add("up")
    @bindings.add("down")
    def move(event):
        nonlocal selected
        selected = max(0, min(selected + (1 if event.key_sequence[0].key == "down" else -1), len(matches()) - 1))

    @bindings.add("enter")
    def choose(event):
        records = matches()
        event.app.exit(result=records[selected]["id"] if records else None)

    @bindings.add("escape")
    @bindings.add("c-c")
    @bindings.add("c-d")
    def cancel(event):
        event.app.exit(result=None)

    control = BufferControl(buffer=buffer, input_processors=[BeforeInput("Model (type to filter, arrows to select): ")])
    app = Application(
        layout=Layout(HSplit([Window(control, height=1), Window(FormattedTextControl(rows))])),
        key_bindings=bindings, full_screen=False, erase_when_done=True,
        style=Style.from_dict({"muted": "#888888"}),
    )
    return app.run()

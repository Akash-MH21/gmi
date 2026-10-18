"""Terminal-independent command, conversation, and input checks."""

import stat
from types import SimpleNamespace

from prompt_toolkit.document import Document
import pytest

from gmi.app.commands import Registry, SlashCompleter, parse_command, registry
from gmi.app.state import Conversation, Usage, session_path
from gmi.config import BUILTIN_DEFAULT_MODEL, GMIError


def test_registry_parsing_and_suggestions():
    assert parse_command(' /SYSTEM  be brief ') == ('system', 'be brief')
    commands = Registry()
    received = []
    commands.command('help', 'Help')(lambda app, arg: received.append(arg))
    commands.dispatch(None, '/help details')
    assert received == ['details']
    with pytest.raises(ValueError, match='Duplicate'):
        commands.command('help', 'Again')(lambda app, arg: None)
    with pytest.raises(GMIError, match='Did you mean /help'):
        commands.dispatch(None, '/hepl')
    with pytest.raises(GMIError, match='Use /help'):
        commands.dispatch(None, '/zzzzzzzz')


def test_completion_on_slash():
    completions = list(SlashCompleter(registry).get_completions(Document('/'), None))
    assert {c.text for c in completions} == {'/' + name for name in registry.commands}
    assert all(c.display_meta_text for c in completions)
    assert [c.text for c in SlashCompleter(registry).get_completions(Document('/mod'), None)] == ['/model', '/models']


def test_save_load_and_model_switch(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    state = Conversation(system='Be brief', messages=[{'role': 'user', 'content': 'hello'}])
    app = SimpleNamespace(state=state, say=lambda text: None)
    registry.dispatch(app, '/model ' + BUILTIN_DEFAULT_MODEL)
    assert state.messages == [{'role': 'user', 'content': 'hello'}]
    assert state.model == BUILTIN_DEFAULT_MODEL
    name = state.save('round-trip')
    assert stat.S_IMODE(session_path(name).stat().st_mode) == 0o600
    restored = Conversation()
    restored.load(name)
    assert restored == state
    assert state.save()
    with pytest.raises(GMIError):
        state.save('../escape')
    session_path('broken').write_text('{}')
    with pytest.raises(GMIError, match='Cannot load'):
        state.load('broken')
    assert state.messages == restored.messages


def test_usage_only_counts_api_numbers():
    usage = Usage()
    usage.add({'prompt_tokens': 12, 'completion_tokens': 2})
    usage.add(None)
    usage.add({'prompt_tokens': 5})
    assert (usage.input, usage.output, usage.unknown_replies) == (17, 2, 2)


def test_system_clear_preserves_session_usage():
    state = Conversation(messages=[{'role': 'user', 'content': 'hello'}])
    app = SimpleNamespace(state=state, say=lambda text: None)
    registry.dispatch(app, '/system Be brief')
    assert state.system == 'Be brief'
    registry.dispatch(app, '/system clear')
    assert not state.system
    state.usage.add({'prompt_tokens': 1, 'completion_tokens': 2})
    registry.dispatch(app, '/clear')
    assert state.messages == []
    assert state.usage.output == 2

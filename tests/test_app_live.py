"""Drive the installed application through a real pseudo-terminal and live API."""

import os
from pathlib import Path
import sys
import time

import pexpect
import pyte
import pytest

from gmi import __version__

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get('GMI_API_KEY'), reason='GMI_API_KEY is not set')]


class Terminal:
    def __init__(self, transcript=None):
        self.screen = pyte.Screen(120, 40)
        self.stream = pyte.Stream(self.screen)
        self.transcript = transcript

    def write(self, text):
        self.stream.feed(text)
        if self.transcript:
            self.transcript.write(text)

    def flush(self):
        if self.transcript:
            self.transcript.flush()


def settle(child):
    """Render pending terminal updates, with a bounded idle timeout."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            child.read_nonblocking(65536, timeout=0.3)
        except pexpect.TIMEOUT:
            return
    pytest.fail('Terminal did not settle within five seconds')


def drive_app(home, transcript=None):
    env = {**os.environ, 'HOME': str(home), 'TERM': 'xterm-256color', 'PROMPT_TOOLKIT_NO_CPR': '1',
           'GMI_MODEL': 'openai/gpt-6.1-sol'}
    env.pop('NO_COLOR', None)
    child = pexpect.spawn(str(Path(sys.executable).parent / 'gmi'),
                          ['chat', '--max-tokens', '16'], env=env, encoding='utf-8', timeout=180,
                          dimensions=(40, 120))
    terminal = Terminal(transcript)
    child.logfile_read = terminal
    try:
        child.expect('/help for commands')
        child.expect('gmi>')
        screen = terminal.screen.display
        top = next(i for i, line in enumerate(screen) if line.startswith('╭'))
        assert screen[top + 5].startswith('╰')
        assert f'gmi {__version__}' in screen[top + 1]
        assert str(Path.cwd()) in screen[top + 3]
        assert 'Ctrl+D to quit' in screen[top + 4]
        child.send('/')
        child.expect('List commands')
        child.send('models sol\r')
        child.expect('CONTEXT')
        child.expect('openai/gpt-6.1-sol')
        child.expect('gmi>')
        child.sendline('/model')
        child.expect(r'Model \(type to filter')
        settle(child)
        rows = [line.strip() for line in terminal.screen.display if line.startswith('>')]
        assert rows[0].startswith('> * openai/gpt-6.1-sol ')
        child.send('6.1')
        settle(child)
        screen = terminal.screen.display
        prompt_row = next(i for i, line in enumerate(screen) if 'Model (type to filter' in line)
        assert screen[prompt_row].rstrip().endswith('6.1')
        assert screen[prompt_row + 1].startswith('> * openai/gpt-6.1-sol ')
        child.sendline('')
        child.expect('Active model: openai/gpt-6.1-sol')
        child.expect('gmi>')
        # Reopen from the session cache, cancel, then exercise no matches.
        child.sendline('/model')
        child.expect(r'Model \(type to filter', timeout=5)
        child.send('\x1b')
        child.expect('gmi>', timeout=5)
        child.sendline('/model')
        child.expect(r'Model \(type to filter', timeout=5)
        child.send('no-such-model')
        child.expect('No models match.')
        child.sendline('')
        child.expect('gmi>')
        child.send('draft')
        child.sendcontrol('c')
        child.expect('Cancelled. Ready for your next message.')
        settle(child)
        screen = terminal.screen.display
        cancelled = next(i for i, line in enumerate(screen) if 'Cancelled. Ready' in line)
        assert screen[cancelled - 1].startswith('gmi> draft')
        assert terminal.screen.buffer[cancelled][0].fg == 'brown'
        child.sendline('Reply with: ok')
        child.expect('Waiting for reply')
        child.sendcontrol('c')
        child.expect('Cancelled. Ready for your next message.')
        settle(child)
        screen = terminal.screen.display
        cancelled = max(i for i, line in enumerate(screen) if 'Cancelled. Ready' in line)
        assert screen[cancelled - 1].startswith('gmi> Reply with: ok')
        child.sendline('Reply with: ok')
        child.expect(r'tokens in (\d+|unknown), out (\d+|unknown)')
        assert 'ok' in child.before.lower()
        child.expect('gmi>')
        screen = terminal.screen.display
        status_row = next(i for i, line in enumerate(screen) if '| tokens in' in line)
        assert terminal.screen.buffer[status_row][0].fg == '9e9e9e'
        child.sendline('/save pty-check')
        child.expect('Saved session: pty-check')
        child.expect('gmi>')
        child.sendline('/load pty-check')
        child.expect('Loaded session: pty-check')
        child.expect('gmi>')
        child.sendline('/usage')
        child.expect('Session usage: tokens in')
        child.expect('gmi>')
        child.sendline('/exit')
        child.expect('Goodbye.')
        child.expect(pexpect.EOF)
        child.close()
        assert child.exitstatus == 0
    finally:
        child.close(force=True)


def test_live_interactive_app(tmp_path):
    drive_app(tmp_path)

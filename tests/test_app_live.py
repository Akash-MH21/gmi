"""Drive the installed application through a real pseudo-terminal and live API."""

import os
from io import StringIO
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
    # pexpect only drains the PTY while expect/read is called.  Asking it to
    # expect TIMEOUT gives the screen a short chance to consume pending writes.
    child.expect(pexpect.TIMEOUT, timeout=0.5)


def wait_for_streamed_marker(child, terminal, marker):
    """Wait for marker text rendered by Rich, after the echoed input."""
    # Live reasoning can delay the first visible token beyond 30 seconds.
    # Allow the API client's 120-second read timeout before failing the test.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        child.expect(pexpect.TIMEOUT, timeout=0.5)
        if any(marker in line and not line.lstrip().startswith('gmi>')
               for line in terminal.screen.display):
            return
        errors = [line.strip() for line in terminal.screen.display if line.startswith('Error:')]
        assert not errors, '\n'.join(errors)
    raise AssertionError('stream did not render the first reply text')


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
        child.expect(r'gmi> ')
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
        child.sendline('/model not-a-real-model')
        child.expect('Unknown model not-a-real-model. Use /model to pick one, or /models <text> to search.')
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
    for attempt in range(2):
        transcript = StringIO()
        try:
            drive_app(tmp_path, transcript)
            return
        except (AssertionError, pexpect.TIMEOUT):
            if attempt == 0 and any(word in transcript.getvalue().lower() for word in ('429', 'overloaded')):
                continue
            raise


def _run_cancelled_stream(tmp_path, transcript):
    """Ctrl+C removes Rich's live frame before printing the partial reply."""
    env = {**os.environ, 'HOME': str(tmp_path), 'TERM': 'xterm-256color',
           'PROMPT_TOOLKIT_NO_CPR': '1', 'GMI_MODEL': 'openai/gpt-6.1-sol'}
    child = pexpect.spawn(str(Path(sys.executable).parent / 'gmi'),
                          ['chat', '--max-tokens', '16'], env=env, encoding='utf-8',
                          timeout=180, dimensions=(40, 120))
    terminal = Terminal(transcript)
    child.logfile_read = terminal
    try:
        child.expect('/help for commands')
        child.expect('gmi>')
        child.sendline('Write a 600 word essay about clouds. Begin with CLOUD_REPLY_MARKER.')
        child.expect('Waiting for reply')
        # Wait for the first generated text before interrupting the stream.
        wait_for_streamed_marker(child, terminal, 'CLOUD_REPLY_MARKER')
        child.sendcontrol('c')
        child.expect('Cancelled. Ready for your next message.', timeout=10)
        settle(child)

        screen = terminal.screen.display
        nonempty = [line.rstrip() for line in screen if line.strip()]
        assert all(left != right for left, right in zip(nonempty, nonempty[1:]))
        cancelled = next(i for i, line in enumerate(screen)
                         if 'Cancelled. Ready for your next message.' in line)
        partial = next(i for i, line in enumerate(screen[:cancelled])
                       if 'CLOUD_REPLY_MARKER' in line)
        assert partial < cancelled
    finally:
        child.close(force=True)


def test_live_cancelled_stream_has_one_partial_reply(tmp_path):
    for attempt in range(2):
        transcript = StringIO()
        try:
            _run_cancelled_stream(tmp_path, transcript)
            return
        except (AssertionError, pexpect.TIMEOUT):
            if attempt == 0 and any(word in transcript.getvalue().lower() for word in ('429', 'overloaded')):
                # The live API asks for a minute before retrying an overload.
                time.sleep(60)
                continue
            raise

"""Drive the installed application through a real pseudo-terminal and live API."""

import os
from pathlib import Path
import sys

import pexpect
import pytest

pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get('GMI_API_KEY'), reason='GMI_API_KEY is not set')]


def drive_app(home, transcript=None):
    env = {**os.environ, 'HOME': str(home), 'TERM': 'xterm-256color', 'PROMPT_TOOLKIT_NO_CPR': '1',
           'GMI_MODEL': 'openai/gpt-6.1-sol'}
    child = pexpect.spawn(str(Path(sys.executable).parent / 'gmi'),
                          ['chat', '--max-tokens', '16'], env=env, encoding='utf-8', timeout=180,
                          dimensions=(40, 120))
    child.logfile_read = transcript
    try:
        child.expect('/help for commands')
        child.expect('gmi>')
        child.send('/')
        child.expect('List commands')
        child.send('models sol\r')
        child.expect('CONTEXT')
        child.expect('openai/gpt-6.1-sol')
        child.expect('gmi>')
        child.sendline('Reply with: ok')
        child.expect(r'tokens in (\d+|unknown), out (\d+|unknown)')
        assert 'ok' in child.before.lower()
        child.expect('gmi>')
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

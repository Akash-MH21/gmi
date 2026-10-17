"""Integration checks against the real endpoint, never an API mock."""

import json
import os
import secrets
import stat

from click.testing import CliRunner
import pytest

from gmi.cli import main
from gmi.config import config_path, read_key, save_key


pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("GMI_API_KEY"), reason="GMI_API_KEY is not set")]
MODEL = "openai/gpt-5.4-nano"


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return CliRunner(mix_stderr=False)


def run(runner, args, **kwargs):
    result = runner.invoke(main, args, **kwargs)
    # CLI diagnostics are deliberately safe to show; never include stdin keys.
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    return result.stdout


def test_live_models(runner):
    response = json.loads(run(runner, ["models", "--json"]))
    assert any(record["id"] == MODEL for record in response["data"])
    filtered = json.loads(run(runner, ["models", "--search", "NANO", "--json"]))
    assert filtered["data"]
    assert all("nano" in (record["id"] + record.get("name", "")).lower() for record in filtered["data"])
    assert MODEL in run(runner, ["models", "--search", MODEL])


def test_live_login_status_logout(runner, monkeypatch):
    key = os.environ["GMI_API_KEY"]
    monkeypatch.delenv("GMI_API_KEY")
    result = json.loads(run(runner, ["auth", "login", "--stdin", "--json"], input=key + "\n"))
    assert result["authenticated"]
    if key in json.dumps(result):
        pytest.fail("Login output exposed the credential")
    assert secrets.compare_digest(read_key(), key)
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600
    status = json.loads(run(runner, ["auth", "status", "--json"]))
    assert status["reachable"]
    if key in json.dumps(status):
        pytest.fail("Status output exposed the credential")
    run(runner, ["auth", "logout", "--yes", "--json"])
    assert not config_path().exists()


@pytest.mark.parametrize("mode", [[], ["--no-stream"], ["--json"]])
def test_live_chat(runner, mode):
    output = run(runner, ["chat", "Reply with hello.", "--model", MODEL, "--max-tokens", "16", *mode])
    if mode == ["--json"]:
        response = json.loads(output)
        assert response["choices"][0]["message"]["content"]
        assert response["usage"]["completion_tokens"] <= 16
    else:
        assert "hello" in output.lower()


def test_live_piped_input_and_system(runner):
    output = run(runner, ["chat", "Repeat the word in the input.", "--system", "Reply only with the supplied word.",
                          "--model", MODEL, "--max-tokens", "16", "--json"], input="pineapple\n")
    response = json.loads(output)
    assert "pineapple" in response["choices"][0]["message"]["content"].lower()
    assert response["usage"]["completion_tokens"] <= 16


def test_live_rejected_key_does_not_overwrite_config(runner):
    save_key("existing-local-credential")
    result = runner.invoke(main, ["auth", "login", "--api-key", "invalid-live-test-key", "--json"])
    assert result.exit_code == 1
    assert "401" in result.stderr
    assert result.stdout == ""
    assert read_key() == "existing-local-credential"

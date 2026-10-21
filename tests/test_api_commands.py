import json
from click.testing import CliRunner

from gmi.api_commands import _credential, render_markdown
from gmi.cli import main


def test_compute_alias_precedence(monkeypatch):
    monkeypatch.setenv("GMI_API_KEY", "normal-secret")
    monkeypatch.setenv("GMI_SANDBOX_API_KEY", "sandbox-secret")
    monkeypatch.setenv("GMI_COMPUTE_API_KEY", "compute-secret")
    assert _credential("sandbox")[:2] == ("compute-secret", "GMI_COMPUTE_API_KEY")
    monkeypatch.delenv("GMI_COMPUTE_API_KEY")
    assert _credential("cluster")[:2] == ("sandbox-secret", "GMI_SANDBOX_API_KEY")
    assert _credential("iam")[:2] == ("normal-secret", "GMI_API_KEY")
    assert _credential("sandbox", "flag-secret")[:2] == ("flag-secret", "--token")


def test_markdown_has_sources_and_no_values():
    secret = "gmi_fake_secret_value"
    report = {"keys": [{"source": "GMI_COMPUTE_API_KEY", "services": ["sandbox"], "scope": "compute", "product": "Compute"}],
              "results": [{"service": "sandbox", "operation": "list", "status": 400, "verdict": "bad request"}],
              "skipped": [{"service": "sandbox", "operation": "catalog", "reasons": ["needs a required query parameter"]}],
              "summary": {"by_service": {"sandbox": {"run": 1, "ok": 0, "needs another key type": 0, "bad request": 1}}, "by_verdict": {"bad request": 1}}}
    output = render_markdown(report)
    assert "GMI_COMPUTE_API_KEY" in output
    assert "bad request" in output
    assert secret not in output


def test_api_check_markdown_option_exists():
    result = CliRunner().invoke(main, ["api", "check", "--help"])
    assert result.exit_code == 0
    assert "--idc-name" in result.output
    assert "--markdown" in result.output

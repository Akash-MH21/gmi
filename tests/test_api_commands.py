import json
import re
from click.testing import CliRunner

from gmi import api_commands
from gmi.api_commands import _check_skip_reasons, _credential, manifest, render_markdown
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


def test_get_sandbox_dry_run_requires_and_substitutes_id():
    runner = CliRunner()
    args = ["api", "sandbox", "get-sandbox"]
    result = runner.invoke(main, args + ["SOME_ID", "--dry-run", "--token", "fake-key-for-offline-test"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["url"].endswith("/sandboxes/SOME_ID")
    assert "fake-key-for-offline-test" not in result.output
    missing = runner.invoke(main, args + ["--dry-run", "--token", "fake-key-for-offline-test"])
    assert missing.exit_code == 2
    assert "Missing argument 'ID'" in missing.output
    grouped = runner.invoke(main, ["api", "sandbox", "Sandbox", "get-sandbox", "SOME_ID", "--dry-run"])
    assert grouped.exit_code == 0, grouped.output
    assert json.loads(grouped.output)["url"].endswith("/sandboxes/SOME_ID")


def test_check_skip_rules_for_every_manifest_operation():
    for op in manifest()["operations"]:
        for idc_name in (None, "example-idc"):
            reasons = _check_skip_reasons(op, idc_name)
            assert ("not a GET" in reasons) == (op["method"] != "GET"), op
            assert ("needs a path parameter" in reasons) == bool(re.findall(r"\{[^{}]+\}", op["path"])), op
            missing = any(p["required"] and (p["name"] != "idc_name" or not idc_name) for p in op["query_parameters"])
            assert ("needs a required query parameter" in reasons) == missing, op


def test_check_skips_unbound_parameters_without_http(monkeypatch, tmp_path):
    # This verifies routing and report output. Any network attempt is a failure.
    unsafe = [op for op in manifest()["operations"] if op["method"] == "GET" and
              (op["path_parameters"] or any(p["required"] and p["name"] != "idc_name" for p in op["query_parameters"]))]
    assert unsafe
    assert any(op["name"] == "download-sandbox-file" for op in unsafe)
    monkeypatch.setattr(api_commands, "_ops", lambda service=None: unsafe)

    def no_http(*args, **kwargs):
        raise AssertionError("A skipped operation attempted HTTP")

    monkeypatch.setattr(api_commands.httpx, "Client", no_http)
    output = tmp_path / "coverage.md"
    result = CliRunner().invoke(main, ["api", "check", "--idc-name", "example-idc", "--json", "--markdown", str(output)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["results"] == []
    assert report["keys"] == []
    assert report["summary"]["not_run"] == len(unsafe)
    skips = {(row["service"], row["operation"]): row["reasons"] for row in report["skipped"]}
    for op in unsafe:
        expected = []
        if op["path_parameters"]:
            expected.append("needs a path parameter")
        if any(p["required"] and p["name"] != "idc_name" for p in op["query_parameters"]):
            expected.append("needs a required query parameter")
        assert skips[op["service"], op["name"]] == expected
    assert output.read_text() == render_markdown(report)


def test_idc_name_only_satisfies_its_own_required_query():
    operation = {"method": "GET", "path_parameters": [], "query_parameters": [{"name": "idc_name", "required": True}]}
    assert _check_skip_reasons(operation) == ["needs a required query parameter"]
    assert _check_skip_reasons(operation, "example-idc") == []
    operation["query_parameters"].append({"name": "path", "required": True})
    assert _check_skip_reasons(operation, "example-idc") == ["needs a required query parameter"]

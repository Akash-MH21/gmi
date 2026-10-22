"""Offline contract tests. Data plane behavior is unverified live."""
import httpx
from click.testing import CliRunner

from gmi.cli import main


def test_platform_deletion_stops_after_one_poll(monkeypatch, tmp_path):
    from gmi import sandbox
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('GMI_COMPUTE_API_KEY', 'compute-secret')
    polls = []
    def handler(request):
        if request.url.path.endswith('/products'):
            return httpx.Response(200, json={'data': []})
        if request.method == 'POST':
            return httpx.Response(201, json={'data': {'id': 'box', 'sandbox_access_token': 'fake-secret'}})
        polls.append(request)
        return httpx.Response(200, json={'data': {'state': 'deleting', 'deletion': {
            'code': 'Sandbox.BillingNoPermission', 'initiator': 'billing',
            'message': 'Deleted by the platform: billing order could not be created'}}})
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(handler))
    result = CliRunner().invoke(main, ['sandbox', 'create', 'template', '--wait', '--yes'])
    assert result.exit_code != 0
    assert len(polls) == 1
    assert 'Sandbox.BillingNoPermission' in result.output
    assert 'billing order could not be created' in result.output
    assert 'billing' in result.output
    assert 'not a gmi error' in result.output
    assert 'fake-secret' not in result.output

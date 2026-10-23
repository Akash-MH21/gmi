"""Offline contract tests. Owner live verification is recorded in docs/AGENTBOX.md."""
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
    result = CliRunner(mix_stderr=False).invoke(main, ['sandbox', 'create', 'template', '--wait', '--yes'])
    assert result.exit_code != 0
    assert len(polls) == 1
    assert 'Sandbox.BillingNoPermission' in (result.stdout + result.stderr)
    assert 'billing order could not be created' in (result.stdout + result.stderr)
    assert 'billing' in (result.stdout + result.stderr)
    assert 'not a gmi error' in (result.stdout + result.stderr)
    assert 'fake-secret' not in (result.stdout + result.stderr)

import hashlib
import json
import pytest

from gmi import sandbox
from gmi.config import save_config

COMPUTE = 'fake-compute-credential-112233'
ACCESS = 'fake-sandbox-secret-445566'
TRAFFIC = 'fake-traffic-secret-778899'


class FakeCloud:
    """Separate control and data hosts with assertions at the HTTP boundary."""
    def __init__(self):
        self.requests = []
        self.states = ['running']
        self.build_states = ['ready']
        self.exit_code = 0
        self.exec_error = None
        self.products = [{'product': 'gmi.sandbox.small', 'status': 'active',
                          'resources': {'vcpu': 2, 'memory_mb': 4096}}]
        self.templates = []
        self.template_detail = {}
        self.sandboxes = [{'id': 'box', 'state': 'running'}]
        self.sandbox_detail = {}
        self.execution_pending = False

    def handler(self, request):
        self.requests.append(request)
        path = request.url.path
        if request.url.host == 'box.example.test':
            assert request.headers.get('X-Access-Token') == ACCESS
            assert 'Authorization' not in request.headers
            if path == '/executions':
                assert request.method == 'POST'
                assert dict(request.url.params) == {'wait': 'true', 'wait_timeout_seconds': '25'}
                body = json.loads(request.content)
                assert body['action'] == 'exec'
                assert set(body['parameters']) == {'command'}
                if self.exec_error:
                    raise self.exec_error
                if self.execution_pending:
                    return httpx.Response(202, json={'execution_id': 'exec', 'status': 'running'})
                return self.execution()
            if path == '/executions/exec':
                return self.execution()
            if path == '/files':
                assert request.url.params['path'] == '/home/user/data.bin'
                assert request.url.params.get('username') == 'user'
                if request.method == 'GET':
                    return httpx.Response(200, content=b'file-content\x00')
                assert 'multipart/form-data' in request.headers['Content-Type']
                assert b'file-content\x00' in request.content
                assert b'name="file"' in request.content
                return httpx.Response(200, json={'path': '/home/user/data.bin', 'type': 'file'})
            raise AssertionError(f'Unexpected data request {request.method} {path}')
        assert request.url.host == 'console.gmicloud.ai'
        assert request.headers.get('Authorization') == 'Bearer ' + COMPUTE
        assert 'X-Access-Token' not in request.headers
        if path.endswith('/products'):
            return httpx.Response(200, json={'data': self.products})
        if path.endswith('/templates'):
            if request.method == 'GET':
                return httpx.Response(200, json={'items': self.templates, 'total': len(self.templates)})
            body = json.loads(request.content)
            assert request.headers['Idempotency-Key']
            assert body['resources'] == {'type': 'preset', 'product': 'gmi.sandbox.small'}
            assert body['build']['source'] == {'type': 'image', 'image': 'ubuntu:24.04'}
            return httpx.Response(201, json={'data': {'id': 'template', 'build_id': 'build', 'status': 'waiting'}})
        if path.endswith('/templates/template'):
            if request.method == 'DELETE':
                return httpx.Response(202, json={'data': {'id': 'template', 'deleted': True}})
            state = self.build_states.pop(0) if len(self.build_states) > 1 else self.build_states[0]
            return httpx.Response(200, json={'data': {'id': 'template', 'latest_build_id': 'build',
                                                    'latest_build_status': state, **self.template_detail}})
        if path.endswith('/builds/build/logs'):
            offset = int(request.url.params['offset'])
            return httpx.Response(200, json={'data': {'entries': [{'message': f'line {offset}'}],
                                                    'has_more': offset == 0, 'next_offset': offset + 1}})
        if path.endswith('/builds/build'):
            return httpx.Response(200, json={'data': {'source': {'type': 'image', 'image': 'ubuntu:24.04'},
                                                    'product': 'gmi.sandbox.small',
                                                    'failure': {'code': 'Build.Error', 'message': 'package installation failed'}}})
        if path.endswith('/sandboxes'):
            if request.method == 'GET':
                return httpx.Response(200, json={'items': self.sandboxes, 'total': len(self.sandboxes)})
            body = json.loads(request.content)
            assert body['template_id'] == 'template'
            assert request.headers['Idempotency-Key']
            return httpx.Response(201, json={'data': {'id': 'box', 'sandbox_key': 'old-host', 'domain': 'old.test',
                                                    'sandbox_access_token': 'old-secret-token', 'traffic_access_token': TRAFFIC}})
        if path.endswith('/sandboxes/box/connect'):
            return httpx.Response(200, json={'data': {'sandbox_key': 'box', 'domain': 'example.test',
                                                    'sandbox_access_token': ACCESS}})
        if path.endswith('/sandboxes/box/timeout'):
            assert json.loads(request.content)['timeout'] == 900
            return httpx.Response(200, json={'data': {'id': 'box', 'new_end_at': '2026-10-22T12:15:00Z'}})
        if path.endswith('/sandboxes/box'):
            if request.method == 'DELETE':
                return httpx.Response(202, json={'data': {'id': 'box', 'state': 'deleting'}})
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            detail = {'id': 'box', 'state': state, 'end_at': '2026-10-22T12:05:00Z',
                      'sandbox_access_token': ACCESS, 'traffic_access_token': TRAFFIC,
                      'metadata': {'echo': ACCESS, 'traffic_access_token': TRAFFIC}}
            detail.update(self.sandbox_detail)
            if state in ('deleted', 'deleting'):
                detail.setdefault('deletion', {'code': 'Sandbox.BillingNoPermission', 'initiator': 'billing',
                                               'message': 'Deleted by platform: billing is not permitted'})
            return httpx.Response(200, json={'data': detail})
        raise AssertionError(f'Unexpected control request {request.method} {path}')

    def execution(self):
        return httpx.Response(200, json={'execution_id': 'exec', 'status': 'succeeded' if self.exit_code == 0 else 'failed',
                                        'exit_code': self.exit_code, 'stdout': 'hello\n', 'stderr': 'diagnostic\n'})


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    for name in ('GMI_API_KEY', 'GMI_TOKEN', 'GMI_SANDBOX_API_KEY', 'GMI_SANDBOX_IDC_NAME'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GMI_COMPUTE_API_KEY', COMPUTE)
    fake = FakeCloud()
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(fake.handler))
    monkeypatch.setattr(sandbox.time, 'sleep', lambda seconds: None)
    return fake


def invoke(args):
    return CliRunner(mix_stderr=False).invoke(main, ['sandbox', *args])


def assert_ok(result):
    assert result.exit_code == 0, ((result.stdout + result.stderr), result.exception)


@pytest.mark.parametrize('state', ['deleting', 'deleted'])
@pytest.mark.parametrize('wait', [True, False])
def test_deleted_states(cloud, state, wait):
    cloud.states = [state]
    result = invoke(['create', 'template', '--yes', *(['--wait'] if wait else [])])
    assert result.exit_code == 1
    assert 'Sandbox.BillingNoPermission' in (result.stdout + result.stderr)
    assert 'billing is not permitted' in (result.stdout + result.stderr)
    assert 'not a gmi error' in (result.stdout + result.stderr)
    assert len([r for r in cloud.requests if r.method == 'GET' and r.url.path.endswith('/sandboxes/box')]) == 1


@pytest.mark.parametrize('as_json', [False, True])
@pytest.mark.parametrize('show_token', [False, True])
def test_creation_masks_tokens_and_reports_expiry(cloud, as_json, show_token):
    result = invoke(['create', 'template', '--yes', '--wait', '--env', 'HELLO=world',
                     *(['--json'] if as_json else []), *(['--show-token'] if show_token else [])])
    assert_ok(result)
    assert COMPUTE not in (result.stdout + result.stderr)
    assert 'old-secret-token' not in (result.stdout + result.stderr)
    for token in (ACCESS, TRAFFIC):
        assert (result.stdout + result.stderr).count(token) == (1 if show_token and as_json else 0)
    assert ('Warning:' in (result.stdout + result.stderr)) == (show_token and as_json)
    assert '2026-10-22T12:05:00Z' in result.stdout
    assert 'box' in result.stdout
    create = next(r for r in cloud.requests if r.method == 'POST' and r.url.path.endswith('/sandboxes'))
    assert json.loads(create.content)['env_vars'] == {'HELLO': 'world'}
    if as_json:
        assert json.loads(result.stdout)['id'] == 'box'


def test_waits_for_build_at_five_second_intervals(cloud, monkeypatch):
    sleeps = []
    monkeypatch.setattr(sandbox.time, 'sleep', sleeps.append)
    cloud.build_states = ['waiting', 'building', 'ready']
    result = invoke(['templates', 'create', '--name', 'demo', '--cmd', 'echo one', '--cmd', 'echo two',
                     '--start-cmd', 'sleep infinity', '--wait', '--yes', '--json'])
    assert_ok(result)
    assert sleeps == [5, 5]
    request = next(r for r in cloud.requests if r.method == 'POST')
    body = json.loads(request.content)
    assert body['build']['commands'] == ['echo one', 'echo two']
    assert body['build']['start_cmd'] == 'sleep infinity'
    assert json.loads(result.stdout)['latest_build_status'] == 'ready'


def test_build_error(cloud):
    cloud.build_states = ['error']
    result = invoke(['templates', 'create', '--name', 'demo', '--wait', '--yes'])
    assert result.exit_code == 1
    assert 'package installation failed' in (result.stdout + result.stderr)
    assert 'Build.Error' in (result.stdout + result.stderr)
    assert not any(r.url.path.endswith('/sandboxes') for r in cloud.requests)


@pytest.mark.parametrize('command', [['kill', 'box'], ['templates', 'delete', 'template']])
def test_nonterminal_kill_refuses_without_yes(cloud, command):
    result = invoke(command)
    assert result.exit_code == 1
    assert '--yes' in (result.stdout + result.stderr)
    assert not cloud.requests


@pytest.mark.parametrize('answer,expected', [('n\n', 1), ('y\n', 0)])
def test_terminal_kill_confirmation(cloud, monkeypatch, answer, expected):
    monkeypatch.setattr(sandbox.sys.stdin, 'isatty', lambda: True)
    # CliRunner replaces stdin, so patch its input wrapper too.
    import click.testing
    monkeypatch.setattr(click.testing._NamedTextIOWrapper, 'isatty', lambda self: True)
    result = invoke_with_input(['kill', 'box'], answer)
    assert result.exit_code == expected
    assert any(r.method == 'DELETE' for r in cloud.requests) == (expected == 0)


def invoke_with_input(args, text):
    return CliRunner(mix_stderr=False).invoke(main, ['sandbox', *args], input=text)


def test_json_never_prompts(cloud, monkeypatch):
    monkeypatch.setattr(sandbox.sys.stdin, 'isatty', lambda: True)
    result = invoke(['kill', 'box', '--json'])
    assert result.exit_code == 1
    assert '--yes' in (result.stdout + result.stderr)
    assert not cloud.requests


@pytest.mark.parametrize('exit_code', [0, 7, 127])
@pytest.mark.parametrize('as_json', [False, True])
def test_exec_status_and_fresh_token(cloud, exit_code, as_json):
    cloud.exit_code = exit_code
    result = invoke(['exec', 'box', *(['--json'] if as_json else []), '--', 'printf', '%s', 'hello world'])
    assert result.exit_code == exit_code, (result.stdout + result.stderr)
    assert 'hello' in result.stdout
    if as_json:
        assert json.loads(result.stdout)['exit_code'] == exit_code
    else:
        assert 'diagnostic' in (result.stdout + result.stderr)
    request = next(r for r in cloud.requests if r.url.path == '/executions')
    assert json.loads(request.content)['parameters']['command'] == "printf %s 'hello world'"
    assert all(t not in (result.stdout + result.stderr) for t in (ACCESS, TRAFFIC, COMPUTE))
    assert cloud.requests[0].url.path.endswith('/connect')


def test_exec_polls_an_accepted_execution(cloud):
    cloud.execution_pending = True
    result = invoke(['exec', 'box', '--', 'true'])
    assert_ok(result)
    assert cloud.requests[-1].url.path == '/executions/exec'


@pytest.mark.parametrize('mode', ['success', 'nonzero', 'network', 'interrupt', 'deletion', 'reuse'])
def test_run_always_kills(cloud, mode):
    if mode == 'nonzero':
        cloud.exit_code = 9
    if mode == 'network':
        cloud.exec_error = httpx.ConnectError('may contain a secret')
    if mode == 'interrupt':
        cloud.exec_error = KeyboardInterrupt()
    if mode == 'deletion':
        cloud.states = ['deleted']
    if mode == 'reuse':
        name = 'gmi-run-' + hashlib.sha256(b'ubuntu:24.04\0gmi.sandbox.small').hexdigest()[:16]
        cloud.templates = [{'id': 'template', 'name': name, 'latest_build_status': 'ready', 'latest_build_id': 'build'}]
    result = invoke(['run', '--image', 'ubuntu:24.04', '--yes', '--', 'echo', 'hello'])
    assert result.exit_code == (0 if mode in ('success', 'reuse') else 9 if mode == 'nonzero' else 1), (result.stdout + result.stderr)
    assert cloud.requests[-1].method == 'DELETE'
    assert cloud.requests[-1].url.path.endswith('/sandboxes/box')
    assert sum(r.method == 'DELETE' for r in cloud.requests) == 1
    assert all(t not in (result.stdout + result.stderr) for t in (ACCESS, TRAFFIC, COMPUTE))
    if mode == 'reuse':
        assert not any(r.method == 'POST' and r.url.path.endswith('/templates') for r in cloud.requests)


def test_files_use_fresh_data_token_and_multipart(cloud, tmp_path):
    local = tmp_path / 'input.bin'
    local.write_bytes(b'file-content\x00')
    assert_ok(invoke(['put', 'box', str(local), '/home/user/data.bin', '--username', 'user', '--json']))
    output = tmp_path / 'output.bin'
    result = invoke(['get-file', 'box', '/home/user/data.bin', '--out', str(output), '--username', 'user', '--json'])
    assert_ok(result)
    assert output.read_bytes() == b'file-content\x00'
    assert json.loads(result.stdout)['bytes'] == 13
    assert sum(r.url.path.endswith('/connect') for r in cloud.requests) == 2


@pytest.mark.parametrize('flag,env,config,expected', [
    ('flag-idc', 'env-idc', 'config-idc', 'flag-idc'),
    (None, 'env-idc', 'config-idc', 'env-idc'),
    (None, None, 'config-idc', 'config-idc'),
    (None, None, None, None),
])
def test_idc_precedence_for_requests(cloud, monkeypatch, flag, env, config, expected):
    if env:
        monkeypatch.setenv('GMI_SANDBOX_IDC_NAME', env)
    if config:
        result = CliRunner(mix_stderr=False).invoke(main, ['config', 'set', 'sandbox_idc', config])
        assert_ok(result)
    extra = ['--idc-name', flag] if flag else []
    assert_ok(invoke(['templates', 'create', '--name', 'demo', '--yes', *extra]))
    assert_ok(invoke(['create', 'template', '--yes', *extra]))
    assert_ok(invoke(['list', *extra]))
    assert_ok(invoke(['products', *extra]))
    for request in cloud.requests:
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body.get('idc_name') == expected
            assert ('idc_name' in body) == (expected is not None)
        elif not request.url.path.endswith('/box'):
            assert request.url.params.get('idc_name') == expected
            assert ('idc_name' in request.url.params) == (expected is not None)


@pytest.mark.parametrize('priced', [False, True])
def test_product_table_only_shows_available_prices(cloud, priced):
    if priced:
        cloud.products[0]['price'] = '0.0001'
        cloud.products[0]['unit'] = 'USD/second'
    result = invoke(['products'])
    assert_ok(result)
    assert ('price' in (result.stdout + result.stderr)) == priced
    assert 'gmi.sandbox.small\tactive\t2\t4096' in (result.stdout + result.stderr)
    result = invoke(['templates', 'create', '--name', 'demo', '--yes'])
    assert_ok(result)
    assert ('0.0001' in (result.stdout + result.stderr)) == priced
    assert ('billing estimate' in (result.stdout + result.stderr)) == priced
    assert ('credits where applicable' in (result.stdout + result.stderr)) != priced


def test_remaining_control_commands(cloud):
    for command in (['templates', 'list', '--json'], ['templates', 'get', 'template', '--json'],
                    ['templates', 'delete', 'template', '--yes', '--json'],
                    ['get', 'box', '--json'], ['list', '--state', 'running', '--json'],
                    ['kill', 'box', '--yes', '--json'], ['timeout', 'box', '900', '--yes', '--json']):
        result = invoke(command)
        assert_ok(result)
        json.loads(result.stdout)
        assert all(t not in (result.stdout + result.stderr) for t in (ACCESS, TRAFFIC, COMPUTE))
    result = invoke(['templates', 'logs', 'template', '--json'])
    assert_ok(result)
    assert [r['message'] for r in json.loads(result.stdout)] == ['line 0', 'line 1']
    assert any(r.url.params.get('state') == 'running' for r in cloud.requests)


def test_missing_compute_key_hint(cloud, monkeypatch):
    monkeypatch.delenv('GMI_COMPUTE_API_KEY')
    result = invoke(['list'])
    assert result.exit_code == 1
    assert 'GMI_COMPUTE_API_KEY or GMI_SANDBOX_API_KEY' in (result.stdout + result.stderr)
    assert 'compute scope' in (result.stdout + result.stderr)
    assert not cloud.requests


@pytest.mark.parametrize('status', [401, 403])
def test_wrong_scope_hint_and_no_error_body_leak(cloud, monkeypatch, status):
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(
        lambda request: httpx.Response(status, json={'message': COMPUTE, 'sandbox_access_token': ACCESS})))
    result = invoke(['list'])
    assert result.exit_code == 1
    assert 'compute scope' in (result.stdout + result.stderr)
    assert COMPUTE not in (result.stdout + result.stderr)
    assert ACCESS not in (result.stdout + result.stderr)


@pytest.mark.parametrize('kind', ['template', 'sandbox', 'execution'])
def test_bounded_waits(cloud, monkeypatch, kind):
    tick = iter(range(100))
    monkeypatch.setattr(sandbox.time, 'monotonic', lambda: next(tick))
    client = sandbox.SandboxClient()
    try:
        with pytest.raises(Exception, match='Timed out'):
            if kind == 'template':
                cloud.build_states = ['building']
                client.wait_template('template', timeout=1)
            elif kind == 'sandbox':
                cloud.states = ['provisioning']
                client.wait_sandbox('box', timeout=1)
            else:
                cloud.execution_pending = True
                cloud.execution = lambda: httpx.Response(200, json={'execution_id': 'exec', 'status': 'running'})
                client.execute('box', ['sleep', '100'], timeout=1)
    finally:
        client.close()


def test_scrubs_tokens_embedded_in_exec_output(cloud):
    cloud.execution = lambda: httpx.Response(200, json={'status': 'succeeded', 'exit_code': 0,
                                                       'stdout': ACCESS + COMPUTE, 'stderr': ACCESS})
    result = invoke(['exec', 'box', '--', 'env'])
    assert_ok(result)
    assert ACCESS not in result.stdout + result.stderr
    assert COMPUTE not in result.stdout + result.stderr
    assert '[redacted]' in result.stdout


def test_run_reports_cleanup_failure(cloud, monkeypatch):
    handler = cloud.handler
    def fail_delete(request):
        if request.method == 'DELETE':
            return httpx.Response(500, json={'message': ACCESS})
        return handler(request)
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(fail_delete))
    result = invoke(['run', '--image', 'ubuntu:24.04', '--yes', '--', 'true'])
    assert result.exit_code == 1
    assert 'Cleanup failed for sandbox box' in result.stderr
    assert 'gmi sandbox kill box --yes' in result.stderr
    assert ACCESS not in result.stdout + result.stderr


@pytest.mark.parametrize('variable', ['GMI_COMPUTE_API_KEY', 'GMI_SANDBOX_API_KEY'])
def test_compute_key_aliases(cloud, monkeypatch, variable):
    monkeypatch.delenv('GMI_COMPUTE_API_KEY')
    monkeypatch.setenv(variable, COMPUTE)
    monkeypatch.setenv('GMI_API_KEY', 'inference-key-must-not-be-used')
    assert_ok(invoke(['list']))


def test_create_rejects_invalid_env_before_http(cloud):
    result = invoke(['create', 'template', '--env', 'missing-value', '--yes'])
    assert result.exit_code == 1
    assert '--env requires K=V' in result.stderr
    assert not cloud.requests


def test_default_idc_creation_survives_catalog_requiring_idc(cloud, monkeypatch):
    handler = cloud.handler
    def catalog_requires_idc(request):
        if request.url.path.endswith('/products'):
            assert 'idc_name' not in request.url.params
            return httpx.Response(400, json={'message': 'idc_name is required'})
        return handler(request)
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(catalog_requires_idc))
    result = invoke(['create', 'template', '--yes', '--wait'])
    assert_ok(result)
    assert 'catalog prices are unavailable' in result.stderr


TEMPLATE = {
    'name': 'demo', 'product': 'gmi.sandbox.small', 'idc_name': 'us-central-iowa16',
    'resources': {'cpu_count': 2, 'memory_mb': 4096}, 'created_at': '2026-10-22T12:00:00Z',
}
BOX = {
    'product': 'gmi.sandbox.small', 'idc_name': 'us-central-iowa16',
    'started_at': '2026-10-22T12:00:00Z', 'end_at': '2026-10-22T12:05:00Z',
}
TEMPLATE_LIST_OUTPUT = (
    'name\tstatus\tproduct\tidc\tid\n'
    'demo\tready\tgmi.sandbox.small\tus-central-iowa16\ttemplate\n'
)
TEMPLATE_GET_OUTPUT = (
    'name: demo\nid: template\nstatus: ready\nproduct: gmi.sandbox.small\n'
    'vcpu: 2\nmemory_mb: 4096\nidc: us-central-iowa16\ncreated: 2026-10-22T12:00:00Z\n'
)
TEMPLATE_CREATE_OUTPUT = 'created: demo (template), build started\n'
TEMPLATE_WAIT_OUTPUT = (
    'building 0s\nbuilding 5s\nbuilding 10s\n'
    'ready: demo (template) product gmi.sandbox.small in 17s\n'
)
SANDBOX_LIST_OUTPUT = (
    'id\tstate\tproduct\tidc\tends\n'
    'box\trunning\tgmi.sandbox.small\tus-central-iowa16\t2026-10-22T12:05:00Z\n'
)
SANDBOX_GET_OUTPUT = (
    'id: box\nstate: running\nproduct: gmi.sandbox.small\nidc: us-central-iowa16\n'
    'started: 2026-10-22T12:00:00Z\nends: 2026-10-22T12:05:00Z\n'
)


@pytest.fixture
def display_cloud(cloud):
    cloud.template_detail = dict(TEMPLATE)
    cloud.templates = [{'id': 'template', 'latest_build_status': 'ready', **TEMPLATE,
                        'sandbox_access_token': ACCESS, 'traffic_access_token': TRAFFIC}]
    cloud.sandbox_detail = dict(BOX)
    cloud.sandboxes = [{'id': 'box', 'state': 'running', **BOX,
                        'sandbox_access_token': ACCESS, 'traffic_access_token': TRAFFIC}]
    return cloud


@pytest.mark.parametrize('command,expected', [
    (['templates', 'list'], TEMPLATE_LIST_OUTPUT),
    (['templates', 'get', 'template'], TEMPLATE_GET_OUTPUT),
    (['templates', 'create', '--name', 'demo', '--yes'], TEMPLATE_CREATE_OUTPUT),
    (['list'], SANDBOX_LIST_OUTPUT),
    (['get', 'box'], SANDBOX_GET_OUTPUT),
])
def test_exact_human_output(display_cloud, command, expected):
    result = invoke(command)
    assert_ok(result)
    assert result.stdout == expected
    if 'get' in command:
        assert len(result.stdout.splitlines()) <= 10
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))
    assert 'sandbox_access_token' not in result.stdout
    assert 'traffic_access_token' not in result.stdout


@pytest.mark.parametrize('as_json', [False, True])
def test_template_wait_output_and_poll_interval(display_cloud, monkeypatch, as_json):
    cloud = display_cloud
    cloud.build_states = ['building', 'building', 'building', 'ready']
    elapsed = [0]
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds
    handler = cloud.handler
    def delayed_ready(request):
        response = handler(request)
        if request.url.path.endswith('/templates/template') and response.json()['data']['latest_build_status'] == 'ready':
            elapsed[0] += 2
        return response
    monkeypatch.setattr(sandbox.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(sandbox.time, 'sleep', sleep)
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(delayed_ready))
    result = invoke(['templates', 'create', '--name', 'demo', '--wait', '--yes', *(['--json'] if as_json else [])])
    assert_ok(result)
    assert sleeps == [5, 5, 5]
    expected = (json.dumps({'id': 'template', 'latest_build_id': 'build', 'latest_build_status': 'ready', **TEMPLATE}) + '\n'
                if as_json else TEMPLATE_WAIT_OUTPUT)
    assert result.stdout == expected
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))


@pytest.mark.parametrize('command,expected', [
    (['templates', 'list'], 'No templates.\n'), (['list'], 'No sandboxes.\n'),
])
def test_empty_human_lists(cloud, command, expected):
    cloud.sandboxes = []
    result = invoke(command)
    assert_ok(result)
    assert result.stdout == expected
    result = invoke([*command, '--json'])
    assert_ok(result)
    assert result.stdout == '[]\n'


def test_template_list_preserves_api_order_and_full_ids(display_cloud):
    display_cloud.templates[0]['id'] = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
    display_cloud.templates.append({**display_cloud.templates[0], 'name': 'alpha',
                                    'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'latest_build_status': 'building'})
    result = invoke(['templates', 'list'])
    assert_ok(result)
    assert result.stdout == (
        'name\tstatus\tproduct\tidc\tid\n'
        'demo\tready\tgmi.sandbox.small\tus-central-iowa16\tffffffff-ffff-ffff-ffff-ffffffffffff\n'
        'alpha\tbuilding\tgmi.sandbox.small\tus-central-iowa16\taaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n'
    )


@pytest.mark.parametrize('state', ['deleting', 'deleted'])
def test_deleted_get_block(display_cloud, state):
    display_cloud.states = [state]
    result = invoke(['get', 'box'])
    assert result.exit_code == 1
    assert result.stdout == SANDBOX_GET_OUTPUT.replace('state: running', f'state: {state}') + (
        'deletion code: Sandbox.BillingNoPermission\n'
        'deletion message: Deleted by platform: billing is not permitted\n'
        'initiator: billing\n'
    )
    assert len(result.stdout.splitlines()) <= 10
    assert 'not a gmi error' in result.stderr
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))
    # JSON keeps the pre-existing deletion error and empty stdout.
    result = invoke(['get', 'box', '--json'])
    assert result.exit_code == 1
    assert result.stdout == ''


@pytest.mark.parametrize('state', ['deleting', 'deleted'])
@pytest.mark.parametrize('as_json', [False, True])
def test_user_deleted_get_is_plain_state(display_cloud, state, as_json):
    display_cloud.states = [state]
    deletion = {'code': 'Sandbox.UserDeleted', 'initiator': 'user',
                'message': 'Deleted by user request'}
    display_cloud.sandbox_detail['deletion'] = deletion
    result = invoke(['get', 'box', *(['--json'] if as_json else [])])
    assert_ok(result)
    assert result.stderr == ''
    if as_json:
        value = json.loads(result.stdout)
        assert value['state'] == state
        assert value['deletion'] == deletion
    else:
        assert f'state: {state}\n' in result.stdout
        assert 'deletion message: Deleted by user request\n' in result.stdout
        assert 'initiator: user\n' in result.stdout
    assert 'platform deletion' not in result.stdout
    assert all(secret not in result.stdout for secret in (COMPUTE, ACCESS, TRAFFIC))


@pytest.mark.parametrize('command', [
    ['create', 'template', '--wait', '--yes'],
    ['run', '--image', 'ubuntu:24.04', '--yes', '--', 'true'],
])
def test_user_deletion_stops_wait_without_platform_wording(cloud, command):
    cloud.states = ['deleted']
    cloud.sandbox_detail['deletion'] = {
        'code': 'Sandbox.UserDeleted', 'initiator': 'user', 'message': 'Deleted by user request'}
    result = invoke(command)
    assert result.exit_code == 1
    assert 'Deleted by user request' in result.stderr
    assert 'platform deletion' not in result.stderr
    assert len([r for r in cloud.requests if r.method == 'GET'
                and r.url.path.endswith('/sandboxes/box')]) == 1


@pytest.mark.parametrize('command,payload', [
    (['templates', 'list'], [{'id': 'template', 'latest_build_status': 'ready', **TEMPLATE,
                             'sandbox_access_token': '[redacted]', 'traffic_access_token': '[redacted]'}]),
    (['templates', 'get', 'template'], {'id': 'template', 'latest_build_id': 'build', 'latest_build_status': 'ready', **TEMPLATE}),
    (['templates', 'create', '--name', 'demo', '--yes'], {'id': 'template', 'build_id': 'build', 'status': 'waiting'}),
    (['templates', 'create', '--name', 'demo', '--wait', '--yes'],
     {'id': 'template', 'latest_build_id': 'build', 'latest_build_status': 'ready', **TEMPLATE}),
    (['list'], [{'id': 'box', 'state': 'running', **BOX,
                'sandbox_access_token': '[redacted]', 'traffic_access_token': '[redacted]'}]),
    (['get', 'box'], {'id': 'box', 'state': 'running', 'end_at': BOX['end_at'],
                     'sandbox_access_token': '[redacted]', 'traffic_access_token': '[redacted]',
                     'metadata': {'echo': '[redacted]', 'traffic_access_token': '[redacted]'},
                     'product': BOX['product'], 'idc_name': BOX['idc_name'], 'started_at': BOX['started_at']}),
])
def test_json_bytes_unchanged(display_cloud, command, payload):
    result = invoke([*command, '--json'])
    assert_ok(result)
    assert result.stdout.encode() == (json.dumps(payload, ensure_ascii=False) + '\n').encode()
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))


def test_human_fields_redact_embedded_tokens_and_keep_single_lines(display_cloud):
    display_cloud.template_detail.update({'name': 'demo\n' + ACCESS, 'traffic_access_token': ACCESS})
    display_cloud.sandbox_detail.update({'product': 'sku\n' + TRAFFIC})
    for command in (['templates', 'get', 'template'], ['get', 'box']):
        result = invoke(command)
        assert_ok(result)
        assert len(result.stdout.splitlines()) <= 10
        assert '[redacted]' in result.stdout
        assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))


SANDBOX_CREATE_OUTPUT = 'created sandbox box ends 2026-10-22T12:05:00Z\n'
TEMPLATE_DELETE_OUTPUT = 'deleting template template (accepted)\n'
SANDBOX_KILL_OUTPUT = 'killing sandbox box (accepted)\n'
SANDBOX_TIMEOUT_OUTPUT = 'timeout set: box ends 2026-10-22T12:15:00Z\n'
TEMPLATE_LOGS_OUTPUT = 'line 0\nline 1\n'
UPLOAD_OUTPUT = 'uploaded input.bin to /home/user/data.bin\n'
DOWNLOAD_OUTPUT = 'downloaded /home/user/data.bin to output.bin (13 bytes)\n'


@pytest.mark.parametrize('as_json', [False, True])
@pytest.mark.parametrize('command,human,payload', [
    (['templates', 'delete', 'template', '--yes'], TEMPLATE_DELETE_OUTPUT,
     {'id': 'template', 'deleted': True}),
    (['templates', 'logs', 'template'], TEMPLATE_LOGS_OUTPUT,
     [{'message': 'line 0'}, {'message': 'line 1'}]),
    (['create', 'template', '--yes'], SANDBOX_CREATE_OUTPUT,
     {'id': 'box', 'sandbox_key': 'old-host', 'domain': 'old.test',
      'sandbox_access_token': '[redacted]', 'traffic_access_token': '[redacted]',
      'state': 'running', 'end_at': '2026-10-22T12:05:00Z',
      'metadata': {'echo': '[redacted]', 'traffic_access_token': '[redacted]'}}),
    (['kill', 'box', '--yes'], SANDBOX_KILL_OUTPUT, {'id': 'box', 'state': 'deleting'}),
    (['timeout', 'box', '900', '--yes'], SANDBOX_TIMEOUT_OUTPUT,
     {'id': 'box', 'new_end_at': '2026-10-22T12:15:00Z'}),
    (['put', 'box', 'input.bin', '/home/user/data.bin', '--username', 'user'], UPLOAD_OUTPUT,
     {'path': '/home/user/data.bin', 'type': 'file'}),
    (['get-file', 'box', '/home/user/data.bin', '--out', 'output.bin', '--username', 'user'],
     DOWNLOAD_OUTPUT, {'path': 'output.bin', 'bytes': 13}),
])
def test_polished_output_and_unchanged_json_bytes(cloud, tmp_path, monkeypatch, command, human, payload, as_json):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'input.bin').write_bytes(b'file-content\x00')
    result = invoke([*command, *(['--json'] if as_json else [])])
    assert_ok(result)
    expected = json.dumps(payload, ensure_ascii=False) + '\n' if as_json else human
    assert result.stdout.encode('utf-8') == expected.encode('utf-8')
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))
    if command[0] == 'get-file':
        assert (tmp_path / 'output.bin').read_bytes() == b'file-content\x00'


@pytest.mark.parametrize('as_json', [False, True])
@pytest.mark.parametrize('command,human', [
    (['templates', 'delete', 'template', '--yes'], TEMPLATE_DELETE_OUTPUT),
    (['kill', 'box', '--yes'], SANDBOX_KILL_OUTPUT),
])
def test_empty_202_deletion_output(cloud, monkeypatch, command, human, as_json):
    requests = []
    def accepted(request):
        assert request.method == 'DELETE'
        requests.append(request)
        return httpx.Response(202)
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(accepted))
    result = invoke([*command, *(['--json'] if as_json else [])])
    assert_ok(result)
    assert result.stdout.encode() == (b'{}\n' if as_json else human.encode())
    assert len(requests) == 1  # No lookup to invent a name or poll deletion.


@pytest.mark.parametrize('as_json', [False, True])
def test_upload_schema_array_output(cloud, monkeypatch, tmp_path, as_json):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'input.bin').write_bytes(b'file-content\x00')
    handler = cloud.handler
    entries = [{'path': '/home/user/data.bin', 'name': 'data.bin', 'type': 'file'}]
    def array_upload(request):
        response = handler(request)
        if request.url.path == '/files':
            return httpx.Response(200, json=entries)
        return response
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(array_upload))
    result = invoke(['put', 'box', 'input.bin', '/home/user/data.bin', '--username', 'user',
                     *(['--json'] if as_json else [])])
    assert_ok(result)
    expected = json.dumps(entries) + '\n' if as_json else UPLOAD_OUTPUT
    assert result.stdout.encode() == expected.encode()


@pytest.mark.parametrize('as_json', [False, True])
def test_empty_build_logs_output(cloud, monkeypatch, as_json):
    handler = cloud.handler
    def no_logs(request):
        if request.url.path.endswith('/logs'):
            return httpx.Response(200, json={'data': {'entries': [], 'has_more': False, 'next_offset': 0}})
        return handler(request)
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(no_logs))
    result = invoke(['templates', 'logs', 'template', *(['--json'] if as_json else [])])
    assert_ok(result)
    assert result.stdout.encode() == (b'[]\n' if as_json else b'No build logs.\n')


def test_timeout_uses_authoritative_response_expiry(cloud, monkeypatch):
    def timeout(request):
        return httpx.Response(200, json={'data': {
            'id': 'box', 'old_end_at': '2026-10-22T12:05:00Z', 'new_end_at': '2026-10-23T01:02:03.123Z'}})
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(timeout))
    result = invoke(['timeout', 'box', '900', '--yes'])
    assert_ok(result)
    assert result.stdout == 'timeout set: box ends 2026-10-23T01:02:03.123Z\n'


def test_creation_does_not_invent_missing_expiry(cloud):
    cloud.sandbox_detail['end_at'] = None
    result = invoke(['create', 'template', '--yes'])
    assert_ok(result)
    assert result.stdout == 'created sandbox box ends -\n'


@pytest.mark.parametrize('command', [
    ['templates', 'delete', 'template', '--yes'], ['kill', 'box', '--yes'],
    ['timeout', 'box', '900', '--yes'], ['templates', 'logs', 'template'],
])
def test_polished_response_fields_are_single_lines_and_redacted(cloud, monkeypatch, command):
    handler = cloud.handler
    def private_fields(request):
        response = handler(request)
        if request.method == 'DELETE' or request.url.path.endswith('/timeout'):
            value = response.json()
            value['data']['id'] = 'box\n' + COMPUTE
            return httpx.Response(response.status_code, json=value)
        if request.url.path.endswith('/logs'):
            return httpx.Response(200, json={'data': {
                'entries': [{'offset': 0, 'level': 'info', 'message': 'hello\n' + COMPUTE}],
                'has_more': False, 'next_offset': 1}})
        return response
    monkeypatch.setattr(sandbox, 'HTTPTransport', lambda: httpx.MockTransport(private_fields))
    result = invoke(command)
    assert_ok(result)
    assert len(result.stdout.splitlines()) == 1
    assert '[redacted]' in result.stdout
    assert all(secret not in result.stdout + result.stderr for secret in (COMPUTE, ACCESS, TRAFFIC))


@pytest.mark.parametrize('filename', ['README.md', 'docs/AGENTBOX.md'])
def test_polished_documentation_copies_tested_output(filename):
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / filename).read_text()
    for output in (SANDBOX_CREATE_OUTPUT, TEMPLATE_DELETE_OUTPUT, SANDBOX_KILL_OUTPUT,
                   SANDBOX_TIMEOUT_OUTPUT, TEMPLATE_LOGS_OUTPUT, UPLOAD_OUTPUT, DOWNLOAD_OUTPUT):
        assert output in text
    assert '`No build logs.`' in text

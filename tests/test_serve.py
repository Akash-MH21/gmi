"""Offline HTTP tests using a local fake OpenAI-compatible upstream."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import httpx
import pytest
from click.testing import CliRunner

from gmi import serve
from gmi.cli import main
from gmi.config import BUILTIN_DEFAULT_MODEL

MAAS_KEY = 'fake-maas-secret-12345'
LOCAL_KEY = 'fake-local-secret-67890'
SERVICE_TOKEN = 'fake-service-secret-24680'


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.fixture
def upstream(monkeypatch):
    state = {'requests': [], 'status': 200, 'body': {'choices': [{'message': {'content': 'hello'}}],
                                                   'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}}
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append({'path': self.path, 'headers': dict(self.headers), 'body': payload})
            body = state['body']
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    with running(ThreadingHTTPServer(('127.0.0.1', 0), Upstream)) as base:
        monkeypatch.setenv('GMI_MAAS_BASE_URL', base)
        monkeypatch.setenv('GMI_MAAS_API_KEY', MAAS_KEY)
        monkeypatch.setenv('GMI_API_KEY', LOCAL_KEY)
        monkeypatch.delenv('GMI_MODELS', raising=False)
        monkeypatch.delenv('GMI_SERVE_TOKEN', raising=False)
        state['base'] = base
        yield state


@pytest.fixture
def service(upstream):
    with running(serve.make_server('127.0.0.1', 0)) as base:
        with httpx.Client(base_url=base, timeout=3, trust_env=False) as client:
            yield client


def test_health_and_chat(service, upstream, capsys):
    response = service.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 200
    assert response.json() == {'model': BUILTIN_DEFAULT_MODEL, 'reply': 'hello',
                               'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}
    request = upstream['requests'][0]
    assert request['path'] == '/v1/chat/completions'
    assert request['headers']['Authorization'] == 'Bearer ' + MAAS_KEY
    assert request['headers']['User-Agent'].startswith('gmi-cli/')
    assert request['body'] == {'model': BUILTIN_DEFAULT_MODEL, 'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False}
    assert not capsys.readouterr().err


@pytest.mark.parametrize('models,expected', [
    ('provider/a,provider/b', 'provider/a'), ('provider/a provider/b', 'provider/a'),
    ('["provider/a", "provider/b"]', 'provider/a'), ('[]', BUILTIN_DEFAULT_MODEL),
    ('', BUILTIN_DEFAULT_MODEL),
])
def test_model_defaults_and_request_override(service, upstream, monkeypatch, models, expected):
    monkeypatch.setenv('GMI_MODELS', models)
    assert service.post('/chat', json={'message': 'hello'}).json()['model'] == expected
    assert service.post('/chat', json={'message': 'hello', 'model': 'any/provider-model'}).json()['model'] == 'any/provider-model'
    assert upstream['requests'][-1]['body']['model'] == 'any/provider-model'


def test_local_key_fallback_and_v1_base(service, upstream, monkeypatch):
    monkeypatch.delenv('GMI_MAAS_API_KEY')
    monkeypatch.setenv('GMI_MAAS_BASE_URL', upstream['base'] + '/v1/')
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 200
    request = upstream['requests'][0]
    assert request['path'] == '/v1/chat/completions'
    assert request['headers']['Authorization'] == 'Bearer ' + LOCAL_KEY


def test_missing_key(service, upstream, monkeypatch):
    monkeypatch.delenv('GMI_MAAS_API_KEY')
    monkeypatch.delenv('GMI_API_KEY')
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 503
    assert 'GMI_MAAS_API_KEY' in response.json()['error']
    assert not upstream['requests']


@pytest.mark.parametrize('body', [b'{broken', b'\xff', b'[]', b'null', b'{}', b'{"message":42}',
                                  b'{"message":" "}', b'{"message":"ok","model":42}', b'{"message":"ok","model":""}'])
def test_bad_request(service, upstream, body):
    response = service.post('/chat', content=body)
    assert response.status_code == 400
    assert not upstream['requests']


def test_size_limit(service, upstream):
    response = service.post('/chat', content=b'x' * (64 * 1024 + 1))
    assert response.status_code == 413
    assert '64 KB' in response.json()['error']
    assert not upstream['requests']
    payload = b'{"message":"' + b'x' * (64 * 1024 - 14) + b'"}'
    assert len(payload) == 64 * 1024
    assert service.post('/chat', content=payload).status_code == 200


@pytest.mark.parametrize('status', [401, 429, 500])
def test_upstream_error_does_not_echo_body(service, upstream, status, capsys):
    upstream['status'] = status
    upstream['body'] = {'error': MAAS_KEY + LOCAL_KEY + SERVICE_TOKEN}
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 502
    assert f'HTTP {status}' in response.json()['error']
    output = response.text + str(capsys.readouterr())
    assert all(key not in output for key in (MAAS_KEY, LOCAL_KEY, SERVICE_TOKEN))


@pytest.mark.parametrize('body', [b'not json', {}, {'choices': []}, {'choices': [{'message': {'content': None}}]},
                                  {'choices': [{'message': {'content': 'ok'}}], 'usage': 'bad'}])
def test_invalid_upstream_response(service, upstream, body):
    upstream['body'] = body
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 502
    assert response.json() == {'error': 'Upstream returned an invalid chat response.'}


@pytest.mark.parametrize('error', [httpx.ReadTimeout, httpx.ConnectError])
def test_upstream_timeout_and_network_errors(service, monkeypatch, error):
    requests = []
    def fail(request):
        requests.append(request)
        assert request.extensions['timeout'] == {'connect': 30, 'read': 30, 'write': 30, 'pool': 30}
        raise error(MAAS_KEY)
    monkeypatch.setattr(serve, 'HTTPTransport', lambda: httpx.MockTransport(fail))
    response = service.post('/chat', json={'message': 'hi'})
    assert response.status_code == 502
    assert '30 seconds' in response.text if error is httpx.ReadTimeout else 'connection failed' in response.text
    assert MAAS_KEY not in response.text
    assert len(requests) == 1


def test_service_token_and_health_exception(service, upstream, monkeypatch, capsys):
    monkeypatch.setenv('GMI_SERVE_TOKEN', SERVICE_TOKEN)
    assert service.get('/health').json() == {'status': 'ok'}
    for method, path in [('GET', '/private'), ('POST', '/chat')]:
        for auth in (None, 'Bearer wrong'):
            response = service.request(method, path, json={'message': 'hi'}, headers={'Authorization': auth} if auth else {})
            assert response.status_code == 401
    assert not upstream['requests']
    headers = {'Authorization': 'Bearer ' + SERVICE_TOKEN}
    response = service.post('/chat', json={'message': 'hi'}, headers=headers)
    assert response.status_code == 200
    assert upstream['requests'][0]['headers']['Authorization'] == 'Bearer ' + MAAS_KEY
    assert service.get('/private', headers=headers).status_code == 404
    captured = capsys.readouterr()
    assert SERVICE_TOKEN not in response.text + captured.out + captured.err


def test_success_response_never_contains_credentials(service, upstream, monkeypatch, capsys):
    monkeypatch.setenv('GMI_SERVE_TOKEN', SERVICE_TOKEN)
    upstream['body'] = {'choices': [{'message': {'content': 'echo: ' + MAAS_KEY + LOCAL_KEY + SERVICE_TOKEN}}],
                        'usage': {'unexpected': MAAS_KEY}}
    response = service.post('/chat', json={'message': 'hi'}, headers={'Authorization': 'Bearer ' + SERVICE_TOKEN})
    assert response.status_code == 200
    output = response.text + str(capsys.readouterr())
    assert all(key not in output for key in (MAAS_KEY, LOCAL_KEY, SERVICE_TOKEN))
    assert '[redacted]' in response.text


def test_port_env_cli_and_default_bind(monkeypatch):
    calls = []
    class FakeServer:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_forever(self): raise KeyboardInterrupt()
    def make(host='0.0.0.0', port=8080):
        calls.append((host, port))
        return FakeServer()
    monkeypatch.setattr(serve, 'make_server', make)
    monkeypatch.setenv('PORT', '9090')
    result = CliRunner().invoke(main, ['serve', '--json'])
    assert result.exit_code == 0
    assert calls == [('0.0.0.0', 9090)]
    assert json.loads(result.output) == {'host': '0.0.0.0', 'port': 9090}


def test_other_methods_require_auth(service, upstream, monkeypatch):
    monkeypatch.setenv('GMI_SERVE_TOKEN', SERVICE_TOKEN)
    for method in ('PUT', 'DELETE', 'PATCH', 'OPTIONS'):
        response = service.request(method, '/chat')
        assert response.status_code == 401
        response = service.request(method, '/chat', headers={'Authorization': 'Bearer ' + SERVICE_TOKEN})
        assert response.status_code == 501
    assert not upstream['requests']

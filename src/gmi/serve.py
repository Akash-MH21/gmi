"""Small AgentBox HTTP service with no credential logging."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re

import click
import httpx

from . import __version__
from .config import BUILTIN_DEFAULT_MODEL

MAX_REQUEST_BYTES = 64 * 1024
UPSTREAM_TIMEOUT = 30
HTTPTransport = httpx.HTTPTransport


def default_model():
    value = os.environ.get('GMI_MODELS', '').strip()
    if not value:
        return BUILTIN_DEFAULT_MODEL
    if value.startswith('['):
        try:
            models = json.loads(value)
            if isinstance(models, list) and models and isinstance(models[0], str) and models[0].strip():
                return models[0].strip()
        except ValueError:
            pass
        return BUILTIN_DEFAULT_MODEL
    return re.split(r'[,\s]+', value)[0]


def redact(value):
    """Remove known runtime secrets even if upstream echoes one in a reply."""
    if isinstance(value, str):
        secrets = {os.environ.get(name, '') for name in (
            'GMI_MAAS_API_KEY', 'GMI_API_KEY', 'GMI_SERVE_TOKEN')}
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                value = value.replace(secret, '[redacted]')
        return value
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = 'gmi'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        # Request paths, headers and bodies must never enter service logs.
        pass

    def send_json(self, status, value):
        body = json.dumps(redact(value), ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        token = os.environ.get('GMI_SERVE_TOKEN')
        if not token:
            return True
        provided = self.headers.get('Authorization', '').encode('utf-8')
        return hmac.compare_digest(provided, ('Bearer ' + token).encode('utf-8'))

    def route(self):
        if self.path != '/health' and not self.authorized():
            self.send_json(401, {'error': 'Unauthorized; provide the service bearer token.'})
            return False
        return True

    def send_error(self, code, message=None, explain=None):
        if hasattr(self, 'headers') and self.path != '/health' and not self.authorized():
            self.send_json(401, {'error': 'Unauthorized; provide the service bearer token.'})
        else:
            self.send_json(code, {'error': 'Unsupported or invalid HTTP request.'})

    def do_GET(self):
        if not self.route():
            return
        if self.path == '/health':
            self.send_json(200, {'status': 'ok'})
        else:
            self.send_json(404, {'error': 'Route not found.'})

    def do_POST(self):
        if not self.route():
            return
        if self.path != '/chat':
            self.send_json(404, {'error': 'Route not found.'})
            return
        if self.headers.get('Transfer-Encoding'):
            self.send_json(400, {'error': 'Use Content-Length; chunked requests are unsupported.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            length = -1
        if length < 0:
            self.send_json(400, {'error': 'Provide a valid Content-Length.'})
            return
        if length > MAX_REQUEST_BYTES:
            self.send_json(413, {'error': 'Request exceeds 64 KB.'})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {'error': 'Invalid JSON; provide an object with a message string.'})
            return
        except (TimeoutError, OSError):
            self.send_json(400, {'error': 'Request body timed out.'})
            return
        if not isinstance(payload, dict) or not isinstance(payload.get('message'), str) or not payload['message'].strip():
            self.send_json(400, {'error': 'Provide a non-empty message string.'})
            return
        model = payload.get('model', default_model())
        if not isinstance(model, str) or not model.strip() or len(model) > 512:
            self.send_json(400, {'error': 'Model must be a non-empty string of at most 512 characters.'})
            return
        key = os.environ.get('GMI_MAAS_API_KEY') or os.environ.get('GMI_API_KEY')
        if not key:
            self.send_json(503, {'error': 'Set GMI_MAAS_API_KEY or GMI_API_KEY on the server.'})
            return
        base = os.environ.get('GMI_MAAS_BASE_URL', 'https://api.gmi-serving.com').rstrip('/')
        if not base.endswith('/v1'):
            base += '/v1'
        try:
            with httpx.Client(transport=HTTPTransport(), timeout=UPSTREAM_TIMEOUT,
                              headers={'Authorization': 'Bearer ' + key, 'User-Agent': f'gmi-cli/{__version__}'}) as client:
                response = client.post(base + '/chat/completions', json={
                    'model': model, 'messages': [{'role': 'user', 'content': payload['message']}], 'stream': False})
            if response.status_code >= 400:
                self.send_json(502, {'error': f'Upstream returned HTTP {response.status_code}; check the model and account access.'})
                return
            data = response.json()
            reply = data['choices'][0]['message']['content']
            usage = data.get('usage') or {}
            if not isinstance(reply, str) or not isinstance(usage, dict):
                raise ValueError()
            self.send_json(200, {'model': model, 'reply': reply, 'usage': usage})
        except httpx.TimeoutException:
            self.send_json(502, {'error': 'Upstream timed out after 30 seconds.'})
        except httpx.RequestError:
            self.send_json(502, {'error': 'Upstream connection failed.'})
        except (ValueError, KeyError, TypeError, IndexError):
            self.send_json(502, {'error': 'Upstream returned an invalid chat response.'})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # The standard implementation prints a traceback that may contain secrets.
        pass


def make_server(host='0.0.0.0', port=8080):
    return Server((host, port), Handler)


@click.command('serve')
@click.option('--port', envvar='PORT', type=click.IntRange(min=1, max=65535), default=8080, show_default=True)
@click.option('--json', 'as_json', is_flag=True, help='Print the startup address as JSON.')
def serve_command(port, as_json):
    """Serve /health and /chat for AgentBox or local use."""
    try:
        server = make_server(port=port)
    except OSError:
        raise click.ClickException('Cannot listen; check PORT and whether it is already in use.') from None
    with server:
        if as_json:
            click.echo(json.dumps({'host': '0.0.0.0', 'port': port}))
        else:
            click.echo(f'gmi serve listening on 0.0.0.0:{port}', err=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

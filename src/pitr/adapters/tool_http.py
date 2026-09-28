"""Dedicated loopback capability port; never exposes browser/admin commands."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from pitr.application.tools import ToolService
from pitr.domain.common import canonical, Forbidden, Conflict, BudgetExhausted


class ToolServer:
    def __init__(self, station):
        service = ToolService(station)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    self.connection.settimeout(40)
                    if self.headers.get('Origin') or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                        raise Forbidden('此端口仅接受执行能力调用')
                    size = int(self.headers.get('Content-Length', '0'))
                    if size < 2 or size > 4_000_000:
                        raise ValueError('请求体大小不正确')
                    value = json.loads(self.rfile.read(size))
                    authorization = self.headers.get('Authorization', '')
                    if not authorization.startswith('Bearer '):
                        raise Forbidden('缺少执行凭据')
                    token = authorization[7:]
                    if self.path == '/catalog':
                        with station.store.connect() as db:
                            _, grant = service.authenticate(db, token)
                        result = service.catalog(grant['role'])
                    elif self.path == '/call':
                        result = service.call(token, value)
                    else:
                        raise KeyError('工具路由不存在')
                    status, body = 200, canonical({'ok': True, 'result': result}).encode()
                except Exception as error:
                    status = 403 if isinstance(error, Forbidden) else 409 if isinstance(error, Conflict) else 429 if isinstance(error, BudgetExhausted) else 404 if isinstance(error, KeyError) else 400
                    body = canonical({'ok': False, 'error': type(error).__name__, 'message': str(error)[:4000]}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='research-tools')
        self.thread.start()
        station.tool_url = self.url

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

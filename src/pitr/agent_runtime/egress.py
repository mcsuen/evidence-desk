"""Per-call model-only CONNECT gateway; research HTTP belongs to the tool service.

The child may connect only to this gateway and its tool-service port. The gateway
runs outside Seatbelt, preserves an existing workstation proxy, and grants exact
model/auth hosts rather than public-web access to the agent's shell.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import threading
from urllib.parse import urlsplit
from urllib.request import getproxies


class ModelEgress:
    def __init__(self, provider, env, config, root):
        hosts = ({'api.openai.com', 'chatgpt.com', 'auth.openai.com', 'ab.chatgpt.com'} if provider == 'codex'
                 else {'api.anthropic.com', 'claude.ai', 'console.anthropic.com', 'platform.claude.com'})
        self.allowed = {(host, 443) for host in hosts}
        endpoints = [env.get('OPENAI_BASE_URL' if provider == 'codex' else 'ANTHROPIC_BASE_URL','')]
        if provider == 'codex':
            endpoints += [config.get('openai_base_url',''), config.get('chatgpt_base_url','')]
            endpoints.append(config.get('model_providers',{}).get(config.get('model_provider'),{}).get('base_url',''))
        for endpoint in endpoints:
            parsed = urlsplit(endpoint)
            if parsed.hostname:
                if parsed.scheme != 'https':
                    raise ValueError('受控 Agent 模型连接必须使用 HTTPS；请使用 HTTPS 模型端点')
                self.allowed.add((parsed.hostname.lower(), parsed.port or 443))
        self.upstream = env.get('HTTPS_PROXY') or env.get('https_proxy') or getproxies().get('https')
        if self.upstream and urlsplit(self.upstream).scheme != 'http':
            raise ValueError('Agent 网关仅支持现有 HTTP CONNECT 代理')
        self.env, self.root = env, root
        self.sockets, self.lock = set(), threading.Lock()
        self.closed = threading.Event()
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args):
                pass

            def do_CONNECT(self):
                parsed = urlsplit('//'+self.path)
                try:
                    target = (parsed.hostname.lower(), parsed.port or 443)
                    if parsed.username or parsed.password or parsed.path or target not in gateway.allowed:
                        self.send_error(403, 'Only configured model endpoints are allowed')
                        gateway.record('denied', target)
                        return
                    remote = gateway.connect(target)
                    with gateway.lock:
                        gateway.sockets.update((remote, self.connection))
                    gateway.record('allowed', target)
                    self.send_response(200, 'Connection Established')
                    self.end_headers()
                    self.wfile.flush()
                    try:
                        while not gateway.closed.is_set():
                            readable, _, _ = select.select([remote, self.connection], [], [], 1)
                            for origin in readable:
                                data = origin.recv(65536)
                                if not data:
                                    return
                                (self.connection if origin is remote else remote).sendall(data)
                    finally:
                        with gateway.lock:
                            gateway.sockets.discard(remote)
                            gateway.sockets.discard(self.connection)
                        remote.close()
                except (OSError, ValueError, AttributeError):
                    self.close_connection = True
                    try:
                        self.send_error(502, 'Model connection unavailable')
                    except OSError:
                        pass
                finally:
                    self.close_connection = True

            def do_GET(self):
                self.send_error(403, 'Public research must use the controlled tool service')
            do_POST = do_PUT = do_DELETE = do_GET

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False

    def record(self, status, target):
        # Never persist URLs, query strings, headers or credentials.
        with self.lock, (self.root/'egress.jsonl').open('a') as log:
            log.write(json.dumps({'status':status,'host':target[0],'port':target[1]})+'\n')

    def connect(self, target):
        if not self.upstream:
            return socket.create_connection(target, timeout=20)
        upstream = urlsplit(self.upstream)
        remote = socket.create_connection((upstream.hostname, upstream.port or 80), timeout=20)
        try:
            host = f'{target[0]}:{target[1]}'
            auth = ''
            if upstream.username:
                import base64
                from urllib.parse import unquote
                credentials = unquote(upstream.username)+':'+unquote(upstream.password or '')
                auth = 'Proxy-Authorization: Basic '+base64.b64encode(credentials.encode()).decode()+'\r\n'
            remote.sendall(f'CONNECT {host} HTTP/1.1\r\nHost: {host}\r\n{auth}\r\n'.encode())
            header = bytearray()
            while not header.endswith(b'\r\n\r\n') and len(header) < 8192:
                data = remote.recv(1)
                if not data:
                    break
                header.extend(data)
            if bytes(header).split(b' ', 2)[1:2] != [b'200']:
                raise OSError('Configured proxy refused model connection')
            return remote
        except BaseException:
            remote.close()
            raise

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_port
        for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
            self.env[key] = f'http://127.0.0.1:{port}'
        self.env['NO_PROXY'] = self.env['no_proxy'] = '127.0.0.1,localhost,::1'
        self.env['PITR_MODEL_GATEWAY_PORT'] = str(port)
        return self

    def __exit__(self, *args):
        self.closed.set()
        with self.lock:
            for sock in self.sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                except OSError:
                    pass
            self.sockets.clear()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

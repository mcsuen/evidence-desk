"""Browser sessions for a loopback daemon, bootstrapped by a one-use URL."""
import asyncio
import json
import secrets
import threading
import time
from http.cookies import SimpleCookie


class LocalAuth:
    def __init__(self, port):
        self.port=port;self.lock=threading.Lock();self.tickets={};self.sessions={}
        self.cookie=f'pitr_session_{port}'
        self.hosts={f'127.0.0.1:{port}',f'localhost:{port}'}

    def url(self):
        ticket=secrets.token_urlsafe(32)
        with self.lock:
            self.tickets={k:v for k,v in self.tickets.items() if v>time.monotonic()}
            self.tickets[ticket]=time.monotonic()+120
        return f'http://127.0.0.1:{self.port}/#bootstrap={ticket}'

    def middleware(self, app):
        async def response(send,status,data,extra=()):
            body=json.dumps(data,ensure_ascii=False).encode()
            await send({'type':'http.response.start','status':status,'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store'),*extra]})
            await send({'type':'http.response.body','body':body})
        async def wrapped(scope,receive,send):
            if scope['type'] not in ('http','websocket'):
                return await app(scope,receive,send)
            headers={k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
            host=headers.get('host','');origin=headers.get('origin')
            valid=host in self.hosts and (not origin or origin==f'http://{host}')
            valid=valid and headers.get('sec-fetch-site')!='cross-site'
            if scope.get('client') and scope['client'][0] not in ('127.0.0.1','::1','testclient'):valid=False
            if scope['type']=='websocket':
                # No unauthenticated upgrade path. Existing traces use SSE.
                await send({'type':'websocket.close','code':1008});return
            if not valid:return await response(send,403,{'detail':'仅允许从本机 PITR 页面访问'})
            method=scope['method'];path=scope['path']
            cookie=SimpleCookie()
            try:cookie.load(headers.get('cookie',''))
            except Exception:pass
            sid=cookie[self.cookie].value if self.cookie in cookie else ''
            with self.lock:
                session=self.sessions.get(sid)
                if session and session[1]<time.monotonic():self.sessions.pop(sid,None);session=None
            if path=='/api/local/session' and method=='POST':
                body=b''
                try:
                    async with asyncio.timeout(5):
                        while True:
                            chunk=await receive()
                            if chunk['type']!='http.request':raise ValueError()
                            body+=chunk.get('body',b'')
                            if len(body)>1024:raise ValueError()
                            if not chunk.get('more_body'):break
                    ticket=json.loads(body).get('ticket','')
                    if not isinstance(ticket,str):raise ValueError()
                except (ValueError,TimeoutError):return await response(send,400,{'detail':'启动链接无效'})
                with self.lock:
                    expires=self.tickets.pop(ticket,0)
                    if expires>time.monotonic():
                        sid=secrets.token_urlsafe(32);session=(secrets.token_urlsafe(32),time.monotonic()+86400)
                        self.sessions[sid]=session
                    else:session=None
                if not session:return await response(send,401,{'detail':'启动链接已使用或过期，请再次运行 ./start'})
                return await response(send,200,{'csrf':session[0]},[(b'set-cookie',f'{self.cookie}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'.encode())])
            if path.startswith('/api/'):
                if not session:return await response(send,401,{'detail':'请运行 ./start 打开本机工作台'})
                if method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(headers.get('x-pitr-csrf',''),session[0]):
                    return await response(send,403,{'detail':'浏览器会话已更新，请刷新页面后重试'})
                if path=='/api/local/session' and method=='GET':return await response(send,200,{'csrf':session[0]})
            async def protected_send(message):
                if message['type']=='http.response.start':
                    message['headers']=[*message.get('headers',[]),(b'x-content-type-options',b'nosniff'),
                        (b'referrer-policy',b'no-referrer'),(b'x-frame-options',b'DENY')]
                    if path.startswith('/api/'):message['headers'].append((b'cache-control',b'no-store'))
                await send(message)
            return await app(scope,receive,protected_send)
        return wrapped

"""Foreground local daemon. The OS lock owns the queue and its child processes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import tempfile
import threading
import time
import webbrowser

from .local_auth import LocalAuth


class Instance:
    def __init__(self, root):
        root=Path(root).resolve();private=root/'private';private.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.fd=os.open(private/'daemon.lock',os.O_CREAT|os.O_RDWR,0o600)
        folder=Path(tempfile.gettempdir())/f'pitr-daemon-{os.getuid()}'
        folder.mkdir(mode=0o700,exist_ok=True)
        if folder.is_symlink() or folder.stat().st_uid!=os.getuid():raise RuntimeError('本机服务目录不属于当前用户')
        folder.chmod(0o700)
        self.path=folder/(hashlib.sha256(str(root).encode()).hexdigest()[:24]+'.sock')
        self.server=None;self.thread=None;self.owned=False;self.stopped=threading.Event()

    def acquire(self):
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.owned=True;return True
        except BlockingIOError:return False

    def existing_url(self):
        for _ in range(30):
            try:
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(1);client.connect(str(self.path));client.sendall(b'open\n')
                    data=client.recv(2048)
                    return json.loads(data)['url']
            except (OSError,ValueError,KeyError):time.sleep(.1)
        raise RuntimeError('此数据目录已有服务正在启动或停止，请稍后重试')

    def listen(self,auth):
        self.path.unlink(missing_ok=True)
        self.server=socket.socket(socket.AF_UNIX);self.server.bind(str(self.path));self.path.chmod(0o600)
        self.server.listen(8);self.server.settimeout(.2)
        def work():
            while not self.stopped.is_set():
                try:client,_=self.server.accept()
                except TimeoutError:continue
                except OSError:break
                with client:
                    client.settimeout(1)
                    try:
                        if client.recv(16)==b'open\n':client.sendall(json.dumps({'url':auth.url()}).encode())
                    except OSError:pass
        self.thread=threading.Thread(target=work,daemon=True,name='daemon-open');self.thread.start()

    def close(self):
        self.stopped.set()
        if self.server:self.server.close()
        if self.thread:self.thread.join(2)
        if self.owned:self.path.unlink(missing_ok=True)
        os.close(self.fd)


def serve(root='data/desk_control',port=8765,*,no_open=False,web_dist=None):
    import uvicorn
    from pitr.desk.api import create_app
    if not 1024<=port<=65535:raise ValueError('端口需在 1024–65535 之间')
    instance=Instance(root);listener=None
    try:
        if not instance.acquire():
            url=instance.existing_url()
            print('PITR 已在运行：'+url,flush=True)
            if not no_open:webbrowser.open(url)
            return
        listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:listener.bind(('127.0.0.1',port));listener.listen(128)
        except OSError:raise RuntimeError(f'端口 {port} 已被其他程序使用。请用 ./start --port <其他端口>；未停止其他程序。') from None
        auth=LocalAuth(port);app=create_app(root,web_dist=web_dist)
        config=uvicorn.Config(auth.middleware(app),host='127.0.0.1',port=port,log_level='warning',
                              access_log=False,timeout_graceful_shutdown=3)
        server=uvicorn.Server(config)
        def opened():
            while not server.started and not server.should_exit:time.sleep(.05)
            if server.should_exit:return
            instance.listen(auth);url=auth.url()
            print('PITR 已启动：'+url+'\n此终端保持运行；按 Ctrl+C 停止。',flush=True)
            if not no_open:webbrowser.open(url)
        threading.Thread(target=opened,daemon=True,name='daemon-browser').start()
        old_hup=signal.getsignal(signal.SIGHUP)
        signal.signal(signal.SIGHUP,lambda *_:setattr(server,'should_exit',True))
        try:server.run(sockets=[listener])
        finally:signal.signal(signal.SIGHUP,old_hup)
    finally:
        if listener:listener.close()
        instance.close()


def main():
    parser=argparse.ArgumentParser(description='PITR 本机工作台')
    parser.add_argument('--data-dir',default='data/desk_control')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-open',action='store_true')
    args=parser.parse_args()
    try:serve(args.data_dir,args.port,no_open=args.no_open)
    except (ValueError,RuntimeError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()

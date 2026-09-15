"""Bounded JSONL subprocess transport. A task lease is checked while waiting."""
from __future__ import annotations
import json
import os
import queue
import signal
import subprocess
import threading
import time
import sys


class AgentError(RuntimeError):
    pass


class Process:
    def __init__(self, command, *, cwd, env, fence=lambda: None, timeout=600):
        self.fence = fence
        self.deadline = time.monotonic() + timeout if timeout else None
        self.last_activity = time.monotonic()
        self.cancelled = threading.Event()
        self.messages = queue.Queue(maxsize=2048)
        self.stderr = ''
        self.number = 0
        self.close_lock=threading.Lock();self.closed=False;self.interrupt=None
        self.proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, start_new_session=True)
        # A private pipe closes even on an abrupt daemon exit. Its guardian
        # reaps this one process group; it has no access to task content/auth.
        guard='''import os,signal,sys,time
pid=int(sys.argv[1])
sys.stdin.buffer.read()
for sig in (signal.SIGTERM,signal.SIGKILL):
 try:os.killpg(pid,sig)
 except (ProcessLookupError,PermissionError):break
 time.sleep(.3)
'''
        try:
            self.guardian=subprocess.Popen([sys.executable,'-c',guard,str(self.proc.pid)],stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
        except BaseException:
            try:os.killpg(self.proc.pid,signal.SIGKILL)
            except (ProcessLookupError,PermissionError):pass
            self.proc.wait();raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.errors = threading.Thread(target=self._errors, daemon=True)
        self.reader.start(); self.errors.start()

    def _put(self, item):
        while not self.cancelled.is_set():
            try:
                self.messages.put(item, timeout=.2)
                return
            except queue.Full:
                continue

    def _read(self):
        try:
            while not self.cancelled.is_set():
                line = self.proc.stdout.readline(4 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 4 * 1024 * 1024:
                    self._put(AgentError('Agent 返回的单条事件过大'))
                    break
                self.last_activity = time.monotonic()
                try:
                    self._put(json.loads(line))
                except json.JSONDecodeError:
                    self._put(AgentError('Agent 返回了无效的 JSON 事件；请检查 CLI 版本'))
                    break
        finally:
            self._put(None)

    def _errors(self):
        while not self.cancelled.is_set():
            chunk = self.proc.stderr.read(1024)
            if not chunk:
                break
            self.stderr = (self.stderr + chunk)[-4000:]

    def send(self, value):
        self.fence()
        if self.cancelled.is_set():
            raise AgentError('Agent 执行已停止')
        try:
            self.proc.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise AgentError('Agent 连接已经关闭') from error

    def receive(self):
        while True:
            self.fence()
            if self.cancelled.is_set():
                raise AgentError('Agent 执行已停止')
            if self.deadline and time.monotonic() > self.deadline:
                raise TimeoutError('Agent 调用超时，输入和检查点已保留')
            if time.monotonic() - self.last_activity > 900:
                raise TimeoutError('Agent 连接连续十五分钟没有响应')
            try:
                value = self.messages.get(timeout=.2)
            except queue.Empty:
                continue
            if isinstance(value, BaseException):
                raise value
            if value is None:
                self.errors.join(.1)
                raise AgentError('Agent 在交付结果前退出；请检查登录、模型权限或 CLI 版本。'+self.stderr[-1600:])
            if not isinstance(value, dict):
                raise AgentError('Agent 协议事件必须为对象')
            return value

    def rpc(self, method, params, notify=lambda event: None):
        self.number += 1
        identity = self.number
        self.send({'id': identity, 'method': method, 'params': params})
        while True:
            value = self.receive()
            if value.get('id') == identity and 'method' not in value:
                if 'error' in value:
                    raise AgentError(str(value['error'].get('message', 'Agent 协议请求失败')))
                return value.get('result', {})
            notify(value)

    def close(self):
        with self.close_lock:
            if self.closed:return
            self.closed=True
        if self.interrupt and self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps(self.interrupt)+'\n');self.proc.stdin.flush()
            except (OSError,ValueError):pass
        self.cancelled.set()
        # Kill the group even if its leader has already exited: MCP children
        # must not outlive the turn that granted their capability.
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError,PermissionError):
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError,PermissionError):
            pass
        self.proc.wait(timeout=5)
        self.guardian.stdin.close()
        try:self.guardian.wait(timeout=2)
        except subprocess.TimeoutExpired:self.guardian.kill();self.guardian.wait()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, BrokenPipeError):
                pass
        self.reader.join(1); self.errors.join(1)

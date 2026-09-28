import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
from pitr.config import project_root
from pitr.domain.common import uid


class LocalJudge:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('PITR_LAYA_HOME', project_root() / '.pitr/laya')).expanduser().resolve()
        self.process = None
        self.lock = threading.RLock()
        self.log = None
        self.last = {}

    @property
    def ready(self):
        return (self.home / 'model-lock.json').is_file() and (self.home / 'venv/bin/python').is_file()

    def call(self, method, data, timeout=180):
        with self.lock:
            if not self.ready: raise ValueError('本地模型尚未安装，请在“来源与运行”安装模型')
            if not self.process or self.process.poll() is not None:
                self.close()
                self.log = (self.home / 'runtime.log').open('a')
                self.process = subprocess.Popen([str(self.home / 'venv/bin/python'), '-u', str(project_root() / 'services/laya/worker.py'), str(self.home)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
                    env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'USE_TF': '0'})
            key = uid('rpc')
            try:
                self.process.stdin.write(json.dumps({'id': key, 'method': method, 'data': data}, ensure_ascii=False)+'\n')
                self.process.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    if not selector.select(timeout): raise TimeoutError('本地推理超时，任务可重试')
                line = self.process.stdout.readline()
                if not line: raise ValueError('本地模型进程已退出，请查看运行记录')
                reply = json.loads(line)
                if reply.get('error'): raise ValueError(reply['error'])
                if reply['id'] != key: raise ValueError('本地推理响应身份不一致')
                return reply['result']
            except Exception:
                self.close()
                raise

    def encode(self, texts): return self.call('encode', {'texts': texts})

    def predict(self, context, text):
        result = self.call('predict', {'context': context, 'text': text})
        self.last = {k: result[k] for k in ('device', 'model', 'sdk', 'peak_mps_driver_bytes') if k in result}
        return result

    def close(self):
        with self.lock:
            if self.process:
                self.process.terminate()
                try: self.process.wait(timeout=3)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
                self.process = None
            if self.log: self.log.close(); self.log = None

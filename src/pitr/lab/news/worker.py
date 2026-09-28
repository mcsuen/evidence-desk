"""One independent Lab worker, renewable leases, coalesced scheduling and recovery."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pitr.config import project_root
from pitr.domain.common import utcnow
from pitr.domain.common import canonical, uid
from .contracts import NewsRunInput


class NewsWorker:
    def __init__(self, news):
        self.news = news
        self.owner = uid('newsworker')
        self.stopped = threading.Event()
        self.thread = None
        self.install_process = None

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stopped.clear()
        self.thread = threading.Thread(target=self.loop, name='lab-news', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.stop_installer()
        # Wake a blocked RPC without waiting on its serialization lock.
        if self.news.judge.process: self.news.judge.process.terminate()
        if self.thread: self.thread.join(5)
        if not self.thread or not self.thread.is_alive(): self.news.judge.close()

    def stop_installer(self):
        process = self.install_process
        if process and process.poll() is None:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass

    def loop(self):
        while not self.stopped.is_set():
            try:
                settings = self.news.settings()
                if settings.enabled:
                    slot = int(time.time() // (settings.cadence_minutes*60))
                    self.news.enqueue(NewsRunInput(operation_id='news-schedule:'+str(settings.cadence_minutes)+':'+str(slot)))
                if not self.run_one(): self.stopped.wait(3)
            except Exception as error:
                self.news.store.set('worker_error', {'error': str(error), 'at': utcnow()})
                self.stopped.wait(5)

    def run_one(self):
        store = self.news.store
        with store.connect(write=True) as db:
            now = time.time()
            if db.execute("SELECT 1 FROM runs WHERE status='running' AND lease>?", (now,)).fetchone(): return False
            row = db.execute("SELECT * FROM runs WHERE status='queued' OR (status='running' AND lease<?) ORDER BY rowid LIMIT 1", (now,)).fetchone()
            if not row: return False
            job = json.loads(row['body'])
            job.update(status='running', started_at=utcnow(), recovered=row['status'] == 'running')
            db.execute('UPDATE runs SET status=?,owner=?,lease=?,body=? WHERE id=?', ('running', self.owner, now+45, canonical(job), job['id']))
        finished = threading.Event()
        def renew():
            while not finished.wait(10):
                with store.connect(write=True) as db:
                    db.execute("UPDATE runs SET lease=? WHERE id=? AND owner=? AND status='running'", (time.time()+45, job['id'], self.owner))
        threading.Thread(target=renew, daemon=True).start()
        def fence():
            if self.stopped.is_set(): raise RuntimeError('系统停止，任务可恢复')
            with store.connect() as db:
                if not db.execute("SELECT 1 FROM runs WHERE id=? AND owner=? AND status='running' AND lease>?", (job['id'], self.owner, time.time())).fetchone():
                    raise RuntimeError('新闻任务租约已变更')
        def progress(value):
            fence()
            job['progress'].update(value)
            with store.connect(write=True) as db:
                db.execute('UPDATE runs SET body=? WHERE id=? AND owner=?', (canonical(job), job['id'], self.owner))
        try:
            if job['kind'] == 'install':
                self.news.judge.close()
                home = self.news.judge.home
                home.mkdir(parents=True, exist_ok=True)
                with (home / 'install.log').open('a') as log:
                    self.install_process = subprocess.Popen([sys.executable, str(project_root() / 'services/laya/install.py'), '--home', str(home)], stdout=log, stderr=log, start_new_session=True)
                    started = time.monotonic()
                    while self.install_process.poll() is None:
                        fence()
                        if time.monotonic()-started > 3600:
                            self.stop_installer()
                            raise TimeoutError('安装超过一小时，请查看安装日志后重试')
                        self.stopped.wait(1)
                    if self.install_process.returncode: raise ValueError('模型安装失败，请查看本机安装日志：'+str(home / 'install.log'))
                    job['progress'] = {'installed': True}
                self.install_process = None
            elif job['kind'] == 'rescore': job['progress'].update(self.news.rescore(fence, progress, force=True))
            else: job['progress'].update(self.news.collect(fence, progress))
            fence()
            job.update(status='partial' if job['progress'].get('errors') else 'completed', finished_at=utcnow())
        except Exception as error:
            job.update(status='queued' if self.stopped.is_set() else 'failed', error=str(error), finished_at=utcnow())
        finally:
            self.stop_installer()
            self.install_process = None
            finished.set()
            with store.connect(write=True) as db:
                db.execute('UPDATE runs SET status=?,lease=0,body=? WHERE id=? AND owner=?', (job['status'], canonical(job), job['id'], self.owner))
        return True

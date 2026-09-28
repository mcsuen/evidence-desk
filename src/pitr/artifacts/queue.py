"""One export lane. Files and manifests commit atomically after structural/render checks."""
import json
import tempfile
from pathlib import Path
import threading
import time

from pitr.domain.common import canonical, uid, utcnow
from pitr.domain.contracts import Artifact, ExportJob
from .docx import compile_docx, TEMPLATE, COMPILER
from .render import render, verify_text


class ExportQueue:
    def __init__(self,station,*,start=True,renderer=render):
        self.station,self.store,self.renderer=station,station.store,renderer
        self.owner=uid('export_worker');self.stopping=threading.Event()
        self.thread=threading.Thread(target=self.loop,daemon=True,name='word-exports')
        if start:self.thread.start()

    def claim(self):
        with self.store.connect(write=True) as db:
            if db.execute("SELECT 1 FROM exports WHERE status='running' AND lease_until>?",(time.time(),)).fetchone():return None
            row=db.execute("SELECT * FROM exports WHERE status='queued' OR (status='running' AND lease_until<=?) ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
            if not row:return None
            job=ExportJob.model_validate_json(row['body']);job.status='running';job.attempts+=1;job.updated_at=utcnow()
            db.execute('UPDATE exports SET status=?,owner=?,lease_until=?,body=? WHERE id=?',
                       ('running',self.owner,time.time()+180,canonical(job),job.id))
            report=self.store.get(job.report,'report',db=db)
            self.store.event(db,report.run_id,'export.claimed',{'job':job.id,'report':job.report,'attempt':job.attempts})
            return job

    def perform(self,job):
        done=threading.Event()
        def heartbeat():
            while not done.wait(15):
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE exports SET lease_until=? WHERE id=? AND owner=? AND status='running' AND lease_until>?",
                               (time.time()+180,job.id,self.owner,time.time()))
        renewer=threading.Thread(target=heartbeat,daemon=True);renewer.start()
        try:
            view=self.station.reports.view(job.report)
            view=view.model_copy(update={'checks':[self.store.get(r,'check') for r in job.check_refs], 'delivery':job.delivery_at_request})
            raw,manifest=compile_docx(view,job.paper)
            with tempfile.TemporaryDirectory(prefix='pitr-export-') as directory:
                path=Path(directory)/'report.docx';path.write_bytes(raw)
                rendered=self.renderer(path,Path(directory)/'render')
                text_check=verify_text(rendered['text'],manifest['text'],view.document.revision)
                manifest['render']={'page_count':rendered['page_count'],'checks':rendered['checks'],
                    'text_check':text_check,
                    'fonts':rendered.get('fonts',[]),
                    'pdf_digest':self.store.blob(rendered['pdf'].read_bytes()),
                    'page_digests':[self.store.blob(p.read_bytes()) for p in rendered['images']]}
            sha=self.store.blob(raw)
            artifact=Artifact(id=uid('artifact'),created_at=utcnow(),report=job.report,digest=sha,
                template_version=TEMPLATE,compiler_version=COMPILER,paper=job.paper,manifest=manifest)
            with self.store.connect(write=True) as db:
                row=db.execute('SELECT owner,status,lease_until FROM exports WHERE id=?',(job.id,)).fetchone()
                if row['owner']!=self.owner or row['status']!='running' or row['lease_until']<time.time():return
                self.store.put(db,'artifact',artifact,dependencies=[job.report])
                job.status,job.artifact,job.error,job.updated_at='completed',artifact.ref,'',utcnow()
                db.execute('UPDATE exports SET status=?,owner=NULL,lease_until=NULL,body=? WHERE id=?',('completed',canonical(job),job.id))
                self.store.event(db,self.store.get(job.report,'report',db=db).run_id,'export.completed',{'job':job.id,'artifact':artifact.ref,'digest':sha})
        except Exception as error:
            with self.store.connect(write=True) as db:
                row=db.execute('SELECT owner,status,lease_until FROM exports WHERE id=?',(job.id,)).fetchone()
                if row['owner']!=self.owner or row['status']!='running' or row['lease_until']<=time.time():return
                job.status,job.error,job.updated_at='failed',str(error)[:3000],utcnow()
                db.execute('UPDATE exports SET status=?,owner=NULL,lease_until=NULL,body=? WHERE id=?',('failed',canonical(job),job.id))
                self.store.event(db,self.store.get(job.report,'report',db=db).run_id,'export.failed',{'job':job.id,'error':job.error})
        finally:
            done.set();renewer.join(2)

    def loop(self):
        while not self.stopping.is_set():
            job=self.claim()
            if job:self.perform(job)
            self.stopping.wait(.4)

    def close(self):
        self.stopping.set()
        if self.thread.is_alive():self.thread.join(5)

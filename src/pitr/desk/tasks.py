"""Persistent one-worker queue with renewable leases and fenced completion."""
import json
import threading
import time
from .contracts import TaskInput, utcnow
from .storage import canonical, uid


class Queue:
    def __init__(self,desk):
        from .research.service import initialize
        initialize(desk)
        self.desk=desk;self.owner=uid('worker');self.stop_event=threading.Event();self.thread=None

    def enqueue(self,req: TaskInput):
        if req.workflow=='research':raise ValueError('原生研究请使用统一 research/requests 请求入口')
        task={'id':uid('task'),'request':req.model_dump(),'status':'queued','created_at':utcnow(),'stage':'queued',
              'versions':{'workflow':'desk.1','tools':'desk-tools.1'},'attempts':0}
        with self.desk.store.connect(write=True) as db:
            cached=self.desk.store.cached(db,req.operation_id,req)
            if cached:return cached
            if req.snapshot:self.desk._snapshot(db,req.snapshot)
            if (req.workflow.startswith('wiki_') and not (req.workflow=='wiki_inspect' and req.parameters.get('kind','rules')=='rules')):
                from pitr.agent_runtime import bind_task
                bind_task(self.desk,task,req.agent_provider,req.model or req.parameters.get('model'))
            db.execute('INSERT INTO tasks(id,status,body) VALUES(?,?,?)',(task['id'],'queued',canonical(task)))
            self.desk.store.remember(db,req.operation_id,req,task)
        return task

    def claim(self):
        with self.desk.store.connect(write=True) as db:
            now=time.time()
            if db.execute("SELECT 1 FROM tasks WHERE status='running' AND lease_until>=?",(now,)).fetchone():return None
            row=db.execute("SELECT * FROM tasks WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY CASE WHEN body LIKE '%wiki_inspect%' THEN 2 WHEN body LIKE '%wiki_compile%' OR body LIKE '%wiki_job%' THEN 1 ELSE 0 END,rowid LIMIT 1",(now,)).fetchone()
            if not row:return None
            task=json.loads(row['body']);attempt=row['attempts']+1
            task.update(recovered_lease=row['status']=='running' or task.get('stage')=='interrupted',status='running',attempts=attempt,started_at=utcnow())
            db.execute('UPDATE tasks SET status=?,owner=?,lease_until=?,attempts=?,body=? WHERE id=?',('running',self.owner,now+30,attempt,canonical(task),task['id']))
            return task

    def checkpoint(self,task,updates):
        task.update(updates)
        with self.desk.store.connect(write=True) as db:
            cur=db.execute("UPDATE tasks SET body=?,lease_until=? WHERE id=? AND owner=? AND status='running'",(canonical(task),time.time()+30,task['id'],self.owner))
            if cur.rowcount!=1:raise RuntimeError('任务已取消或租约已转移')
        self._observe_research(task)

    def _observe_research(self,task):
        if task.get('request',{}).get('workflow')=='research' and task.get('research',{}).get('trace_version'):
            from .research.trace.store import SafeTrace
            SafeTrace(self.desk,task['id']).observe_task(task)

    def run_one(self):
        task=self.claim()
        if not task:return False
        self._observe_research(task)
        done=threading.Event()
        def heartbeat():
            while not done.wait(8):
                with self.desk.store.connect(write=True) as db:db.execute("UPDATE tasks SET lease_until=? WHERE id=? AND owner=? AND status='running'",(time.time()+30,task['id'],self.owner))
        threading.Thread(target=heartbeat,daemon=True).start()
        from pitr.agent_runtime import task_scope
        def agent_fence():
            with self.desk.store.connect() as db:
                active=db.execute("SELECT 1 FROM tasks WHERE id=? AND owner=? AND status='running' AND lease_until>=?",(task['id'],self.owner,time.time())).fetchone()
            if not active or self.stop_event.is_set():raise RuntimeError('任务已停止或租约已转移')
        scope=task_scope(self.desk,task,agent_fence);scope.__enter__()
        try:
            req=task['request'];workflow=req['workflow'];params=req['parameters']
            if workflow=='disclosures':
                from .sources import pdd_catalog,fetch,pdd_pdf_fallback
                if req['company']!='PDD':raise ValueError('此公司请先通过原始披露链接导入')
                imported=[]
                catalog=pdd_catalog()[:16]
                for index,item in enumerate(catalog):
                    # Re-fetch the latest releases: a stable URL can acquire a
                    # revised original. Older originals are retained by hash.
                    known={d.id for d in self.desk.documents('PDD')}
                    if index>=4 and any(d.url==item['url'] for d in self.desk.documents('PDD')):continue
                    try:raw,media,url=fetch(item['url'])
                    except ValueError:raw,media,url=pdd_pdf_fallback(item['period'])
                    doc=self.desk.ingest(raw,media,url,'PDD',item['title'])
                    if doc.id not in known:imported.append(doc.id)
                    self.checkpoint(task,{'stage':'importing','imported':imported})
                result={'imported':imported}
            elif workflow=='research':
                from .research.native import run
                result=run(self.desk,task,self.owner,lambda u:self.checkpoint(task,u))
            elif workflow=='wiki_compile':
                from pitr.wiki.worker import compile_sources
                result=compile_sources(self.desk.wiki,task,lambda u:self.checkpoint(task,u))
            elif workflow=='wiki_job':
                from pitr.wiki.jobs import run
                result=run(self.desk.wiki,task,self.owner,lambda u:self.checkpoint(task,u))
            elif workflow=='wiki_answer':
                from pitr.wiki.research import generate_answer
                result=generate_answer(self.desk.wiki,task,lambda u:self.checkpoint(task,u))
            elif workflow=='wiki_inspect':
                from pitr.wiki.inspection import inspect
                def fence(db):
                    if not db.execute("SELECT 1 FROM tasks WHERE id=? AND owner=? AND status='running' AND lease_until>=?",(task['id'],self.owner,time.time())).fetchone():
                        raise RuntimeError('巡检已取消或执行权已转移')
                result=inspect(self.desk.wiki,req['company'],params.get('kind','rules'),run_id='inspection:'+task['id'],budget_seconds=req['budget_seconds'],checkpoint=lambda u:self.checkpoint(task,u),fence=fence)
            else:
                raise ValueError('未知工作流：'+workflow)
            task.update(status='waiting_user' if result.get('status')=='waiting_user' else 'failed' if result.get('status')=='failed' else 'cancelled' if result.get('status')=='cancelled' else 'completed',stage='clarification' if result.get('status')=='waiting_user' else 'finished',result=result,finished_at=utcnow())
        except Exception as error:task.update(status='failed',error=str(error),finished_at=utcnow())
        finally:
            scope.__exit__(None,None,None)
            done.set()
            with self.desk.store.connect(write=True) as db:
                active=db.execute("SELECT 1 FROM tasks WHERE id=? AND owner=? AND status='running' AND lease_until>=?",(task['id'],self.owner,time.time())).fetchone()
                if active and (task.get('result',{}).get('wiki_proposal') or task.get('result',{}).get('wiki_answer')):
                    db.execute('SAVEPOINT wiki_task_effects')
                    try:
                        if task['result'].get('wiki_proposal'):
                            from pitr.wiki.contracts import ProposalInput as WikiProposal
                            proposal=self.desk.wiki.propose(WikiProposal.model_validate(task['result']['wiki_proposal']),db=db)
                            task['result']['proposal_id']=proposal['id']
                        else:
                            from pitr.wiki.contracts import AnswerInput
                            from pitr.wiki.research import save_answer
                            task['result']['answer']=save_answer(self.desk.wiki,AnswerInput.model_validate(task['result']['wiki_answer']),db=db)
                        db.execute('RELEASE wiki_task_effects')
                    except Exception as error:
                        db.execute('ROLLBACK TO wiki_task_effects')
                        db.execute('RELEASE wiki_task_effects')
                        task.update(status='failed',error=str(error))
                if active and req['workflow']=='wiki_inspect' and task['status']=='failed':
                    from pitr.wiki.store import get,change
                    inspection=get(db,'inspections','inspection:'+task['id'])
                    if inspection:
                        inspection['finished_at']=utcnow()
                        inspection['failures'].append({'target':'run','reason':task.get('error','执行失败')})
                        self.desk.wiki._emit(db,req['company'],'inspection.failed',[change('inspections',inspection['id'],inspection)])
                if active and req['workflow']=='wiki_job':
                    from pitr.wiki.jobs import finalize
                    finalize(self.desk.wiki,db,task)
                if active and req['workflow']=='research' and task['status']=='completed':
                    pending=db.execute("SELECT status FROM research_interpretations WHERE request_id=? AND status IN ('pending','running','ready','error','clarification') ORDER BY version DESC LIMIT 1",(req['parameters']['request_id'],)).fetchone()
                    if pending:
                        task.update(status='queued' if pending['status']=='ready' else 'waiting_user',stage='queued' if pending['status']=='ready' else 'awaiting_input')
                        task.pop('finished_at',None)
                if active:
                    db.execute("UPDATE tasks SET status=?,body=?,lease_until=NULL WHERE id=? AND owner=? AND status='running'",(task['status'],canonical(task),task['id'],self.owner))
        if active:self._observe_research(task)
        return True

    def start(self):
        from .research.intake import IntakeWorker
        self.intake_worker=IntakeWorker(self.desk,self)
        self.intake_worker.start()
        def work():
            while not self.stop_event.is_set():
                try:
                    if not self.run_one():self.stop_event.wait(1)
                except Exception:self.stop_event.wait(2)
        self.thread=threading.Thread(target=work,daemon=True,name='desk-worker');self.thread.start()

    def stop(self):
        self.stop_event.set()
        if hasattr(self,'intake_worker'):self.intake_worker.stop()
        with self.desk.store.connect(write=True) as db:
            for row in db.execute("SELECT id,body FROM tasks WHERE status='running' AND owner=?",(self.owner,)).fetchall():
                task=json.loads(row['body'])
                task.update(status='queued',stage='interrupted')
                db.execute("UPDATE tasks SET status='queued',owner=NULL,lease_until=NULL,body=? WHERE id=?",(canonical(task),row['id']))
        if getattr(self.desk,'agents',None):self.desk.agents.shutdown()
        if getattr(self,'thread',None):self.thread.join(5)

    def cancel(self,tid):
        with self.desk.store.connect(write=True) as db:
            row=db.execute('SELECT body FROM tasks WHERE id=?',(tid,)).fetchone()
            if not row:raise KeyError('任务不存在')
            task=json.loads(row['body'])
            if task['status'] in ('queued','running','waiting_user'):
                task.update(status='cancelled',finished_at=utcnow())
                db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('cancelled',canonical(task),tid))
                if task['request']['workflow']=='research':
                    rid=task['request']['parameters']['request_id']
                    db.execute("UPDATE research_interpretations SET status='superseded',owner=NULL,lease_until=NULL WHERE request_id=? AND status IN ('pending','running','ready','error','clarification')",(rid,))
                    db.execute("UPDATE research_messages SET status='saved' WHERE request_id=? AND status IN ('received','ready')",(rid,))
                if task['request']['workflow']=='wiki_job':
                    from pitr.wiki.jobs import finalize
                    finalize(self.desk.wiki,db,task)
                if getattr(self.desk,'agents',None):self.desk.agents.cancel(tid)
        self._observe_research(task)
        return task

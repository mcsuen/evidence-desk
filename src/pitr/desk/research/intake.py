"""Durable, independent intake lane and append-only user updates for research."""
from __future__ import annotations
import json, threading, time, re
from .contracts import ResearchRequest, ResearchTaskInput
from ..contracts import utcnow
from ..storage import canonical, digest, uid, Conflict

SCHEMA='''
CREATE TABLE IF NOT EXISTS research_entities(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_messages(id TEXT PRIMARY KEY, request_id TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(request_id,ordinal));
CREATE TABLE IF NOT EXISTS research_interpretations(request_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, owner TEXT, lease_until REAL, body TEXT NOT NULL, PRIMARY KEY(request_id,version));
'''

def raw_request(db,rid):
    row=db.execute('SELECT body FROM research_requests WHERE id=? OR task_id=?',(rid,rid)).fetchone()
    if not row:raise KeyError('研究记录不存在')
    r=json.loads(row['body']);r['task']=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(r['task_id'],)).fetchone()['body']);return r

def messages(db,rid):
    return [{**json.loads(r['body']),'id':r['id'],'ordinal':r['ordinal'],'status':r['status']} for r in db.execute('SELECT * FROM research_messages WHERE request_id=? ORDER BY ordinal',(rid,))]

def describe(db,r):
    rows=db.execute('SELECT * FROM research_interpretations WHERE request_id=? ORDER BY version DESC',(r['id'],)).fetchall()
    latest=rows[0] if rows else None
    applied=next((x for x in rows if x['status']=='applied'),None)
    row=latest if latest and latest['status'] in ('ready','applied','clarification') else applied
    details=json.loads(row['body']) if row else {}
    r['interpretation']=details.get('interpretation')
    r['interpretation_status']=latest['status'] if latest else 'pending'
    r['interpretation_error']=json.loads(latest['body']).get('error','') if latest else ''
    r['conversation_version']=latest['version'] if latest else 0
    r['messages']=messages(db,r['id'])
    r['input_version']=r['task'].get('research',{}).get('input_version',0)
    r['activity']=activity(db,r)
    r['updated_at']=max([r['created_at'],r['task'].get('finished_at',''),r['task'].get('research',{}).get('progress',{}).get('saved_at',''),*[m['created_at'] for m in r['messages']]])
    return r

def activity(db,r):
    task=r['task'];state=task.get('research',{});items=[]
    names={'interpreting':'正在理解研究问题','awaiting_input':'正在理解补充信息','queued':'等待开始调查','prepared':'研究资料已准备',
           'investigating':'正在查证核心问题','independent_review':'正在独立复核结论','repairing':'正在补查并修订','recovering':'正在恢复连接',
           'search_public':'正在寻找公开原件','fetch_public_source':'正在获取原始资料','read_page':'正在阅读原文','read_source':'正在阅读原文',
           'register_numbers':'正在核对关键数字','calculate':'正在计算可比指标','save_checkpoint':'已保存阶段进展','finished':'本轮研究已结束',
           'clarification':'等待补充关键信息','clarification_requested':'等待补充关键信息','understanding_failed':'问题理解失败，可以重试'}
    items.append({'kind':'status','text':names.get(task.get('stage'), '正在调查与核对资料' if task['status']=='running' else task['status']), 'at':task.get('finished_at',task.get('started_at',task['created_at']))})
    for row in db.execute("SELECT body FROM research_receipts WHERE task_id=? AND kind='checkpoint' ORDER BY rowid DESC LIMIT 3",(r['task_id'],)):
        c=json.loads(row['body']);items.append({'kind':'finding','text':c.get('findings',''),'next_steps':c.get('next_steps',''),'at':c.get('at',''),'provisional':True})
    return {'items':items,'questions':list(state.get('requirements',{}).values()),'reading_count':db.execute("SELECT COUNT(*) FROM research_receipts WHERE task_id=? AND kind='reading'",(r['task_id'],)).fetchone()[0]}

class Intake:
    def __init__(self,desk,queue=None):self.desk=desk;self.queue=queue

    def create(self,req,*,resolved=None,parent=None):
        payload=req.model_dump();rid=uid('research');tid=uid('task');now=utcnow()
        with self.desk.store.connect(write=True) as db:
            cached=self.desk.store.cached(db,req.operation_id,payload)
            if cached:return describe(db,raw_request(db,cached['id']))
            self.validate_sources(db,req.source_ids,req.as_of)
            if not req.question.strip() and not req.source_ids:raise ValueError('请输入研究问题或添加材料')
            if req.snapshot:
                snap=self.desk._snapshot(db,req.snapshot)
                if req.company and snap['company']!=req.company:raise ValueError('公司与固定快照不一致')
                if req.as_of and req.as_of!=snap['as_of']:raise ValueError('截止时间与固定快照不一致')
            body={'id':rid,'task_id':tid,'created_at':now,'input':payload,'original_question':req.question,'answers':[]}
            task={'id':tid,'status':'waiting_user','created_at':now,'stage':'interpreting','attempts':0,
                  'request':ResearchTaskInput(operation_id=req.operation_id,company=req.company,parameters={'request_id':rid,'question':req.question,'period':req.period},budget_seconds=req.budget_seconds,snapshot=req.snapshot).model_dump(),
                  'versions':{'workflow':'native-research.3','model':req.model,'reasoning':req.reasoning},
                  'research':{'controller_id':digest(str(self.desk.store.path.resolve()))[:20],'active_seconds':0,'tool_calls':0,'session_id':None,'input_version':0,'repairs':0,'recoveries':0,'questions':[],'trace_version':'research-trace.1'}}
            from pitr.agent_runtime import bind_task
            bind_task(self.desk,task,req.agent_provider,req.model,req.reasoning if 'reasoning' in req.model_fields_set else None,parent=parent)
            db.execute('INSERT INTO research_requests VALUES(?,?,?)',(rid,tid,canonical(body)))
            db.execute('INSERT INTO tasks(id,status,body) VALUES(?,?,?)',(tid,task['status'],canonical(task)))
            job={'created_at':now,'through_ordinal':0}
            if resolved:job['interpretation']=resolved
            db.execute('INSERT INTO research_interpretations VALUES(?,?,?,?,?,?)',(rid,1,'ready' if resolved else 'pending',None,None,canonical(job)))
            if resolved:self.apply_initial(db,body,task,resolved,1)
            self.desk.store.remember(db,req.operation_id,payload,{'id':rid})
            return describe(db,raw_request(db,rid))

    def validate_sources(self,db,ids,cutoff):
        if len(set(ids))>10:raise ValueError('一次研究最多十个附件')
        from ..service import stamp
        for sid in ids:
            row=db.execute('SELECT body FROM documents WHERE id=?',(sid,)).fetchone()
            if not row:raise ValueError('附件尚未上传完成')
            d=json.loads(row['body'])
            if cutoff and stamp(d['available_at'])>stamp(cutoff):raise ValueError('新附件晚于固定信息截止时间；请明确更新研究时点后补充')

    def send(self,rid,msg):
        payload={'request_id':rid,**msg.model_dump()}
        with self.desk.store.connect(write=True) as db:
            cached=self.desk.store.cached(db,msg.operation_id,payload)
            if cached:return describe(db,raw_request(db,cached['id']))
            r=raw_request(db,rid)
            if not msg.text.strip() and not msg.source_ids and not msg.company and not msg.intent:raise ValueError('请输入补充内容或添加材料')
            if r['task'].get('research',{}).get('input_version',0)!=msg.expected_input_version:raise Conflict('研究资料已更新，请刷新后重新提交；补充内容仍保留')
            ids=list(dict.fromkeys(r['input']['source_ids']+msg.source_ids))
            self.validate_sources(db,ids,msg.as_of or r['input'].get('as_of'))
            ordinal=db.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM research_messages WHERE request_id=?',(rid,)).fetchone()[0]
            mid=uid('message');body={**msg.model_dump(),'created_at':utcnow()}
            db.execute('INSERT INTO research_messages VALUES(?,?,?,?,?)',(mid,rid,ordinal,'received',canonical(body)))
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM research_interpretations WHERE request_id=?',(rid,)).fetchone()[0]
            # Supersede unclaimed interpretations; running work is fenced by the newest version.
            db.execute("UPDATE research_interpretations SET status='superseded' WHERE request_id=? AND status IN ('pending','running','ready','clarification','error')",(rid,))
            db.execute('INSERT INTO research_interpretations VALUES(?,?,?,?,?,?)',(rid,version,'pending',None,None,canonical({'created_at':utcnow(),'through_ordinal':ordinal})))
            task=r['task']
            if task['status'] not in ('running','completed','cancelled','failed'):
                task.update(status='waiting_user',stage='interpreting');task['research']['questions']=[]
                db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',(task['status'],canonical(task),task['id']))
            self.desk.store.remember(db,msg.operation_id,payload,{'id':rid})
            return describe(db,raw_request(db,rid))

    @staticmethod
    def normalized_input(r,value,updates):
        inp=dict(r['input']);target=[s['company_id'] for s in value['subjects'] if s['role']=='target' and s['company_id']]
        active=[s for s in value['subjects'] if s['role']!='excluded' and s['company_id']]
        inp.update(company=target[0] if len(target)==1 and value['scope_type']=='company' else 'INDUSTRY',
                   period=value['period'],intent=value['intent'] if value['intent']!='collect' else 'investigation',
                   as_of=value['as_of'],scope={'type':value['scope_type'],'topic':value['topic'],'subjects':active,'questions':value['questions'],'plan':value['plan'],'time_description':value['time_description'],'allow_public_search':value.get('allow_public_search',True)})
        base=r.get('original_question',r['input']['question'])
        inp['question']='\n'.join([base,*[m['text'] for m in updates if m.get('text')]]).strip()
        inp['official_urls']=list(dict.fromkeys(inp['official_urls']+re.findall(r'https://[^\s<>|]+',inp['question'])))
        if len(inp['official_urls'])>10:raise ValueError('单请求最多十个来源链接')
        inp['source_ids']=list(dict.fromkeys(inp['source_ids']+[sid for m in updates for sid in m.get('source_ids',[])]))
        if value.get('context_action')=='replace':
            inp.update(snapshot='',model_draft_id='',context={k:v for k,v in inp['context'].items() if k=='slack'},context_source='none')
        if inp['company']!=r['input']['company'] and not inp.get('snapshot'):inp['context']={k:v for k,v in inp['context'].items() if k not in ('wiki_refs','metric','thesis_id')}
        return inp

    def apply_initial(self,db,r,task,value,version):
        updates=messages(db,r['id']);proposed=self.normalized_input(r,value,updates)
        if proposed.get('snapshot'):
            snap=self.desk._snapshot(db,proposed['snapshot'])
            if snap['company']!=proposed['company']:
                value.update(clarification='研究对象与固定模型上下文不同，本次以哪个为准？',options=['以新问题为准，移除原上下文','保留原公司和固定上下文'])
        if not value['clarification']:
            if proposed.get('model_draft_id'):
                from ..company_model import get_draft
                draft=get_draft(self.desk,proposed['model_draft_id'])
                if draft['spec']['snapshot']!=proposed['snapshot'] or draft['spec']['anchor_period']!=proposed['period']:
                    value.update(clarification='研究期间与固定模型不同，是否按新问题研究并移除原模型？',options=['按新问题研究，移除原模型','保留原模型期间'])
            if proposed['context'].get('wiki_refs'):
                from pitr.wiki.service import refkey,BLOCKED
                visible=self.desk.wiki._view_state(db,proposed.get('as_of'))
                for ref in proposed['context']['wiki_refs']:
                    key=ref if isinstance(ref,str) else refkey(ref);revision=visible.get('revisions',{}).get(key)
                    if not revision or revision['company'] not in [s['company_id'] for s in proposed['scope']['subjects']] or visible.get('status',{}).get(key,{}).get('availability') in BLOCKED:
                        value.update(clarification='带入的 Wiki 依据已失效或不适用于本次范围。是否移除后继续？',options=['移除旧上下文，按新问题研究'])
            if not value['clarification']:r['input']=proposed
        questions=[value['clarification']] if value['clarification'] else []
        task['research']['questions']=questions
        task['request'].update(company=r['input']['company'],snapshot=r['input']['snapshot'])
        task['request']['parameters'].update(question=r['input']['question'],period=r['input']['period'])
        task.update(status='waiting_user' if questions else 'queued',stage='clarification' if questions else 'queued')
        if not questions and value['intent']=='collect':
            from pitr.wiki.contracts import CaptureEnvelope
            for sid in r['input']['source_ids']:
                doc=self.desk.document(sid)
                self.desk.wiki.capture(CaptureEnvelope(operation_id='research-collect:'+r['id']+':'+sid,provider='manual',external_id=sid,company=r['input']['company'],title=doc.title,text='\n'.join(b.text for b in doc.blocks),origin='user'),db=db)
            task.update(status='completed',stage='collected',result={'status':'collected','source_ids':r['input']['source_ids']},finished_at=utcnow())
        saved={k:v for k,v in r.items() if k!='task'}
        db.execute('UPDATE research_requests SET body=? WHERE id=?',(canonical(saved),r['id']))
        db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',(task['status'],canonical(task),task['id']))
        job=json.loads(db.execute('SELECT body FROM research_interpretations WHERE request_id=? AND version=?',(r['id'],version)).fetchone()['body'])
        job['interpretation']=value
        db.execute('UPDATE research_interpretations SET status=?,body=? WHERE request_id=? AND version=?',('clarification' if questions else 'applied',canonical(job),r['id'],version))
        if not questions:db.execute("UPDATE research_messages SET status='applied' WHERE request_id=? AND status IN ('received','ready')",(r['id'],))

class IntakeWorker:
    def __init__(self,desk,queue=None,resolver=None):
        self.desk=desk;self.queue=queue;self.stop_event=threading.Event();self.owner=uid('intake');self.resolver=resolver
    def start(self):
        def work():
            while not self.stop_event.is_set():
                try:
                    if not self.run_one():self.stop_event.wait(.5)
                except Exception:self.stop_event.wait(1)
        self.thread=threading.Thread(target=work,daemon=True,name='research-intake');self.thread.start()
    def stop(self):
        self.stop_event.set()
        with self.desk.store.connect(write=True) as db:
            db.execute("UPDATE research_interpretations SET status='pending',owner=NULL,lease_until=NULL WHERE status='running' AND owner=?",(self.owner,))
    def run_one(self):
        # Recover a terminal revision interrupted after interpretation committed.
        with self.desk.store.connect() as db:
            ready=db.execute("SELECT i.* FROM research_interpretations i JOIN research_requests r ON r.id=i.request_id JOIN tasks t ON t.id=r.task_id WHERE i.status='ready' AND t.status IN ('completed','failed','cancelled') ORDER BY i.rowid LIMIT 1").fetchone()
            if ready:
                previous=raw_request(db,ready['request_id']);job_body=json.loads(ready['body'])
                updates=[m for m in messages(db,previous['id']) if m['ordinal']<=job_body['through_ordinal']]
        if ready:
            make_successor(self.desk,previous,job_body['interpretation'],ready['version'],updates,self.queue)
            return True
        with self.desk.store.connect(write=True) as db:
            now=time.time()
            if db.execute("SELECT 1 FROM research_interpretations WHERE status='running' AND lease_until>?",(now,)).fetchone():return False
            job=db.execute("SELECT * FROM research_interpretations WHERE status='pending' OR (status='running' AND lease_until<?) ORDER BY rowid LIMIT 1",(now,)).fetchone()
            if not job:return False
            rid,version=job['request_id'],job['version'];body=json.loads(job['body'])
            r=raw_request(db,rid);updates=[m for m in messages(db,rid) if m['ordinal']<=body['through_ordinal']]
            db.execute("UPDATE research_interpretations SET status='running',owner=?,lease_until=? WHERE request_id=? AND version=?",(self.owner,now+30,rid,version))
        last_lease=0;started=time.monotonic()
        def fence():
            nonlocal last_lease
            if self.stop_event.is_set():raise Conflict('理解服务正在停止，已保存输入')
            if time.monotonic()-started>180:raise Conflict('理解与身份核实暂时超时，输入已保留；请补充上市市场或官方身份依据后重试')
            with self.desk.store.connect() as db:
                row=db.execute('SELECT status,owner FROM research_interpretations WHERE request_id=? AND version=?',(rid,version)).fetchone()
                task=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(r['task_id'],)).fetchone()['body'])
            if row['status']!='running' or row['owner']!=self.owner:raise Conflict('已有更新的补充，停止旧版本理解')
            if task['status']=='cancelled' and r['task']['status']!='cancelled':raise Conflict('研究已停止')
            if time.monotonic()-last_lease>8:
                with self.desk.store.connect(write=True) as db:db.execute('UPDATE research_interpretations SET lease_until=? WHERE request_id=? AND version=? AND owner=?',(time.time()+30,rid,version,self.owner))
                last_lease=time.monotonic()
        try:
            from .semantics import interpret
            from pitr.agent_runtime import task_scope
            with task_scope(self.desk,r['task'],fence):
                value=(self.resolver or interpret)(self.desk,r,updates,rid+'-'+str(version),fence)
            fence();body['interpretation']=value;body['finished_at']=utcnow()
            with self.desk.store.connect(write=True) as db:
                row=db.execute('SELECT status,owner FROM research_interpretations WHERE request_id=? AND version=?',(rid,version)).fetchone()
                if row['status']!='running' or row['owner']!=self.owner:return True
                db.execute("UPDATE research_interpretations SET status='ready',body=?,lease_until=NULL WHERE request_id=? AND version=?",(canonical(body),rid,version))
                current=raw_request(db,rid);task=current['task'];was_terminal=task['status'] in ('completed','cancelled','failed')
                if task['status'] in ('completed','cancelled','failed'):
                    # A completed conversation gets a successor after interpretation, outside this transaction.
                    pass
                elif not task['research']['input_version'] and task['status']!='running':Intake(self.desk).apply_initial(db,current,task,value,version)
                else:
                    db.execute("UPDATE research_messages SET status='ready' WHERE request_id=? AND ordinal<=? AND status='received'",(rid,body['through_ordinal']))
                    if task['status']!='running':
                        task.update(status='queued',stage='queued')
                        db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',(task['status'],canonical(task),task['id']))
            if was_terminal:make_successor(self.desk,current,value,version,updates,self.queue)
        except Exception as error:
            with self.desk.store.connect(write=True) as db:
                row=db.execute('SELECT status,owner FROM research_interpretations WHERE request_id=? AND version=?',(rid,version)).fetchone()
                if row['status']!='running' or row['owner']!=self.owner:return True
                body['error']=str(error)
                db.execute("UPDATE research_interpretations SET status='error',body=?,lease_until=NULL WHERE request_id=? AND version=?",(canonical(body),rid,version))
                current=raw_request(db,rid);task=current['task']
                if task['stage']=='interpreting':
                    task.update(stage='understanding_failed');task['research']['questions']=[]
                    db.execute('UPDATE tasks SET body=? WHERE id=?',(canonical(task),task['id']))
        return True

def make_successor(desk,r,value,version,updates,queue=None):
    from .service import Research
    inp=Intake.normalized_input(r,value,updates)
    # New entity/time means the old financial snapshot must not leak into this revision.
    if inp['company']!=r['input']['company'] or inp.get('as_of')!=r['input'].get('as_of') or inp['period']!=r['input']['period'] or inp.get('scope',{}).get('subjects')!=r['input'].get('scope',{}).get('subjects'):
        inp.update(snapshot='',model_draft_id='',context={k:v for k,v in inp['context'].items() if k=='slack'},context_source='none')
    inp.update(operation_id='research-revision:'+r['id']+':'+str(version),parent_request_id=r['id'],workflow_version=3)
    next_r=Intake(desk,queue).create(ResearchRequest.model_validate(inp),resolved=value,parent=r['task'])
    with desk.store.connect(write=True) as db:
        db.execute("UPDATE research_interpretations SET status='applied' WHERE request_id=? AND version=?",(r['id'],version))
        for m in updates:
            if m['status'] not in ('applied','linked'):
                body={k:v for k,v in m.items() if k not in ('id','ordinal','status')};body['next_request_id']=next_r['id']
                db.execute("UPDATE research_messages SET status='linked',body=? WHERE id=?",(canonical(body),m['id']))
    if r['task']['status'] in ('running','queued','waiting_user'):
        from ..tasks import Queue
        (queue or Queue(desk)).cancel(r['task_id'])
    return Research(desk).get(next_r['id'])

class UserUpdate(Exception):pass

def ready_update(plane):
    with plane.desk.store.connect() as db:return bool(db.execute("SELECT 1 FROM research_interpretations WHERE request_id=? AND status='ready'",(plane.request['id'],)).fetchone())

def apply_updates(plane):
    if not ready_update(plane):return False
    with plane.desk.store.connect() as db:
        row=db.execute("SELECT * FROM research_interpretations WHERE request_id=? AND status='ready' ORDER BY version DESC LIMIT 1",(plane.request['id'],)).fetchone()
        r=raw_request(db,plane.request['id']);body=json.loads(row['body']);updates=[m for m in messages(db,r['id']) if m['ordinal']<=body['through_ordinal']]
    value=body['interpretation']
    if value['clarification']:
        plane.state['questions']=[value['clarification']]
        with plane.desk.store.connect(write=True) as db:db.execute("UPDATE research_interpretations SET status='clarification' WHERE request_id=? AND version=?",(r['id'],row['version']))
        plane.checkpoint({'research':plane.state,'stage':'clarification_requested'})
        return True
    inp=Intake.normalized_input(r,value,updates)
    old_ids=sorted(s['company_id'] for s in plane.input.get('scope',{}).get('subjects',[]))
    new_ids=sorted(s['company_id'] for s in inp['scope']['subjects'])
    if old_ids!=new_ids or inp.get('as_of')!=plane.input.get('as_of') or (plane.frozen and inp['period']!=plane.input['period']):
        make_successor(plane.desk,r,value,row['version'],updates)
        raise Conflict('研究范围已更新，请查看关联修订')
    added=[sid for sid in inp['source_ids'] if sid not in plane.input['source_ids']]
    with plane.desk.store.connect(write=True) as db:
        plane.fence(db)
        r['input']=inp
        db.execute('UPDATE research_requests SET body=? WHERE id=?',(canonical({k:v for k,v in r.items() if k!='task'}),r['id']))
    plane.update_pending=False
    plane.input=inp;plane.request={k:v for k,v in r.items() if k!='task'};plane.state['questions']=[]
    if plane.frozen:
        with plane.desk.store.connect() as db:snap=plane.desk._snapshot(db,plane.frozen['snapshot'])
        for sid in added:
            doc=plane.desk.document(sid)
            if doc.available_at>snap['as_of']:
                if inp.get('as_of') or inp.get('snapshot'):raise ValueError('补充资料晚于固定截止时间')
                snap['as_of']=max(utcnow(),doc.available_at)
            snap['sources'][sid]=doc.digest
        plane._freeze(snap,plane.frozen['issues'])
    else:plane.prepare()
    for question in value['questions']:
        key='request_'+digest(question)[:12]
        from .contracts import Requirement
        plane.state.setdefault('requirements',{}).setdefault(key,Requirement(id=key,question=question,reason='用户补充').model_dump())
    quality=plane.state.setdefault('quality',{})
    quality.setdefault('reviews',[])
    quality.update(phase='research',seen=[],alternatives=[],next_prompt='用户补充已经纳入输入，重新读取 context。落实以下问题并保留有效证据、引用与原结论编号：'+canonical(value))
    plane.task['request']['parameters']['question']=inp['question']
    plane.checkpoint({'research':plane.state,'stage':'investigating'})
    with plane.desk.store.connect(write=True) as db:
        plane.fence(db)
        db.execute("UPDATE research_interpretations SET status='applied' WHERE request_id=? AND version=?",(r['id'],row['version']))
        db.execute("UPDATE research_messages SET status='applied' WHERE request_id=? AND ordinal<=? AND status IN ('ready','received')",(r['id'],body['through_ordinal']))
    plane.trace.emit('input.updated',data={'version':row['version'],'message_count':len(updates)})
    return True

from __future__ import annotations
import json, logging, threading, time
from contextlib import contextmanager
from datetime import datetime
from .contracts import TraceSpan, TraceView, TraceSummary
from ...contracts import utcnow
from ...storage import canonical, digest

SCHEMA = '''
CREATE TABLE IF NOT EXISTS trace_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, event_id TEXT NOT NULL,
 source TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT, received_at TEXT NOT NULL,
 span_id TEXT, content_ref TEXT, data TEXT NOT NULL, UNIQUE(task_id,event_id));
CREATE INDEX IF NOT EXISTS trace_events_task ON trace_events(task_id,seq);
CREATE TABLE IF NOT EXISTS trace_spans(task_id TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(task_id,id));
CREATE TABLE IF NOT EXISTS trace_content(hash TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trace_cursors(task_id TEXT, stream TEXT, position INTEGER NOT NULL, identity TEXT NOT NULL, PRIMARY KEY(task_id,stream));
CREATE TABLE IF NOT EXISTS trace_meta(task_id TEXT, key TEXT, body TEXT NOT NULL, PRIMARY KEY(task_id,key));
CREATE TABLE IF NOT EXISTS trace_outbox(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL, next_at REAL NOT NULL, attempts INTEGER NOT NULL, body TEXT NOT NULL);
'''

class Trace:
    def __init__(self, desk, task_id):
        self.desk, self.task_id = desk, task_id
        # Short transactions; no network or model work while holding the writer.
        with desk.store.connect(write=True) as db: db.executescript(SCHEMA)

    def meta(self, key, default=None):
        with self.desk.store.connect() as db:
            row=db.execute('SELECT body FROM trace_meta WHERE task_id=? AND key=?',(self.task_id,key)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self,key,value):
        with self.desk.store.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO trace_meta VALUES(?,?,?)',(self.task_id,key,canonical(value)))

    def emit(self, kind, *, event_id=None, source='controller', span_id=None, occurred_at=None, data=None, content=None):
        data=data or {}; event_id=event_id or f'{kind}:{time.time_ns()}:{threading.get_ident()}'
        with self.desk.store.connect(write=True) as db:
            old=db.execute('SELECT seq FROM trace_events WHERE task_id=? AND event_id=?',(self.task_id,event_id)).fetchone()
            if old:return old[0]
            ref=None
            if content is not None:
                body=canonical(content);ref=digest(content)
                db.execute('INSERT OR IGNORE INTO trace_content VALUES(?,?)',(ref,body))
            if kind=='span' and data.get('status') and data.get('status')!='interrupted' and source!='history':
                prior=db.execute('SELECT body FROM trace_spans WHERE task_id=? AND id=?',(self.task_id,span_id)).fetchone()
                if prior and json.loads(prior[0]).get('status')=='interrupted':
                    data={**data,'status':'interrupted','metadata':{**data.get('metadata',{}),'late_reported_status':data['status']}}
            cursor=db.execute('INSERT INTO trace_events(task_id,event_id,source,kind,occurred_at,received_at,span_id,content_ref,data) VALUES(?,?,?,?,?,?,?,?,?)',
                (self.task_id,event_id,source,kind,occurred_at,utcnow(),span_id,ref,canonical(data)))
            seq=cursor.lastrowid
            if kind=='span':
                row=db.execute('SELECT body FROM trace_spans WHERE task_id=? AND id=?',(self.task_id,span_id)).fetchone()
                span=json.loads(row[0]) if row else {'id':span_id,'first_seq':seq}
                if 'metadata' in data:data={**data,'metadata':{**span.get('metadata',{}),**data['metadata']}}
                span.update(data,last_seq=seq)
                # Validation also prevents accidental content leaking into the summary projection.
                span=TraceSpan.model_validate(span).model_dump()
                db.execute('INSERT OR REPLACE INTO trace_spans VALUES(?,?,?)',(self.task_id,span_id,canonical(span)))
            return seq

    def content(self,value):
        body=canonical(value);ref=digest(value)
        with self.desk.store.connect(write=True) as db:db.execute('INSERT OR IGNORE INTO trace_content VALUES(?,?)',(ref,body))
        return ref

    def span(self,id,**patch):return self.emit('span',span_id=id,occurred_at=patch.get('ended_at') or patch.get('started_at') or utcnow(),data=patch)
    def link(self,source,target,kind='sequence',label=''):
        key=digest([source,target,kind])[:24]
        return self.emit('link',event_id='link:'+key,data={'id':key,'source':source,'target':target,'kind':kind,'label':label})

    def gap(self,code,detail):
        self.emit('gap',event_id='gap:'+code,data={'code':code,'message':detail})

    @contextmanager
    def segment(self,id,name,kind,parent_id='root',executor='controller',**meta):
        started=time.monotonic()
        self.span(id,name=name,kind=kind,parent_id=parent_id,executor=executor,started_at=utcnow(),timing='measured',**meta)
        try:yield id
        except BaseException as e:
            self.span(id,status='interrupted' if type(e).__name__ in ('Conflict','TimeoutError') else 'failed',ended_at=utcnow(),duration_ms=(time.monotonic()-started)*1000,error_ref=self.content({'type':type(e).__name__,'message':str(e)}))
            raise
        else:self.span(id,status='completed',ended_at=utcnow(),duration_ms=(time.monotonic()-started)*1000)

    def interrupt_children(self,parent_id):
        with self.desk.store.connect() as db:rows=db.execute('SELECT body FROM trace_spans WHERE task_id=?',(self.task_id,)).fetchall()
        for row in rows:
            span=json.loads(row[0])
            if span['parent_id']==parent_id and span['status']=='running':self.span(span['id'],status='interrupted',ended_at=utcnow(),metadata={'end_observed_on_recovery':True})

    def observe_task(self,task):
        state={'status':task['status'],'stage':task.get('stage'),'active_seconds':task.get('research',{}).get('active_seconds'),
               'tool_calls':task.get('research',{}).get('tool_calls'),'updated_at':task.get('updated_at') or utcnow()}
        previous=self.meta('task_state',{})
        if {k:v for k,v in state.items() if k!='updated_at'}=={k:v for k,v in previous.items() if k!='updated_at'}:return
        self.emit('task',occurred_at=state['updated_at'],data=state);self.set_meta('task_state',state)
        if task['status'] in ('completed','failed','cancelled') or task.get('stage')=='interrupted':
            with self.desk.store.connect() as db:rows=db.execute('SELECT body FROM trace_spans WHERE task_id=?',(self.task_id,)).fetchall()
            for row in rows:
                s=json.loads(row[0])
                if s['status']=='running':self.span(s['id'],status='interrupted',ended_at=state['updated_at'])

    def events(self,after=0,through=None,limit=1000):
        with self.desk.store.connect() as db:
            rows=db.execute('SELECT * FROM trace_events WHERE task_id=? AND seq>? AND (? IS NULL OR seq<=?) ORDER BY seq LIMIT ?',
                 (self.task_id,after,through,through,limit)).fetchall()
        return [{**{k:r[k] for k in r.keys() if k!='task_id'},'data':json.loads(r['data'])} for r in rows]

    def all_events(self,through=None):
        result=[];cursor=0
        while True:
            page=self.events(cursor,through)
            if not page:break
            result.extend(page);cursor=page[-1]['seq']
        return result

    def view(self,request,at_seq=None):
        events=self.all_events();latest=events[-1]['seq'] if events else 0
        if at_seq is not None:events=[e for e in events if e['seq']<=at_seq]
        spans={};links={};plans=[];gaps=[];task={};reconstructed=False
        for e in events:
            data=e['data']
            if e['kind']=='span':
                s=spans.setdefault(e['span_id'],{'id':e['span_id'],'first_seq':e['seq']});s.update({**data,'metadata':{**s.get('metadata',{}),**data.get('metadata',{})}},last_seq=e['seq'])
            elif e['kind']=='link':links[data['id']]=data
            elif e['kind']=='plan':plans.append({**data,'seq':e['seq'],'content_ref':e['content_ref'],'occurred_at':e['occurred_at']})
            elif e['kind']=='gap':gaps.append(data['message'])
            elif e['kind']=='task':task=data
            elif e['kind']=='history':reconstructed=True
        items=[TraceSpan.model_validate(s).model_dump() for s in spans.values()]
        tools=[s for s in items if s['kind']=='tool'];measured=[s for s in tools if s['duration_ms'] is not None]
        tokens={}
        for s in items:
            if s['kind']=='agent':
                reported=s['metadata'].get('usage') or []
                if isinstance(reported,dict):reported=[reported]
                for usage in reported:
                    for key,value in (usage or {}).items():
                        if isinstance(value,int):tokens[key]=tokens.get(key,0)+value
        # Waiting and queue are disjoint task-state intervals; they never enter active execution totals.
        periods={'queue_seconds':0.,'waiting_seconds':0.};transitions=[e for e in events if e['kind']=='task' and e['occurred_at']]
        def seconds(a,b):
            try:return max(0.,(datetime.fromisoformat(b.replace('Z','+00:00'))-datetime.fromisoformat(a.replace('Z','+00:00'))).total_seconds())
            except (ValueError,TypeError):return 0.
        for a,b in zip(transitions,transitions[1:]):
            key={'queued':'queue_seconds','waiting_user':'waiting_seconds'}.get(a['data']['status'])
            if key:periods[key]+=seconds(a['occurred_at'],b['occurred_at'])
        if transitions and at_seq is None:
            key={'queued':'queue_seconds','waiting_user':'waiting_seconds'}.get(transitions[-1]['data']['status'])
            if key:periods[key]+=seconds(transitions[-1]['occurred_at'],utcnow())
        for s in items:s['tool_count']=sum(1 for child in tools if child['parent_id']==s['id']) if s['kind']!='tool' else 0
        sync=self.meta('sync',{'mode':'off','status':'disabled'})
        if len(measured)<len(tools):gaps.append(f'{len(tools)-len(measured)} 次工具调用没有独立耗时，未根据相邻日志推算')
        if reconstructed:periods={'queue_seconds':None,'waiting_seconds':None}
        summary=TraceSummary(active_seconds=task.get('active_seconds'),**periods,tool_seconds=sum(s['duration_ms'] for s in measured)/1000 if measured else None,
             measured_tools=len(measured),tool_count=len(tools),budget_tool_count=task.get('tool_calls'),tokens=tokens,gaps=list(dict.fromkeys(gaps)),
             capture='partial' if gaps else 'observed',reconstructed=reconstructed,sync=sync)
        return TraceView(request_id=request['id'],task_id=self.task_id,seq=events[-1]['seq'] if events else 0,latest_seq=latest,
             task_status=task.get('status','unobserved'),spans=items,links=list(links.values()),plans=plans,summary=summary).model_dump()

    def detail(self,span_id,at_seq=None):
        events=self.all_events(at_seq);span=None;refs=set()
        for e in events:
            if e['span_id']==span_id:
                if e['kind']=='span':
                    if span is None:span={'id':span_id,'first_seq':e['seq']}
                    span.update({**e['data'],'metadata':{**span.get('metadata',{}),**e['data'].get('metadata',{})}},last_seq=e['seq'])
                if e['content_ref']:refs.add(e['content_ref'])
        if span is None:raise KeyError('执行节点不存在于所选事件位置')
        refs.update(span.get(k) for k in ('input_ref','output_ref','error_ref') if span.get(k))
        with self.desk.store.connect() as db:
            contents={ref:json.loads(row[0]) for ref in refs if (row:=db.execute('SELECT body FROM trace_content WHERE hash=?',(ref,)).fetchone())}
        return {'span':TraceSpan.model_validate(span).model_dump(),'events':[e for e in events if e['span_id']==span_id], 'contents':contents}

class SafeTrace:
    """Observation failure is reported, but never changes a research result or budget."""
    def __init__(self,desk,task_id):self.desk=desk;self.task_id=task_id;self.failure=None
    def __getattr__(self,name):
        def call(*args,**kwargs):
            try:return getattr(Trace(self.desk,self.task_id),name)(*args,**kwargs)
            except Exception as e:
                self.failure=type(e).__name__
                logging.getLogger(__name__).exception('Trace capture failed for %s',self.task_id)
                try:
                    path=self.desk.root/'trace-capture-failures';path.mkdir(exist_ok=True)
                    (path/self.task_id).write_text(canonical({'at':utcnow(),'type':self.failure}))
                except Exception:pass
                return None
        return call

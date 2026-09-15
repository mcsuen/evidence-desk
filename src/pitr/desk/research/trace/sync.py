"""Explicit, opt-in LangSmith export. No SDK client exists when synchronization is off."""
import json, os, re, tempfile, threading, time, uuid
from urllib.parse import urlparse
from datetime import datetime, timezone
from .contracts import TraceSettings
from .store import Trace
from ...storage import canonical,digest,Conflict
from ...contracts import utcnow

SECRET=re.compile(r'(authorization|api[_-]?key|password|secret|credential|capability|cookie|^env$|^headers$|^(slack_app|slack_bot|access|refresh|id)_token$)',re.I)
TOKEN=re.compile(r'(?i)\bBearer\s+[^\s"\',}]+|\b(?:sk-[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+)')
LOCK=threading.RLock()

def redact(value,secrets=()):
    if isinstance(value,dict):return {k:('[REDACTED]' if SECRET.search(k) else redact(v,secrets)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v,secrets) for v in value]
    if isinstance(value,str):
        value=TOKEN.sub('[REDACTED]',value)
        try:
            structured=json.loads(value)
            if isinstance(structured,(dict,list)):return canonical(redact(structured,secrets))
        except (ValueError,TypeError):pass
        for secret in secrets:
            if secret and len(secret)>=6:value=value.replace(secret,'[REDACTED]')
    return value

class Sync:
    def __init__(self,desk):
        self.desk=desk;self.path=desk.root/'private'/'trace-settings.json';self.stop_event=threading.Event();self.thread=None
    def settings(self):
        with LOCK:return json.loads(self.path.read_text()) if self.path.exists() else TraceSettings().model_dump()
    def public(self):
        s=self.settings();s['api_key']=bool(s.get('api_key'));return s
    def save(self,settings:TraceSettings):
        if settings.mode!='off':
            parsed=urlparse(settings.endpoint)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('LangSmith 地址必须是不含凭据的 HTTPS 服务地址')
            if not settings.project.strip():raise ValueError('请设置 LangSmith 项目')
        with LOCK:
            data=settings.model_dump();prior=self.settings()
            if not data.get('api_key'):data['api_key']=prior.get('api_key')
            if prior['mode']=='off' and data['mode']=='content':raise ValueError('首次启用请先选择仅元数据；内容模式需另外选择并预览')
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd,temp=tempfile.mkstemp(dir=self.path.parent,prefix='.trace-settings-')
            with os.fdopen(fd,'w') as f:json.dump(data,f)
            os.replace(temp,self.path);self.path.chmod(0o600)
        return self.public()
    def secrets(self):
        values=[]
        for path in (self.path,self.desk.root/'private'/'settings.json'):
            try:
                data=json.loads(path.read_text())
                values.extend(v for k,v in data.items() if isinstance(v,str) and (SECRET.search(k) or 'token' in k))
            except (OSError,ValueError):pass
        return values
    def payload(self,trace,request):
        mode=self.settings()['mode']
        if mode=='off':raise ValueError('LangSmith 同步已关闭；本机记录不会外发')
        view=trace.view(request);spans=view['spans'];ids={s['id'] for s in spans}
        scope=digest(str(self.desk.store.path.resolve()));root_id=str(uuid.uuid5(uuid.NAMESPACE_URL,scope+trace.task_id+self.settings()['endpoint']+self.settings()['project']))
        def external(sid):return str(uuid.uuid5(uuid.UUID(root_id),sid))
        def safe_time(v):return v or request['created_at']
        root={'id':root_id,'name':'research','run_type':'chain','inputs':{},'outputs':{},'parent_run_id':None,'trace_id':root_id,
            'start_time':request['created_at'],'end_time':request['task'].get('finished_at'),
            'extra':{'metadata':{'trace_version':view['version'],'status':view['task_status'],'active_seconds':view['summary']['active_seconds'],
              'tool_count':view['summary']['tool_count'],'tokens':view['summary']['tokens'],'capture':view['summary']['capture']}}}
        records=[root];mapping={s['id']:external(s['id']) for s in spans}
        for s in spans:
            item={'id':external(s['id']),'name':s['kind'],'run_type':'tool' if s['kind']=='tool' else 'chain','trace_id':root_id,
                  'parent_run_id':external(s['parent_id']) if s['parent_id'] in ids else root_id,
                  'start_time':safe_time(s['started_at'] or s['ended_at']),'end_time':s['ended_at'],'inputs':{},'outputs':{},
                  'extra':{'metadata':{k:s[k] for k in ('kind','status','duration_ms','timing','attempt','ordinal','input_version','tool_count','issue_count')}}}
            # External SDK needs a timestamp even where old spans do not have one. Mark its use explicitly.
            item['extra']['metadata']['timestamp_placeholder']=not bool(s['started_at'])
            if mode=='content':
                detail=trace.detail(s['id']);item['name']=s['name']
                item['inputs']={'value':detail['contents'].get(s['input_ref'])}
                item['outputs']={'value':detail['contents'].get(s['output_ref']),'error':detail['contents'].get(s['error_ref']),
                    'artifacts':s['artifact_refs'],'events':detail['events'],'content':detail['contents']}
            records.append(item)
        if mode=='content':root['inputs']={'request':request['input']}
        # Parent-first order and explicit dotted_order for independent nested records.
        by={r['id']:r for r in records};ordered=[]
        def visit(r):
            if r in ordered:return
            if r['parent_run_id']:visit(by[r['parent_run_id']])
            stamp=datetime.fromisoformat(r['start_time'].replace('Z','+00:00')).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+r['id']
            r['dotted_order']=(by[r['parent_run_id']]['dotted_order']+'.' if r['parent_run_id'] else '')+stamp
            ordered.append(r)
        for r in records:visit(r)
        payload=redact({'version':'langsmith-export.1','mode':mode,'seq':view['seq'],'records':ordered,'mapping':mapping},self.secrets())
        return payload
    def enqueue(self,trace,request,preview_hash=None,preview=False):
        payload=self.payload(trace,request);fingerprint=digest(payload)
        if preview:return {'hash':fingerprint,'payload':payload,'notice':'仅预览，尚未发送；不包含原始 PDF'}
        settings=self.settings()
        if settings['mode']=='content' and preview_hash!=fingerprint:raise Conflict('内容或事件位置已变化，请先查看本次发送预览')
        if not settings.get('api_key'):raise ValueError('请先在本机配置 LangSmith API Key')
        target={'endpoint':settings['endpoint'],'project':settings['project']}
        key=digest([trace.task_id,fingerprint,target])
        body={'payload':payload,'target':target,'preview_hash':fingerprint,'created_at':utcnow()}
        with self.desk.store.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO trace_outbox VALUES(?,?,?,?,?,?)',(key,trace.task_id,'pending',0,0,canonical(body)))
            current=db.execute('SELECT status FROM trace_outbox WHERE id=?',(key,)).fetchone()[0]
            if current=='retry':db.execute('UPDATE trace_outbox SET next_at=0 WHERE id=?',(key,))
        if current!='sent':trace.set_meta('sync',{'mode':payload['mode'],'status':current,'job_id':key,'seq':payload['seq']})
        return {'id':key,'status':current}
    def process_one(self,client_factory=None):
        settings=self.settings()
        if settings['mode']=='off':return False
        with self.desk.store.connect(write=True) as db:
            row=db.execute("SELECT * FROM trace_outbox WHERE status IN ('pending','retry','sending') AND next_at<=? ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
            if not row:return False
            row=dict(row);body=json.loads(row['body']);attempt=row['attempts']+1
            db.execute("UPDATE trace_outbox SET status='sending',attempts=?,next_at=? WHERE id=?",(attempt,time.time()+120,row['id']))
        trace=Trace(self.desk,row['task_id']);payload=body['payload']
        try:
            if body['target']!={'endpoint':settings['endpoint'],'project':settings['project']} or payload['mode']!=settings['mode']:
                raise ValueError('configuration_changed')
            if client_factory is None:
                from langsmith import Client
                client_factory=Client
            client=client_factory(api_url=settings['endpoint'],api_key=settings['api_key'],auto_batch_tracing=False,timeout_ms=15000)
            urls={}
            for item in payload['records']:
                try:run=client.read_run(item['id'])
                except Exception as e:
                    # Only an explicit 404 means it is safe to attempt a create.
                    if type(e).__name__!='LangSmithNotFoundError':raise
                    run=None
                if run is None:
                    client.create_run(project_name=settings['project'],**item)
                else:
                    client.update_run(item['id'],end_time=item['end_time'],inputs=item['inputs'],outputs=item['outputs'],extra=item['extra'])
                # URL comes from SDK / server, never a guessed tenant path.
                run=client.read_run(item['id']);urls[item['id']]=client.get_run_url(run=run,project_name=settings['project'])
            body['urls']=urls;body['finished_at']=utcnow()
            with self.desk.store.connect(write=True) as db:db.execute("UPDATE trace_outbox SET status='sent',body=? WHERE id=?",(canonical(body),row['id']))
            trace.set_meta('sync',{'mode':payload['mode'],'status':'sent','job_id':row['id'],'seq':payload['seq'],
                'url':urls.get(payload['records'][0]['id']),'links':{sid:urls.get(eid) for sid,eid in payload['mapping'].items()}})
        except Exception as error:
            # Never put SDK errors (which may include URLs, auth or user data) into public diagnostics.
            reason='configuration_changed' if str(error)=='configuration_changed' else type(error).__name__
            status='blocked' if reason=='configuration_changed' else 'retry'
            body['failure_type']=reason
            with self.desk.store.connect(write=True) as db:db.execute('UPDATE trace_outbox SET status=?,next_at=?,body=? WHERE id=?',(status,time.time()+min(3600,2**min(attempt,10)),canonical(body),row['id']))
            trace.set_meta('sync',{'mode':payload['mode'],'status':status,'job_id':row['id'],'reason':reason,'attempts':attempt})
        return True
    def start(self):
        def work():
            while not self.stop_event.wait(2):
                try:self.process_one()
                except Exception:pass
        self.thread=threading.Thread(target=work,daemon=True,name='trace-sync');self.thread.start()
    def stop(self):self.stop_event.set()

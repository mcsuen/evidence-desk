"""Durable research turns with a fenced loopback MCP broker and OS isolation."""
from __future__ import annotations
import os,json,threading,time,secrets
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from contextlib import contextmanager
from .tools import ToolPlane,tool_schemas
from ..contracts import utcnow
from ..storage import canonical,digest



def runtime_root(desk):
    # Must be outside production source/database and outside the frozen experiment lab.
    base=Path(os.environ.get('PITR_RESEARCH_RUNTIME',str(Path.home()/'.pitr-research-runtime'))).resolve()
    # A copied database retains task IDs. It must never reuse the original
    # controller's CLI session, files, process registry or capability endpoint.
    return base/('desk_'+digest(str(desk.store.path.resolve()))[:20])


@contextmanager
def broker(plane):
    token=secrets.token_urlsafe(32);revoked=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if revoked.is_set() or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                self.send_error(403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1_000_000:raise ValueError('工具请求过大')
                raw=self.rfile.read(length)
                if self.path.startswith('/otel/'):
                    from .trace.telemetry import receive
                    try:
                        receive(plane.trace,plane.trace_attempt,raw,self.headers.get('Content-Type',''),self.path,self.headers.get('Content-Encoding',''))
                    except Exception:
                        plane.trace.gap('otel-receive','本机遥测解析失败，CLI 和工具账本仍独立保留')
                    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{}');return
                payload=json.loads(raw);plane.fence()
                if payload.get('catalog'):result={'tools':tool_schemas()}
                else:
                    # Result and call identity must be captured under the same lock:
                    # concurrent MCP requests must never inherit the next call's ID.
                    with plane.execution_lock:
                        try:value=plane.call(payload['name'],payload.get('arguments',{}))
                        except Exception as error:value={'error':str(error)}
                        result={'value':value,'_trace':dict(plane.last_trace_call) if plane.last_trace_call else None}
            except Exception as e:result={'error':str(e),'value':{'error':str(e)},'_trace':getattr(plane,'last_trace_call',None)}
            data=canonical(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server.server_port,token
    finally:revoked.set();server.shutdown();server.server_close();thread.join(2)


def run(desk,task,owner,checkpoint):
    plane=ToolPlane(desk,task,owner,checkpoint)
    from .trace import VERSION
    plane.state['trace_version']=VERSION
    plane.trace.observe_task(task)
    plane.trace.emit('boundary',data={'message':'记录可观察执行与整轮 token；内部上下文及推理不可见，费用未知'})
    # Recover persisted elapsed time conservatively; never reset counters on a new lease.
    with desk.store.connect() as db:
        interrupted=[json.loads(r['body']) for r in db.execute('SELECT body FROM research_attempts WHERE task_id=?',(task['id'],)) if json.loads(r['body'])['status']=='running']
    if interrupted or task.get('recovered_lease'):
        for prior in interrupted:
            prior.update(status='interrupted',recovered_at=utcnow())
            plane.trace.span(f'attempt:{prior["ordinal"]}',status='interrupted',ended_at=prior['recovered_at'],metadata={'end_observed_on_recovery':True})
            plane.trace.interrupt_children(f'attempt:{prior["ordinal"]}')
            with desk.store.connect(write=True) as db:db.execute('UPDATE research_attempts SET body=? WHERE task_id=? AND ordinal=?',(canonical(prior),task['id'],prior['ordinal']))
        plane.state['active_seconds']+=1.5 # heartbeat interval upper bound before abrupt exit
        plane.state['recoveries']+=1
        plane.state['recovery_note']='恢复任务检查点与已保存证据；原生会话内部进度以精确 session ID 续接结果为准'
        transition='recovery:lease:'+str(task.get('attempts',1))
        plane.trace.span(transition,name='中断后恢复执行',kind='recovery',parent_id='root',status='completed',ended_at=utcnow(),metadata={'session_id':plane.state.get('session_id')})
        if interrupted:plane.trace.link(f'attempt:{interrupted[-1]["ordinal"]}',transition,'recovery')
        plane.state['trace_next_link']={'id':transition,'kind':'recovery'}
    from .intake import apply_updates
    apply_updates(plane)
    if plane.state.get('questions'):return {'status':'waiting_user','questions':plane.state['questions']}
    from pitr.agent_runtime.research import BridgeNative
    factory=BridgeNative
    native=factory(plane)
    plane.clock_started=time.monotonic();plane.clock_base=plane.state['active_seconds']
    prep_started=time.monotonic();preparation_id='preparation:'+str(task.get('attempts',1));plane.trace_parent=preparation_id
    plane.trace.span(preparation_id,name='资料准备',kind='preparation',parent_id='root',started_at=utcnow(),timing='measured')
    prepare_budgeted(plane)
    plane.trace.span(preparation_id,status='completed',ended_at=utcnow(),duration_ms=(time.monotonic()-prep_started)*1000,
        input_version=plane.state['input_version'],output_ref=plane.trace.content(plane.frozen))
    plane.charge();checkpoint({'research':plane.state})
    from .quality import run_quality
    return run_quality(plane,native,factory(plane,role='reviewer'))

def re_missing_session(text):
    import re
    return bool(re.search(r'(session|thread).{0,60}(not found|does not exist|unknown)',text,re.I))


def prepare_budgeted(plane):
    """Network preparation cannot hold a heavy slot beyond the request deadline."""
    done=threading.Event();errors=[]
    def prepare():
        try:plane.prepare()
        except BaseException as e:errors.append(e)
        finally:done.set()
    thread=threading.Thread(target=prepare,daemon=True,name='research-input-preparation');thread.start()
    while not done.wait(.25):
        with plane.lock:
            plane.fence();plane.checkpoint({'research':plane.state,'stage':'preparing_sources'})
    if errors:raise errors[0]

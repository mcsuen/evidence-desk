"""Trace protocol, recovery, privacy and honest history regressions (no model truth labels)."""
import json,time,io,zipfile,hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from research_fixtures import Research
from pitr.desk.research.contracts import ResearchRequest
from pitr.desk.research.trace.store import Trace,SafeTrace
from pitr.desk.research.trace.history import ensure_history
from pitr.desk.research.trace.ingest import Tail
from pitr.desk.research.trace.sync import Sync,redact
from pitr.desk.research.trace.contracts import TraceSettings
from pitr.desk.storage import canonical,Conflict
from pitr.desk.api import create_app

@pytest.fixture
def case(tmp_path):
 d=Desk(tmp_path/'desk');q=Queue(d);r=Research(d,q).create(ResearchRequest(operation_id='trace-test',company='PDD',period='2025Q2',intent='investigation',question='Private PDD question 123'))
 return d,q,r,Trace(d,r['task_id'])

def test_append_idempotence_and_replay(case):
 d,q,r,t=case
 first=t.emit('span',event_id='a',span_id='a',data={'name':'same','kind':'tool','ordinal':1,'started_at':'2025-01-01T00:00:00Z'})
 assert t.emit('span',event_id='a',span_id='a',data={'name':'different','kind':'tool'})==first
 t.span('a',status='completed',duration_ms=123)
 t.emit('span',event_id='b',span_id='b',occurred_at='2024-01-01T00:00:00Z',data={'name':'same','kind':'tool','ordinal':2})
 assert len(t.view(r)['spans'])==2
 assert t.view(r,first)['spans'][0]['status']=='running'
 assert t.view(r)['summary']['tool_count']==2
 assert t.view(r)['summary']['tool_seconds']==.123
 assert t.events(first)[0]['seq']>first
 with d.store.connect() as db:assert db.execute('select count(*) from trace_spans').fetchone()[0]==2

def test_tail_partial_lines_duplicate_and_unknown(case,tmp_path):
 d,q,r,t=case;path=tmp_path/'events.jsonl';path.write_bytes(b'{"type":"thread.started","thread_id":"s"}\n{"type":"new')
 tail=Tail(t,path,1);assert len(tail.poll())==1;assert tail.session_id=='s';assert tail.poll()==[]
 with path.open('ab') as f:f.write(b'.unknown"}\n')
 assert len(tail.poll())==1
 new=Tail(t,path,1);assert new.poll()==[]
 assert len([e for e in t.all_events() if e['kind'].startswith('cli.')])==2
 assert any('未支持' in g for g in t.view(r)['summary']['gaps'])

def test_cli_tools_do_not_count_twice_and_plans_do_not_execute(case,tmp_path):
 _,_,r,t=case;t.span('attempt:1',name='agent',kind='agent')
 t.span('tool:1',name='search',kind='tool',parent_id='attempt:1',ordinal=1)
 tail=Tail(t,tmp_path/'unused',1)
 for typ in ('started','completed'):
  tail.accept({'type':'item.'+typ,'item':{'type':'mcp_tool_call','id':'abc','result':{'_meta':{'pitr.trace':{'task_id':r['task_id'],'span_id':'tool:1'}}}}},typ)
 tail.accept({'type':'item.updated','item':{'type':'todo_list','id':'p','items':[{'text':'read','completed':False},{'text':'calculate','completed':False}]}},'p1')
 tail.accept({'type':'item.updated','item':{'type':'todo_list','id':'p','items':[{'text':'read','completed':True}]}},'p2')
 view=t.view(r);assert view['summary']['tool_count']==1;assert len(view['plans'])==2
 assert len(view['plans'][0]['items'])==2;assert len(view['plans'][1]['items'])==1
 assert len(t.detail('tool:1')['events'])==3
 assert not any(s['kind']=='plan' for s in view['spans'])

def test_parent_duration_and_tokens_not_double_counted(case):
 _,_,r,t=case
 t.span('attempt:1',name='Agent',kind='agent',duration_ms=1000,metadata={'usage':[{'input_tokens':100,'cached_input_tokens':70,'output_tokens':10}]})
 for i in range(2):t.span('tool:'+str(i),name='read',kind='tool',duration_ms=200,parent_id='attempt:1')
 t.emit('otel.log',data={'usage':{'input_tokens':100}})
 view=t.view(r);assert view['summary']['tool_seconds']==.4;assert view['summary']['tokens']['input_tokens']==100
 assert view['spans'][0]['tool_count']==2;assert view['summary']['cost'] is None

def test_cancel_closes_open_spans(case):
 _,q,r,t=case;q.claim();t.span('attempt:1',name='Agent',kind='agent',started_at='2025-01-01T00:00:00Z')
 q.cancel(r['task_id']);view=t.view(r)
 assert view['task_status']=='cancelled';assert view['spans'][0]['status']=='interrupted'
 assert view['spans'][0]['duration_ms'] is None

def test_capture_failure_does_not_change_task(case,monkeypatch):
 d,_,r,t=case
 monkeypatch.setattr(Trace,'emit',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
 safe=SafeTrace(d,r['task_id']);assert safe.span('x',name='x',kind='tool') is None
 assert (d.root/'trace-capture-failures'/r['task_id']).exists()
 assert Research(d).get(r['id'])['task']['status']=='queued'


def test_sync_disabled_metadata_privacy_and_stable_identity(case):
 d,_,r,t=case;s=Sync(d)
 t.span('a',name='PDD sensitive q',kind='agent',input_ref=t.content({'prompt':'Private PDD'}),error_ref=t.content('secret free text'),metadata={'company':'PDD','usage':[{'input_tokens':123}]})
 assert s.process_one(client_factory=lambda **k:pytest.fail('network')) is False
 with pytest.raises(ValueError):s.payload(t,r)
 with pytest.raises(ValueError):s.save(TraceSettings(mode='content',api_key='secret'))
 s.save(TraceSettings(mode='metadata',api_key='secret-key-123'))
 payload=s.payload(t,r);body=canonical(payload)
 assert 'PDD' not in body and 'Private' not in body and 'secret' not in body and 'prompt' not in body
 assert payload['records'][1]['inputs']=={}
 assert s.payload(t,r)['records'][1]['id']==payload['records'][1]['id']
 a=s.enqueue(t,r);b=s.enqueue(t,r);assert a['id']==b['id']
 with d.store.connect() as db:assert db.execute('select count(*) from trace_outbox').fetchone()[0]==1
 # Changing the destination must create an independent trace, not update another project's runs.
 s.save(TraceSettings(mode='metadata',project='second-project'))
 assert s.payload(t,r)['records'][0]['id']!=payload['records'][0]['id']

def test_content_preview_changes_secret_redaction(case):
 d,_,r,t=case;s=Sync(d);s.save(TraceSettings(mode='metadata',api_key='secret-value'));s.save(TraceSettings(mode='content'))
 t.span('a',name='tool',kind='tool',input_ref=t.content({'authorization':'Bearer abc','api_key':'secret-value','body':'xoxb-123-abcd secret-value'}))
 preview=s.enqueue(t,r,preview=True);assert 'secret-value' not in canonical(preview);assert 'Bearer abc' not in canonical(preview)
 with pytest.raises(Conflict):s.enqueue(t,r)
 t.span('b',name='second',kind='tool')
 with pytest.raises(Conflict):s.enqueue(t,r,preview['hash'])
 preview=s.enqueue(t,r,preview=True);assert s.enqueue(t,r,preview['hash'])['status']=='pending'

def test_outbox_resume_failure_and_metadata_client(case):
 d,_,r,t=case;s=Sync(d);s.save(TraceSettings(mode='metadata',api_key='secret'));t.span('a',name='private',kind='tool');s.enqueue(t,r)
 seen={};calls=[]
 class LangSmithNotFoundError(Exception):pass
 class Client:
  def __init__(self,**kwargs):pass
  def read_run(self,key):
   if key not in seen:raise LangSmithNotFoundError()
   return seen[key]
  def create_run(self,**item):calls.append(item['id']);seen[item['id']]=item
  def update_run(self,key,**kwargs):seen[key].update(kwargs)
  def get_run_url(self,**kwargs):return 'https://smith.langchain.com/example'
 assert s.process_one(client_factory=Client)
 assert t.meta('sync')['status']=='sent';assert len(calls)==2
 assert s.process_one(client_factory=Client) is False
 # Same identities survive a retry after an uncertain response.
 with d.store.connect(write=True) as db:db.execute("update trace_outbox set status='retry',next_at=0")
 assert s.process_one(client_factory=Client);assert len(calls)==2
 with d.store.connect(write=True) as db:db.execute("update trace_outbox set status='retry',next_at=0")
 assert s.process_one(client_factory=lambda **k:(_ for _ in ()).throw(ConnectionError('secret-value')))
 assert t.meta('sync')['reason']=='ConnectionError';assert 'secret-value' not in canonical(t.meta('sync'))
 s.save(TraceSettings(mode='off'));assert s.process_one(client_factory=lambda **k:pytest.fail('network')) is False

def test_api_lazy_details_replay_and_export(tmp_path):
 app=create_app(tmp_path/'api',worker=False);d=app.state.desk
 with TestClient(app) as client:
  r=client.post('/api/desk/research/requests',json={'operation_id':'api-trace','company':'PDD','period':'2025Q2','intent':'investigation','question':'Check changes'}).json()
  t=Trace(d,r['task_id']);seq=t.span('a',name='read',kind='tool',input_ref=t.content({'authorization':'Bearer abc','metric':'revenue'}))
  t.span('a',status='completed',duration_ms=17)
  root=f"/api/desk/research/requests/{r['id']}/trace"
  view=client.get(root).json();assert view['spans'][0]['input_ref'];assert 'revenue' not in canonical(view)
  detail=client.get(root+'/spans/a').json();assert 'revenue' in canonical(detail)
  assert client.get(root,params={'at_seq':seq}).json()['spans'][0]['status']=='running'
  bundle=zipfile.ZipFile(io.BytesIO(client.get(root+'/export').content));manifest=json.loads(bundle.read('manifest.json'))
  for name,hash in manifest['files'].items():assert hashlib.sha256(bundle.read(name)).hexdigest()==hash
  assert b'Bearer abc' not in bundle.read('contents.json')
  assert client.post(root+'/sync',json={}).status_code==422

def test_late_completion_does_not_resurrect_interrupted_span(case):
 _,q,r,t=case;q.claim();t.span('a',name='Agent',kind='agent');q.cancel(r['task_id'])
 t.span('a',status='completed',duration_ms=10,metadata={'usage':[{'input_tokens':7}]})
 v=t.view(r);assert v['spans'][0]['status']=='interrupted';assert v['task_status']=='cancelled'
 assert v['spans'][0]['metadata']['late_reported_status']=='completed'
 assert v['summary']['tokens']['input_tokens']==7

def test_budget_rejection_has_own_identity_and_no_extra_domain_call(tmp_path):
 import runpy
 plane=runpy.run_path('tests/test_native_research.py')['plane'].__wrapped__(tmp_path)
 plane.call('context',{})
 prior=plane.last_trace_call
 plane.input['tool_budget']=2;plane.state['tool_calls']=2
 with pytest.raises(ValueError):plane.call('context',{})
 assert plane.last_trace_call['span_id']!=prior['span_id']
 request=Research(plane.desk).get(plane.task['id']);v=Trace(plane.desk,plane.task['id']).view(request)
 assert len([s for s in v['spans'] if s['kind']=='rejected_tool'])==1
 assert v['summary']['tool_count']==1

def test_duplicate_sent_sync_keeps_sent_status(case):
 d,_,r,t=case;s=Sync(d);s.save(TraceSettings(mode='metadata',api_key='secret'));t.span('a',name='x',kind='tool');job=s.enqueue(t,r)
 with d.store.connect(write=True) as db:db.execute("UPDATE trace_outbox SET status='sent' WHERE id=?",(job['id'],))
 t.set_meta('sync',{'status':'sent','url':'https://smith.langchain.com/verified'})
 assert s.enqueue(t,r)['status']=='sent';assert t.meta('sync')['url'].endswith('verified')

def test_serialized_json_secret_is_redacted():
 raw={'text':json.dumps({'api_key':'a-custom-opaque-key','authorization':'Basic confidential'})}
 assert 'a-custom-opaque-key' not in canonical(redact(raw));assert 'Basic confidential' not in canonical(redact(raw))

def test_quality_validation_has_measured_span_and_artifact_link(tmp_path,monkeypatch):
 import runpy
 from pitr.desk.research import quality
 plane=runpy.run_path('tests/test_native_research.py')['plane'].__wrapped__(tmp_path)
 monkeypatch.setattr(quality,'validate',lambda raw,p:{'status':'needs_review','issues':[{'code':'test_issue'}]})
 report=quality.validate_traced(plane,{'claims':[]})
 saved=quality.persist(plane,{'claims':[]},report,'草稿核验')
 detail=Trace(plane.desk,plane.task['id']).detail(plane.validation_trace)
 span=detail['span']
 assert span['timing']=='measured' and span['duration_ms']>=0
 assert span['status']=='needs_review' and span['issue_count']==1
 assert span['artifact_refs'][0]['version']==saved['artifact_version']
 assert detail['contents'][span['output_ref']]['issues']==report['issues']
 monkeypatch.setattr(quality,'validate',lambda *a:(_ for _ in ()).throw(ValueError('calculation mismatch')))
 with pytest.raises(ValueError):quality.validate_traced(plane,{})
 assert Trace(plane.desk,plane.task['id']).detail(plane.validation_trace)['span']['status']=='failed'

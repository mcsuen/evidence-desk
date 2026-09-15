"""Known regressions and boundary tests; fixtures are not real model evaluations."""
import json,time,dataclasses,hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from pitr.desk.contracts import Document,SourceBlock,Citation,Metric,utcnow
from pitr.desk.storage import canonical,digest,Conflict
from research_fixtures import Research
from pitr.desk.research.contracts import ResearchRequest,ResearchMessage
from pitr.desk.research.tools import ToolPlane
from pitr.desk.research.verify import validate
from pitr.desk.research.report import html_report,png_chart,slack_files
from pitr.desk.api import create_app

@pytest.fixture
def plane(tmp_path):
 d=Desk(tmp_path/'desk');now=utcnow()
 doc=Document(id='source_fixture',company='PDD',title='PDD 2025Q2 disclosed fixture',url='https://investor.pddholdings.com/fixture',digest=digest('fixture'),media_type='text/plain',published_at=now,available_at=now,observed_at=now,origin_group='issuer',blocks=[SourceBlock(id='a',text='Quarter 2025Q2 revenue is RMB 100 million. Prior 2024Q2 revenue was RMB 200 million. Investment timing remains uncertain.')],file_name='fixture.txt')
 doc.digest=hashlib.sha256(doc.blocks[0].text.encode()).hexdigest();(d.files/doc.file_name).write_text(doc.blocks[0].text);d.put_document(doc)
 with d.store.connect(write=True) as db:
  for i,(period,value) in enumerate([('2025Q2',100),('2024Q2',200)]):
   m=Metric(id='obs'+str(i),name='revenue',label='收入',period=period,value=value,unit='RMB_mn',basis='GAAP',frequency='quarter',citation=Citation(source_id=doc.id,block_id='a',quote=doc.blocks[0].text))
   db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',doc.id,canonical(m)))
 q=Queue(d);snap=d.snapshot('PDD',utcnow())[0]
 r=Research(d,q).create(ResearchRequest(operation_id='fixture-request',workflow_version=3,question='核对历史收入变化与持续性',company='PDD',period='2025Q2',intent='investigation',snapshot=snap))
 task=q.claim();p=ToolPlane(d,task,q.owner,lambda u:q.checkpoint(task,u));p.prepare();p.queue=q
 return p

def claim(**kw):
 return {'id':'c','section':'changes','text':'收入变化需要核对。','verdict':'interpretation','evidence':[],
   'counterevidence':[],'calculations':[],'depends_on':[],'chronology':[], 'alternative':'可能是投资发生时点变化。','next_check':'检查后续同口径披露。',**kw}

def draft(*claims):return {'title':'研究测试','claims':list(claims),'gaps':[]}

def test_same_request_and_changed_command(plane):
    req=ResearchRequest(operation_id='fixture-request',question='核对历史收入变化与持续性',company='PDD',period='2025Q2',intent='investigation',snapshot=plane.input['snapshot'])
    service=Research(plane.desk)
    assert service.create(req)['id']==plane.request['id']
    with pytest.raises(Conflict):service.create(req.model_copy(update={'question':'different'}))

def test_reference_calculation_and_direction(plane):
 a,b=plane.call('financial_observations',{'metric':'revenue'})
 c=plane.call('calculate',{'operation':'growth','left':a['id'],'right':b['id']})
 assert c['value']==-50 and c['direction']=='decrease'
 e=plane.call('read_source',{'source_id':'source_fixture'})['blocks'][0]
 result=validate(draft(claim(text='2025Q2 收入增长 {{'+c['id']+'}}。',evidence=[e['id']])),plane)
 assert any(x['code']=='direction' for x in result['issues'])
 assert result['verification']['removed_claims']==0
 good=validate(draft(claim(text='2025Q2 收入下降 {{'+c['id']+'}}。',evidence=[e['id']])),plane)
 assert good['claims'][0]['validation']=='integrity_checked'
 assert '-50.000 %' in good['claims'][0]['text']

@pytest.mark.parametrize('unit,basis,frequency',[('USD_mn','GAAP','quarter'),('RMB_mn','non-GAAP','quarter'),('RMB_per_ADS','GAAP','quarter'),('RMB_mn','GAAP','annual')])
def test_incomparable_inputs_are_not_calculated(plane,unit,basis,frequency):
 a=plane._calc('revenue',100,'RMB_mn','2025Q2','observation',[],basis='GAAP',frequency='quarter')
 b=plane._calc('revenue',50,unit,'2024Q2','observation',[],basis=basis,frequency=frequency)
 with pytest.raises(ValueError):plane.calculate('growth',a['id'],b['id'])

def test_quarter_cash_and_rounding_are_retained(plane):
 a=plane._calc('operating_cash_flow',37158.599,'RMB_mn','2025Q2','observation',[],basis='GAAP',frequency='ytd')
 b=plane._calc('operating_cash_flow',15516.943,'RMB_mn','2025Q1','observation',[],basis='GAAP',frequency='ytd')
 c=plane.calculate('quarterize',a['id'],b['id']);assert c['value']==pytest.approx(21641.656)
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text='2025Q2 单季现金流为 {{'+c['id']+'}}。季节性需要后续检查。',evidence=[e['id']])),plane)
 assert not r['issues'] and r['claims'][0]['alternative']

@pytest.mark.parametrize('badperiod,metric,unit',[('2025Q4','operating_cash_flow','RMB_mn'),('2024Q2','operating_cash_flow','RMB_mn'),('2025Q2','cash','RMB_mn'),('2025Q2','eps','RMB_per_ADS')])
def test_quarterize_rejects_nonadjacent_or_stock(plane,badperiod,metric,unit):
 a=plane._calc(metric,100,unit,badperiod,'observation',[],basis='GAAP',frequency='ytd')
 b=plane._calc(metric,20,unit,'2025Q1','observation',[],basis='GAAP',frequency='ytd')
 with pytest.raises(ValueError):plane.calculate('quarterize',a['id'],b['id'])

def test_fee_impact_is_not_a_complete_earnings_forecast(plane):
 c=plane.mechanical_scenario(1000,'RMB_mn',1,'2025Q1')
 assert c['value']==-10 and c['assumption'] and '不是完整盈利预测' in c['limitations'][0]

@pytest.mark.parametrize('text',['2024Q2 在 2025Q1 之后。','2025Q1 在 2024Q2 之前。'])
def test_chronology(plane,text):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text=text,evidence=[e['id']])),plane)
 assert any(x['code']=='chronology' for x in r['issues'])

def test_dates_survive_and_other_numbers_do_not_bypass_as_interpretation(plane):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text='2025Q2 与 2024Q2 比较。',evidence=[e['id']])),plane)
 assert not r['issues']
 r=validate(draft(claim(text='2025Q2 收入 100、利润 999。',evidence=[e['id']])),plane)
 assert any(x['code']=='unbound_number' for x in r['issues'])
 assert '999' in r['claims'][0]['text'] and r['claims'][0]['validation']=='needs_repair'

def test_summary_dependency_revalidation_and_complete_denominator(plane):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text='错误数字 999。',evidence=[e['id']]),claim(id='summary',section='summary',depends_on=['c'],evidence=[e['id']])),plane)
 assert [c['validation'] for c in r['claims']]==['needs_repair']*2
 assert r['verification']['original_claims']==r['verification']['retained_claims']==2
 assert not r['handoffs']
 assert all(x['status'] in ('missing','invalid') for x in r['coverage'])

def test_uploaded_author_does_not_self_certify(plane):
 from research_fixtures import Research
 u=Research(plane.desk).upload(b'Author says growth is sustainable','text/plain','note.txt','PDD')
 # A new immutable input version explicitly admits the newly observed attachment.
 p=plane; p.input['source_ids']=[u['source_id']];p.input['snapshot']='';p.frozen=None;p.input['intent']='report_review';p.prepare()
 e=p.read_source(u['source_id'])['blocks'][0]
 r=validate(draft(claim(section='claims',verdict='supported',evidence=[e['id']])),p)
 assert any(x['code']=='source_independence' for x in r['issues'])


def test_cancel_and_lease_transfer_revoke_tools(plane):
 before=plane.state['tool_calls'];plane.queue.cancel(plane.task['id'])
 with pytest.raises(Conflict):plane.call('context',{})
 assert plane.state['tool_calls']==before


def test_tool_budget_includes_errors_and_retries(plane):
 plane.input['tool_budget']=2
 with pytest.raises(ValueError):plane.call('read_source',{'source_id':'not-in-snapshot'})
 with pytest.raises(ValueError):plane.call('not_a_tool',{})
 with pytest.raises(ValueError,match='预算耗尽'):plane.call('context',{})
 assert plane.state['tool_calls']==2 and len(plane.receipts('tool'))==2


def test_clarification_keeps_session_and_budget(plane):
 plane.state.update(session_id='precise-session-id',active_seconds=41,tool_calls=7,questions=['请确认统计范围'])
 plane.task['status']='waiting_user'
 with plane.desk.store.connect(write=True) as db:db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('waiting_user',canonical(plane.task),plane.task['id']))
 req=Research(plane.desk);a=ResearchMessage(operation_id='answer-fixture',text='只比较同口径',company='PDD',expected_input_version=plane.state['input_version'])
 r=req.message(plane.request['id'],a);r2=req.message(plane.request['id'],a)
 assert r['id']==r2['id'] and r['task']['status']=='waiting_user'
 from research_fixtures import resolve_pending
 resolve_pending(plane.desk)
 r=req.get(r['id']);assert r['task']['status']=='queued'
 assert r['task']['research']['session_id']=='precise-session-id' and r['task']['research']['tool_calls']==7 and r['task']['research']['active_seconds']==41


@pytest.mark.parametrize('name,raw',[('table.csv',b'a,b'),('archive.zip',b'PK'),('bad.txt',b'\xff')])
def test_unsupported_attachments_do_not_claim_read(tmp_path,name,raw):
 with pytest.raises(ValueError):Research(Desk(tmp_path)).upload(raw,'application/octet-stream',name)


def test_current_upload_not_historical_material(tmp_path):
 s=Research(Desk(tmp_path));u=s.upload(b'Quarter 2024Q2 report','text/plain','report.txt','PDD')
 with pytest.raises(ValueError,match='截止'):s.create(ResearchRequest(operation_id='backdate-upload',question='分析',company='PDD',source_ids=[u['source_id']],as_of='2024-01-01T00:00:00+00:00'))


def saved_report(plane):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(*[claim(id=k,section=k,evidence=[e['id']]) for k in ('changes','persistence','questions')]),plane)
 r['delivery']={'status':'ready'};r['verification']['independent_review']='passed'
 with plane.desk.store.connect(write=True) as db:
  db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,canonical({'raw':{},'validated':r})))
  plane.task.update(status='completed',result=r);db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('completed',canonical(plane.task),plane.task['id']))
 return r


def test_artifact_export_and_handoff_are_bound_to_versions(plane):
 r=saved_report(plane);s=Research(plane.desk)
 from pitr.desk.research.handoff import propose
 p=propose(s,r['request_id'],{'operation_id':'handoff-fixture','claim_id':'changes','kind':'wiki'})
 assert p['status']=='pending'
 assert '研究测试' in html_report(r) and png_chart(r).startswith(b'\x89PNG')
 assert len(slack_files(r))==2
 plane.desk.withdraw('source_fixture')
 assert s.artifact(r['request_id'])['status']=='needs_review'
 with pytest.raises((Conflict,ValueError)):plane.desk.wiki.review(p['id'],__import__('pitr.wiki.contracts',fromlist=['DecisionRecord']).DecisionRecord(operation_id='adopt-invalidated',digest=p['digest'],action='adopt',reason='Review fixture'))


def test_forged_research_ref_cannot_skip_numbers(plane):
    from pitr.wiki.contracts import ProposalInput,RevisionDraft,Reference
    report=saved_report(plane)
    binding={'kind':'research_artifact','field':'content','research_ref':{'request_id':report['request_id'],'artifact_version':1,'claim_id':'changes','claim_digest':'fake'}}
    with pytest.raises((Conflict,ValueError)):
        plane.desk.wiki.propose(ProposalInput(operation_id='forged',company='PDD',policy=Reference(**plane.desk.wiki.policy()),reason='test',changes=[RevisionDraft(id='forged',kind='page',title='Forged',content='profit 999',numeric_assertions=[binding])]))


def test_current_api_rejects_retired_versions_and_workflows(tmp_path):
    client=TestClient(create_app(tmp_path,worker=False))
    for version in (1,2):
        assert client.post('/api/desk/research/requests',json={'operation_id':'old'+str(version),'question':'核对收入','workflow_version':version}).status_code==422
    for workflow in ('investigate','earnings_review','pm_scan','factor_build'):
        assert client.post('/api/desk/tasks',json={'operation_id':workflow,'workflow':workflow}).status_code==422
    for path in ('/api/runs','/api/workbench/runs','/api/cases','/api/desk/proposals','/api/desk/operating-model'):
        assert client.get(path).status_code==404


def test_http_clarification_and_cancel_are_shared(plane):
 c=TestClient(create_app(plane.desk.root,worker=False));rid=plane.request['id']
 assert c.get('/api/desk/research/requests/'+rid).json()['task_id']==plane.task['id']
 assert c.post('/api/desk/research/requests/'+rid+'/cancel',json={}).json()['status']=='cancelled'
 assert c.get('/api/desk/research/requests/'+rid+'/report').status_code==404


def test_broker_rejects_wrong_capability_and_revoked_lease(plane):
 import urllib.request,urllib.error
 from pitr.desk.research.native import broker
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with broker(plane) as (port,token):
  url=f'http://127.0.0.1:{port}/'
  with pytest.raises(urllib.error.HTTPError):opener.open(urllib.request.Request(url,data=b'{}',headers={'Authorization':'Bearer bad'}))
  plane.queue.cancel(plane.task['id'])
  with opener.open(urllib.request.Request(url,data=b'{"catalog":true}',headers={'Authorization':'Bearer '+token})) as r:
   assert '执行权' in json.load(r)['error']


def test_metric_name_and_year_shaped_amount_cannot_bypass(plane):
 a=plane.financial_observations('revenue')[0];e=plane.read_source('source_fixture')['blocks'][0]
 bad=validate(draft(claim(text='经营利润为 {{'+a['id']+'}}。',evidence=[e['id']])),plane)
 assert any(x['code']=='metric' for x in bad['issues'])
 bad=validate(draft(claim(text='收入为 2025 百万元。',evidence=[e['id']])),plane)
 assert any(x['code']=='unbound_number' for x in bad['issues'])


def test_wiki_handoff_keeps_numeric_references_and_research_origin(plane):
 a=plane.financial_observations('revenue')[0];e=plane.read_source('source_fixture')['blocks'][0]
 raw=draft(claim(text='2025Q2 收入为 {{'+a['id']+'}}。',evidence=[e['id']]))
 report=validate(raw,plane)
 report['delivery']={'status':'ready'};report['verification']['independent_review']='passed'
 with plane.desk.store.connect(write=True) as db:
  db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,canonical({'raw':raw,'validated':report})))
  plane.task.update(status='completed',result=report);db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('completed',canonical(plane.task),plane.task['id']))
 from pitr.desk.research.handoff import propose
 p=propose(Research(plane.desk),report['request_id'],{'operation_id':'wiki-native-handoff','kind':'wiki','claim_id':'c'})
 assert p['status']=='pending'
 with plane.desk.store.connect() as db:
  from pitr.wiki.store import get
  wp=get(db,'proposals',p['id'])
  assert wp['request']['origin']=='research'


def test_bare_upload_never_becomes_official_or_auto_compiles(tmp_path):
 d=Desk(tmp_path);s=Research(d);u=s.upload(b'An author claim','text/plain','author.txt','PDD')
 from pitr.wiki.store import get
 with d.store.connect() as db:
  assert get(db,'sources',u['source_id'])['provider']=='manual'
  jobs=[json.loads(r['body']) for r in db.execute("SELECT body FROM wiki_outbox WHERE kind='compile'")]
 assert not any(u['source_id'] in str(j) for j in jobs)
 r=s.create(ResearchRequest(operation_id='bare-file-collect',source_ids=[u['source_id']],company='PDD'))
 answer=ResearchMessage(operation_id='collect-file-once',text='收录',company='PDD',intent='collect',expected_input_version=r['input_version'])
 assert s.message(r['id'],answer)['task']['status']=='waiting_user'
 from research_fixtures import resolve_pending
 resolve_pending(d,intent='collect')
 assert s.message(r['id'],answer)['task']['status']=='completed'


def test_failed_repair_keeps_last_verified_draft_visible_but_cannot_submit(plane):
 r=saved_report(plane);plane.task.update(status='failed',error='累计活跃执行预算耗尽')
 with plane.desk.store.connect(write=True) as db:db.execute('UPDATE tasks SET status=?,body=? WHERE id=?',('failed',canonical(plane.task),plane.task['id']))
 latest=Research(plane.desk).artifact(r['request_id'])
 assert latest['claims'] and latest['status']=='needs_review' and not latest['handoffs']
 assert any(i['code']=='run_incomplete' for i in latest['issues'])
 from pitr.desk.research.handoff import propose
 with pytest.raises(Conflict):propose(Research(plane.desk),r['request_id'],{'operation_id':'partial-draft-handoff','kind':'wiki','claim_id':'changes'})


@pytest.mark.parametrize('text',['收入为十亿元。','费用率增加一个百分点。','利润减少一千万元。'])
def test_chinese_financial_numerals_need_the_same_numeric_binding(plane,text):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text=text,evidence=[e['id']])),plane)
 assert any(x['code']=='unbound_number' for x in r['issues'])


def test_pdd_first_quarter_flow_can_be_the_adjacent_ytd_base(plane):
 a=plane._calc('operating_cash_flow',70,'RMB_mn','2025Q2','observation',[],basis='GAAP',frequency='ytd')
 b=plane._calc('operating_cash_flow',30,'RMB_mn','2025Q1','observation',[],basis='GAAP',frequency='quarter')
 assert plane.calculate('quarterize',a['id'],b['id'])['value']==40


def test_preparation_cannot_hold_execution_slot_beyond_budget(plane,monkeypatch):
 from pitr.desk.research.native import prepare_budgeted
 plane.clock_started=time.monotonic();plane.clock_base=0;plane.input['budget_seconds']=.1
 monkeypatch.setattr(plane,'prepare',lambda:time.sleep(1))
 start=time.monotonic()
 with pytest.raises(TimeoutError):prepare_budgeted(plane)
 assert time.monotonic()-start<.7
 assert plane.state['active_seconds']>=.1


def test_expired_lease_is_explicitly_recorded(plane):
 with plane.desk.store.connect(write=True) as db:db.execute('UPDATE tasks SET lease_until=0 WHERE id=?',(plane.task['id'],))
 claim=Queue(plane.desk).claim()
 assert claim['recovered_lease'] is True and claim['attempts']==2


def test_pdf_without_text_is_an_explicit_gap(tmp_path):
 objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
          b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << >> >>',b'<< /Length 0 >>\nstream\n\nendstream']
 raw=b'%PDF-1.4\n';offsets=[0]
 for i,obj in enumerate(objects,1):offsets.append(len(raw));raw+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
 start=len(raw);raw+=b'xref\n0 5\n0000000000 65535 f \n'+b''.join(f'{off:010d} 00000 n \n'.encode() for off in offsets[1:])
 raw+=b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF'
 u=Research(Desk(tmp_path)).upload(raw,'application/pdf','scan.pdf','PDD')
 assert u['blocks']==0 and any('文本层' in s for s in u['issues'])


def test_repair_cannot_improve_denominator_by_deleting_required_claims(plane):
 plane.register_requirements([{'id':'required-change','question':'解释变化'}])
 e=plane.read_source('source_fixture')['blocks'][0]
 raw=draft(claim(id='required',evidence=[e['id']]),claim(id='other',section='questions',evidence=[e['id']]))
 raw['requirement_resolutions']=[{'requirement_id':'required-change','status':'answered','claim_ids':['required'],'explanation':'检查必要结论'}]
 first=validate(raw,plane)
 with plane.desk.store.connect(write=True) as db:db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,canonical({'raw':raw,'validated':first})))
 revision=draft(claim(id='other',section='questions',evidence=[e['id']]))
 revision['requirement_resolutions']=raw['requirement_resolutions']
 revised=validate(revision,plane)
 assert revised['verification']['original_claims']==2 and revised['verification']['removed_claims']==1
 assert next(c['status'] for c in revised['coverage'] if c['key']=='required-change')=='invalid'
 assert revised['verification']['deleted_claims'][0]['id']=='required'


def test_bootstrap_network_uses_the_same_call_ledger(plane,monkeypatch):
 p=plane;p.frozen=None;p.input.update(snapshot='',intent='earnings',as_of=None,official_urls=[])
 monkeypatch.setattr(p,'discover_sources',lambda **kwargs:{'links':[{'url':'https://investor.pddholdings.com/fixture','period':'2025Q2','title':'quarter'}],'issues':[]})
 monkeypatch.setattr(p,'_fetch',lambda *args:p.desk.document('source_fixture'))
 p.prepare()
 assert p.state['tool_calls']==2
 assert {r['name'] for r in p.receipts('tool').values()}=={'discover_sources','prepare.fetch_source'}


def test_native_deadline_is_not_blocked_by_slow_domain_tool(plane,monkeypatch):
 import threading
 plane.clock_started=time.monotonic();plane.clock_base=0;plane.input['budget_seconds']=.1
 monkeypatch.setattr(plane,'discover_sources',lambda:time.sleep(.6))
 failures=[]
 def slow():
  try:plane.call('discover_sources',{})
  except Exception as e:failures.append(e)
 t=threading.Thread(target=slow);t.start();time.sleep(.15)
 with plane.lock:
  with pytest.raises(TimeoutError):plane.fence()
 t.join();assert any(isinstance(e,TimeoutError) for e in failures)


def test_uploaded_financial_rows_do_not_become_official_observations(plane):
 p=plane;u=Research(p.desk).upload(b'PDD revenue was RMB 999 million','text/plain','opinion.txt','PDD')
 with p.desk.store.connect(write=True) as db:
  m=Metric(id='fake-author-metric',name='revenue',label='Revenue',period='2025Q2',value=999,unit='RMB_mn',basis='GAAP',frequency='quarter',citation=Citation(source_id=u['source_id'],block_id='paragraph-0',quote='PDD revenue was RMB 999 million'))
  db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',u['source_id'],canonical(m)))
 p.frozen=None;p.input.update(snapshot='',intent='report_review',source_ids=[u['source_id']]);p.prepare()
 assert all(c['value']!=999 for c in p.financial_observations('revenue'))
 assert any('上传材料中的数字' in issue for issue in p.frozen['issues'])


def test_chinese_text_can_adjoin_a_quarter_without_becoming_an_amount(plane):
 e=plane.read_source('source_fixture')['blocks'][0]
 r=validate(draft(claim(text='比较2025Q2与2024Q2的口径。',evidence=[e['id']])),plane)
 assert not r['issues']


def test_industry_request_keeps_registered_subjects_separate(tmp_path,monkeypatch):
    from pitr.desk.research.intake import Intake
    from pitr.desk.research.contracts import ResearchInterpretation,ResearchSubject
    import pitr.wiki.discovery as sources
    d=Desk(tmp_path);q=Queue(d)
    resolved=ResearchInterpretation(title='行业可比性',scope_type='industry',subjects=[ResearchSubject(company_id=c,name=c,verified=True) for c in ('PDD','BABA')],questions=['核对收入可比性']).model_dump()
    r=Intake(d,q).create(ResearchRequest(operation_id='industry-input',question='复核行业收入可比性'),resolved=resolved)
    t=q.claim();p=ToolPlane(d,t,q.owner,lambda u:q.checkpoint(t,u));p.prepare()
    monkeypatch.setattr(sources,'fetch_public',lambda *a,**kw:(b'PDD public disclosure','text/plain','https://investor.pddholdings.com/release',[]))
    assert p._fetch('https://investor.pddholdings.com/release').company=='PDD'
    with pytest.raises(ValueError,match='company_id'):p.financial_observations('revenue')


def test_extra_source_keeps_fixed_model_baseline_in_a_new_input_version(plane):
 from pitr.desk.company_model import ModelSpec
 p=plane;base=p.frozen['snapshot'];saved={'id':'model-fixture','spec':ModelSpec(snapshot=base,anchor_period='2025Q2').model_dump()}
 with p.desk.store.connect(write=True) as db:db.execute('INSERT INTO imports VALUES(?,?,?,?)',(saved['id'],'operating_draft','PDD',canonical(saved)))
 p.input.update(snapshot=base,model_draft_id=saved['id']);p.frozen=None;p.prepare()
 u=Research(p.desk).upload(b'Additional pending explanation','text/plain','extra.txt','PDD')
 with p.desk.store.connect() as db:snap=p.desk._snapshot(db,p.frozen['snapshot'])
 snap['sources'][u['source_id']]=u['digest']
 later=p._freeze(snap,[])
 assert later['snapshot']!=base and later['model_draft']['spec']['snapshot']==base
 assert later['model_draft']['id']==saved['id']


def test_official_link_in_natural_request_is_preserved(tmp_path):
 s=Research(Desk(tmp_path));url='https://investor.pddholdings.com/quarterly-results'
 r=s.create(ResearchRequest(operation_id='natural-source-url',question='分析 PDD 财报 '+url))
 assert r['input']['official_urls']==[url]


def test_cash_profit_check_requires_same_period_and_fee_shock_requires_revenue(plane):
 cash=plane._calc('operating_cash_flow',100,'RMB_mn','2025Q2','observation',[],basis='GAAP',frequency='quarter')
 profit=plane._calc('net_income',50,'RMB_mn','2025Q1','observation',[],basis='GAAP',frequency='quarter')
 with pytest.raises(ValueError,match='同期间'):plane.calculate('subtract',cash['id'],profit['id'])
 with pytest.raises(ValueError,match='收入金额'):plane.calculate('fee_shock',profit['id'],delta_pp=1)


def test_wrapped_existing_calculation_identifier_is_syntax_not_a_new_claim(plane):
 c=plane.mechanical_scenario(1000,'RMB_mn',1,'2025Q1');token='{{'+c['id']+'}}'
 raw=draft(claim(text='情景经营利润影响为 '+token+'。',verdict='supported',calculations=[token]))
 out=validate(raw,plane)
 assert not out['issues'] and out['claims'][0]['calculations']==[c['id']]
 assert out['verification']['reference_syntax_normalizations'][0]['from']==token
 assert raw['claims'][0]['calculations']==[token]
 bad=validate(draft(claim(text='情景影响。',calculations=['{{calculation_deadbeef}}'])),plane)
 assert any(i['code']=='calculation' for i in bad['issues'])


def test_real_source_ytd_period_notation_is_preserved_and_can_be_quarterized(plane):
 a=plane._calc('operating_cash_flow',42115,'RMB_mn','2026YTD2','observation',[],basis='GAAP',frequency='ytd')
 b=plane._calc('operating_cash_flow',16445,'RMB_mn','2026Q1','observation',[],basis='GAAP',frequency='quarter')
 c=plane.calculate('quarterize',a['id'],b['id'])
 assert c['value']==25670 and c['period']=='2026Q2' and c['frequency']=='quarter'
 e=plane.read_source('source_fixture')['blocks'][0]
 for period in ('2026YTD2','2026H1','FY2026','2026FY'):
  out=validate(draft(claim(text='累计报告期间是'+period+'，需要区分单季口径。',evidence=[e['id']])),plane)
  assert not out['issues']

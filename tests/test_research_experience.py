"""Research behavior tests. Injected interpretations are not model-quality measurements."""
import json,time,hashlib
import pytest
from fastapi.testclient import TestClient
from pitr.desk.api import create_app
from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from pitr.desk.storage import Conflict,canonical,digest
from pitr.desk.contracts import Document,SourceBlock,utcnow,Metric,Citation
from pitr.desk.research.service import Research
from pitr.desk.research.contracts import ResearchRequest,ResearchMessage,ResearchInterpretation,ResearchSubject
from pitr.desk.research.intake import IntakeWorker,apply_updates,ready_update
from pitr.desk.research.semantics import normalize as normalize_model

def normalize(desk,value,*args,**kwargs):
 value={**value,'subjects':[{k:v for k,v in s.items() if k!='verified'} for s in value['subjects']]}
 return normalize_model(desk,value,*args,**kwargs)
from pitr.desk.research.tools import ToolPlane
from pitr.desk.research.presentation import enrich

def interpreted(*companies,scope='company',clarification='',period='',topic='',as_of=None):
 return ResearchInterpretation(title='利润持续性研究',scope_type=scope,subjects=[ResearchSubject(company_id=c,name=c,mention=c,verified=True) for c in companies],questions=['利润增长是否可持续？'],plan=['读取原始披露','核对现金转化','寻找替代解释'],period=period,topic=topic,clarification=clarification,options=['分析材料','收录材料'] if clarification else [],as_of=as_of).model_dump()

@pytest.fixture
def env(tmp_path):
 d=Desk(tmp_path/'desk');q=Queue(d);return d,q,Research(d,q)

def create(env,text='分析拼多多的利润持续性',**kw):
 return env[2].create(ResearchRequest(operation_id='create-'+digest([text,kw])[:14],workflow_version=3,question=text,**kw))

def resolve(env,value):
 w=IntakeWorker(env[0],env[1],resolver=lambda *a:value);assert w.run_one();return w

def start(env,r):
 t=env[1].claim();assert t and t['id']==r['task_id']
 p=ToolPlane(env[0],t,env[1].owner,lambda u:env[1].checkpoint(t,u));p.prepare();return p

def document(d,company,name='source',text='Revenue 100 million. Profit 20 million.'):
 now=utcnow();sid='source_'+digest([company,name])[:12];fn=sid+'.txt';(d.files/fn).write_text(text)
 doc=Document(id=sid,company=company,title=company+' 2025Q2',url='https://'+('investor.pddholdings.com' if company=='PDD' else 'www.alibabagroup.com')+'/'+name,digest=hashlib.sha256(text.encode()).hexdigest(),media_type='text/plain',published_at=now,available_at=now,observed_at=now,origin_group='issuer',blocks=[SourceBlock(id='b',text=text)],file_name=fn)
 d.put_document(doc)
 with d.store.connect(write=True) as db:
  m=Metric(id='obs_'+sid,name='revenue',label='收入',period='2025Q2',value=100,unit='RMB_mn',basis='GAAP',frequency='quarter',citation=Citation(source_id=sid,block_id='b',quote=text))
  db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,company,sid,canonical(m)))
 return doc

def test_api_uses_semantic_intake_without_company(env):
 app=create_app(env[0].root,worker=False)
 with TestClient(app) as c:
  r=c.post('/api/desk/research/requests',json={'operation_id':'api-natural-input','question':'分析阿里的利润'}).json()
  assert r['input']['workflow_version']==3 and r['input']['company']==''
  assert r['task']['stage']=='interpreting'
  assert env[1].claim() is None
  resolve(env,interpreted('BABA'))
  r=c.get('/api/desk/research/requests/'+r['id']).json()
  assert r['input']['company']=='BABA' and r['task']['status']=='queued'

def test_intake_does_not_wait_for_heavy_research(env):
 one=create(env);resolve(env,interpreted('PDD'));p=start(env,one)
 two=create(env,'比较拼多多和阿里');resolve(env,interpreted('PDD','BABA',scope='comparison'))
 assert env[2].get(two['id'])['task']['status']=='queued'
 assert env[2].get(one['id'])['task']['status']=='running'
 assert env[1].claim() is None

def test_context_does_not_override_semantics(env):
 inp=ResearchRequest(operation_id='test-context',question='不要研究拼多多，研究阿里',company='PDD',context_source='passive').model_dump()
 out=normalize(env[0],interpreted('BABA'),inp,[])
 assert out['subjects'][0]['company_id']=='BABA' and not out['clarification']
 inp['context_source']='workspace';out=normalize(env[0],interpreted('BABA'),inp,[])
 assert out['clarification'] and 'PDD' in out['options']

def test_single_known_alias_can_resolve_without_id(env):
 value=interpreted('');value['subjects'][0].update(name='阿里巴巴',mention='阿里')
 out=normalize(env[0],value,ResearchRequest(operation_id='known-alias',question='研究阿里').model_dump(),[])
 assert out['subjects'][0]['company_id']=='BABA'

def test_multi_company_snapshots_and_numbers_do_not_mix(env):
 a=document(env[0],'PDD');b=document(env[0],'BABA')
 r=create(env,'比较拼多多和阿里');resolve(env,interpreted('PDD','BABA',scope='comparison'));p=start(env,r)
 assert {s['company_id'] for s in p.frozen['subject_contexts']}=={'PDD','BABA'}
 assert not p.frozen['rows']
 with pytest.raises(ValueError,match='company_id'):p.financial_observations('revenue')
 left=p.financial_observations('revenue',company='PDD')[0];right=p.financial_observations('revenue',company='BABA')[0]
 assert left['company_id']=='PDD' and right['company_id']=='BABA'
 assert p.calculate('compare',left['id'],right['id'])['subject_ids']==['BABA','PDD']
 with pytest.raises(ValueError,match='跨公司'):p.calculate('growth',left['id'],right['id'])
 with pytest.raises(ValueError,match='跨公司'):p.calculate('add',left['id'],right['id'])
 e=p.read_source(a.id)['blocks'][0]
 args=dict(evidence_id=e['id'],text='100',metric='revenue',unit='RMB_mn',period='2025Q2',role='company_actual',basis='GAAP',frequency='quarter')
 with pytest.raises(ValueError,match='company_id'):p.register_numbers([args])
 with pytest.raises(ValueError,match='主体'):p.register_numbers([{**args,'company_id':'BABA'}])

def test_subject_period_or_basis_mismatch_rejects_comparison(env):
 r=create(env,'比较拼多多和阿里');resolve(env,interpreted('PDD','BABA',scope='comparison'));p=start(env,r)
 a=p._calc('revenue',100,'RMB_mn','2025Q2','source_literal',[],company_id='PDD',basis='GAAP',frequency='quarter')
 b=p._calc('revenue',100,'USD_mn','2025Q2','source_literal',[],company_id='BABA',basis='GAAP',frequency='quarter')
 with pytest.raises(ValueError,match='口径'):p.calculate('compare',a['id'],b['id'])
 c=p._calc('revenue',100,'RMB_mn','2025Q3','source_literal',[],company_id='BABA',basis='GAAP',frequency='quarter')
 with pytest.raises(ValueError,match='period'):p.calculate('compare',a['id'],c['id'])

def test_topic_only_has_no_fake_company(env):
 r=create(env,'研究跨境电商的竞争格局');resolve(env,interpreted(scope='industry',topic='跨境电商'))
 p=start(env,r);assert p.frozen['company']=='INDUSTRY' and p.frozen['subject_contexts']==[]
 assert not p.context()['subjects'];assert p.input['scope']['topic']=='跨境电商'

def test_messages_are_idempotent_and_survive_checkpoints(env):
 r=create(env);resolve(env,interpreted('PDD'));p=start(env,r)
 msg=ResearchMessage(operation_id='update-margin-focus',text='重点看现金流',expected_input_version=p.state['input_version'])
 first=env[2].message(r['id'],msg);again=env[2].message(r['id'],msg)
 assert len(again['messages'])==1
 p.checkpoint({'research':p.state,'stage':'read_page'})
 assert env[2].get(r['id'])['messages'][0]['text']=='重点看现金流'
 resolve(env,interpreted('PDD'));assert ready_update(p)
 apply_updates(p)
 updated=env[2].get(r['id']);assert updated['messages'][0]['status']=='applied'
 assert '重点看现金流' in p.input['question'] and p.state['recoveries']==0
 with pytest.raises(Conflict):env[2].message(r['id'],msg.model_copy(update={'operation_id':'stale-update-next'}))
 # Retrying the same command still returns the original accepted message after input advances.
 assert len(env[2].message(r['id'],msg)['messages'])==1

def test_scope_change_creates_successor_without_reusing_snapshot(env):
 r=create(env);resolve(env,interpreted('PDD'));p=start(env,r)
 env[2].message(r['id'],ResearchMessage(operation_id='change-to-alibaba',text='改成研究阿里',expected_input_version=p.state['input_version']))
 resolve(env,interpreted('BABA'))
 with pytest.raises(Conflict,match='关联修订'):apply_updates(p)
 old=env[2].get(r['id']);assert old['task']['status']=='cancelled'
 nxt=env[2].get(old['messages'][0]['next_request_id'])
 assert nxt['input']['company']=='BABA' and nxt['input']['parent_request_id']==r['id'] and not nxt['input']['snapshot']

def test_latest_message_fences_old_interpretation(env):
 r=create(env)
 env[2].message(r['id'],ResearchMessage(operation_id='second-input-wins',text='改成研究阿里',expected_input_version=0))
 resolve(env,interpreted('BABA'))
 latest=env[2].get(r['id']);assert latest['conversation_version']==2 and latest['input']['company']=='BABA'
 assert not IntakeWorker(env[0],resolver=lambda *a:interpreted('PDD')).run_one()

def test_resolution_error_keeps_input_and_allows_retry(env):
 r=create(env)
 def fail(*a):raise RuntimeError('offline')
 IntakeWorker(env[0],resolver=fail).run_one()
 current=env[2].get(r['id']);assert current['interpretation_status']=='error' and current['original_question']==r['input']['question']
 env[2].message(r['id'],ResearchMessage(operation_id='retry-understand-input',text='请重试',expected_input_version=0))
 resolve(env,interpreted('PDD'));assert env[2].get(r['id'])['task']['status']=='queued'

def test_key_findings_only_use_validated_claims():
 report={'claims':[{'id':'bad','section':'summary','validation':'needs_repair','text':'bad'},{'id':'valid','section':'changes','validation':'integrity_checked','text':'checked'}]}
 out=enrich(report);assert out['key_claim_ids']==['valid'];assert out['sections'][0]['claim_ids']==['bad']

def test_attachment_only_asks_for_action(env):
 sid=env[2].upload(b'PDD opinion','text/plain','note.txt')['source_id']
 req=ResearchRequest(operation_id='only-attachment',question='',source_ids=[sid]).model_dump()
 out=normalize(env[0],interpreted('PDD'),req,[])
 assert out['clarification']=='希望我如何处理这些材料？' and len(out['options'])==3

def test_unknown_identity_never_auto_becomes_registered(env,monkeypatch):
 monkeypatch.setattr('pitr.desk.research.semantics.verify_identity',lambda *a:None)
 value=interpreted('FAKE');value['subjects'][0]['name']='不确定的公司'
 out=normalize(env[0],value,ResearchRequest(operation_id='unknown-identity',question='研究这家公司').model_dump(),[])
 assert out['clarification'] and not out['subjects'][0]['verified'] and not out['subjects'][0]['company_id']

def test_explicit_conflict_can_release_old_snapshot(env):
 snap=env[0].snapshot('PDD',utcnow())[0]
 r=create(env,'分析阿里',company='PDD',snapshot=snap,context_source='workspace')
 resolve(env,interpreted('BABA',clarification='以哪个对象为准？'))
 current=env[2].get(r['id']);assert current['input']['company']=='PDD' and current['input']['snapshot']==snap
 env[2].message(r['id'],ResearchMessage(operation_id='release-fixed-context',text='以阿里为准，移除原上下文',expected_input_version=0,release_context=True))
 value=interpreted('BABA');value['context_action']='replace';resolve(env,value)
 current=env[2].get(r['id']);assert current['task']['status']=='queued' and current['input']['company']=='BABA' and not current['input']['snapshot']

def test_period_revision_clears_fixed_snapshot(env):
 snap=env[0].snapshot('PDD',utcnow())[0]
 r=create(env,company='PDD',snapshot=snap,period='2025Q1');resolve(env,interpreted('PDD',period='2025Q1'));p=start(env,r)
 env[2].message(r['id'],ResearchMessage(operation_id='period-correction',text='改成第二季度',expected_input_version=p.state['input_version']))
 resolve(env,interpreted('PDD',period='2025Q2'))
 with pytest.raises(Conflict):apply_updates(p)
 current=env[2].get(r['id']);nxt=env[2].get(current['messages'][0]['next_request_id'])
 assert nxt['input']['period']=='2025Q2' and not nxt['input']['snapshot']

def test_message_arriving_at_delivery_prevents_false_completion(env,monkeypatch):
 r=create(env);resolve(env,interpreted('PDD'))
 def deliver(desk,task,owner,checkpoint):
  env[2].message(r['id'],ResearchMessage(operation_id='late-message',text='同时核对现金流',expected_input_version=0))
  return {'status':'review_ready'}
 monkeypatch.setattr('pitr.desk.research.native.run',deliver)
 assert env[1].run_one()
 current=env[2].get(r['id']);assert current['task']['status']=='waiting_user' and current['messages'][0]['status']=='received'
 assert current['task']['stage']=='awaiting_input'

def test_new_identity_requires_downloaded_regulator_proof(env,monkeypatch):
 from pitr.desk.research.semantics import verify_identity,companies
 body=b'Example Legal Corporation. Trading symbol EXAM on NASDAQ.'
 def response(desk,key,prompt,schema,**kw):
  if schema.__name__=='Identity':return {'name':'Example Legal Corporation','aliases':[],'securities':[{'ticker':'EXAM','exchange':'NASDAQ'}],'urls':['https://www.sec.gov/Archives/profile.htm']}
  return {'confirmed':True,'name':'Example Legal Corporation','securities':[{'ticker':'EXAM','exchange':'NASDAQ'}],'quote':body.decode()}
 monkeypatch.setattr('pitr.desk.research.semantics.run_json',response)
 monkeypatch.setattr('pitr.wiki.discovery.fetch_public',lambda url,**kw:(body,'text/plain',url,[]))
 record=verify_identity(env[0],{'name':'Example Legal Corporation','securities':[]},'known-proof',lambda:None,'gpt-5.5')
 assert record['company'] in companies(env[0]) and record['identity_receipts'][0]['digest']==hashlib.sha256(body).hexdigest()
 monkeypatch.setattr('pitr.wiki.discovery.fetch_public',lambda url,**kw:(b'This page is unrelated','text/plain',url,[]))
 assert verify_identity(env[0],{'name':'Example Legal Corporation','securities':[]},'bad-proof',lambda:None,'gpt-5.5') is None

def test_reference_is_not_a_second_research_target(env):
 value=interpreted('JD','AMZN',scope='comparison');value['subjects'][1]['role']='reference'
 out=normalize(env[0],value,ResearchRequest(operation_id='reference-role',question='以亚马逊为参照分析京东').model_dump(),[])
 assert out['scope_type']=='company' and [s['company_id'] for s in out['subjects'] if s['role']=='target']==['JD']

def test_identity_is_stable_across_filings_and_distinct_within_shared_filing(env,monkeypatch):
 from pitr.desk.research.semantics import verify_identity
 state={'name':'Example One Limited','ticker':'101','url':'https://www.hkexnews.hk/shared.pdf'}
 def response(desk,key,prompt,schema,**kw):
  security={'exchange':'HKEX','ticker':state['ticker']}
  if schema.__name__=='Identity':return {'name':state['name'],'aliases':[],'securities':[security],'urls':[state['url']]}
  return {'confirmed':True,'name':state['name'],'securities':[security],'quote':state['name']+' Stock Code '+state['ticker']}
 monkeypatch.setattr('pitr.desk.research.semantics.run_json',response)
 monkeypatch.setattr('pitr.wiki.discovery.fetch_public',lambda url,**kw:((state['name']+' Stock Code '+state['ticker']).encode(),'text/plain',url,[]))
 def verify():return verify_identity(env[0],{'name':state['name']},'stable-company',lambda:None,'gpt-5.5')['company']
 first=verify()
 state.update(name='Example Two Limited',ticker='102');second=verify()
 assert first!=second
 state.update(name='Example One Limited',ticker='00101',url='https://www.hkexnews.hk/another-filing.pdf')
 assert verify()==first

def test_hong_kong_code_padding_does_not_create_false_ambiguity(env):
 registry={'EXAMPLE':{'company':'EXAMPLE','name':'Example Limited','securities':[{'exchange':'HKEX','ticker':'700'}]}}
 value=interpreted('EXAMPLE');value['subjects'][0]['securities']=[{'exchange':'SEHK','ticker':'00700'}]
 out=normalize(env[0],value,ResearchRequest(operation_id='hk-code-padding',question='分析 Example').model_dump(),[],registry=registry)
 assert not out['clarification'] and out['subjects'][0]['company_id']=='EXAMPLE'

def test_supplied_regulator_original_is_checked_without_repeated_search(env,monkeypatch):
 from pitr.desk.research.semantics import verify_identity
 body='Example Limited Stock Code 700';code='00700'
 def response(desk,key,prompt,schema,**kw):
  assert schema.__name__=='IdentityProof'
  return {'confirmed':True,'name':'Example Limited','securities':[{'ticker':code,'exchange':'HKEX'}],'quote':body}
 monkeypatch.setattr('pitr.desk.research.semantics.run_json',response)
 monkeypatch.setattr('pitr.wiki.discovery.fetch_public',lambda url,**kw:(body.encode(),'text/plain',url,[]))
 mention={'name':'示例有限公司','securities':[{'ticker':'0700','exchange':'HKEX'}],'identity_sources':['https://www.hkexnews.hk/original.pdf']}
 assert verify_identity(env[0],mention,'direct-original',lambda:None,'gpt-5.5')
 body='Example Limited Stock Code 999';code='999'
 assert verify_identity(env[0],mention,'wrong-security',lambda:None,'gpt-5.5') is None

def test_cancel_pending_understanding_does_not_restart_research(env):
 r=create(env);env[1].cancel(r['task_id'])
 assert not IntakeWorker(env[0],resolver=lambda *a:interpreted('PDD')).run_one()
 assert env[2].get(r['id'])['task']['status']=='cancelled' and len(env[2].list())==1
 env[2].message(r['id'],ResearchMessage(operation_id='intentional-resume',text='请继续',expected_input_version=0))
 resolve(env,interpreted('PDD'))
 assert len(env[2].list())==2

def test_received_message_is_preserved_when_user_stops(env):
 r=create(env);resolve(env,interpreted('PDD'));p=start(env,r)
 env[2].message(r['id'],ResearchMessage(operation_id='saved-on-stop',text='别忘了现金流',expected_input_version=p.state['input_version']))
 env[1].cancel(r['task_id'])
 current=env[2].get(r['id']);assert current['messages'][0]['status']=='saved' and current['messages'][0]['text']=='别忘了现金流'
 assert not IntakeWorker(env[0],resolver=lambda *a:interpreted('PDD')).run_one()

def test_requested_no_public_search_is_enforced(env):
 r=create(env);value=interpreted('PDD');value['allow_public_search']=False;resolve(env,value);p=start(env,r)
 with pytest.raises(ValueError,match='不执行外部搜索'):p.search_public('PDD')

def test_industry_numbers_keep_topic_identity(env):
 sid=env[2].upload(b'Offline topic fixture: industry total 100.','text/plain','industry.txt')['source_id']
 r=create(env,'研究行业整体供给',source_ids=[sid]);resolve(env,interpreted(scope='industry',topic='行业供给'));p=start(env,r)
 e=p.read_source(sid)['blocks'][0]
 n=p.register_numbers([dict(evidence_id=e['id'],text='100',metric='industry_supply',unit='count',period='2025Q2',role='scenario',basis='disclosed',frequency='quarter')])
 assert n[0]['company_id']=='INDUSTRY'

def test_ambiguous_candidates_are_asked_before_expensive_identity_search(env,monkeypatch):
 def unexpected(*a):raise AssertionError('Ambiguous intent should be clarified first')
 monkeypatch.setattr('pitr.desk.research.semantics.verify_identity',unexpected)
 value=interpreted('',clarification='你指中信银行还是中信证券？');value['subjects'][0]['name']='中信'
 out=normalize(env[0],value,ResearchRequest(operation_id='ambiguous-identity',question='分析中信').model_dump(),[])
 assert out['clarification']=='你指中信银行还是中信证券？' and not out['subjects'][0]['verified']

def test_download_uses_selected_immutable_artifact_version(env):
 from pitr.desk.research.verify import validate
 r=create(env);resolve(env,interpreted('PDD'));p=start(env,r)
 old=validate({'title':'旧版本报告','claims':[]},p);new={**old,'title':'新版本报告'}
 with env[0].store.connect(write=True) as db:
  for version,report in [(1,old),(2,new)]:db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(r['task_id'],version,canonical({'raw':{},'validated':report})))
  task=env[2].get(r['id'],db)['task'];task['status']='completed';db.execute("UPDATE tasks SET status='completed',body=? WHERE id=?",(canonical(task),task['id']))
 with TestClient(create_app(env[0].root,worker=False)) as client:
  first=client.get('/api/desk/research/requests/'+r['id']+'/report?version=1').json()
  assert first['title']=='旧版本报告' and first['artifact_version']==1
  html=client.get('/api/desk/research/requests/'+r['id']+'/report.html?version=1').text
  assert '旧版本报告' in html and '新版本报告' not in html
  assert client.get('/api/desk/research/requests/'+r['id']+'/report?version=99').status_code==404

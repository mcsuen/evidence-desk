"""Offline contract acceptance: no network, remote model, or Slack delivery."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pitr.desk.api import create_app
from pitr.desk.service import Desk
from pitr.desk.tasks import Queue
from pitr.desk.storage import Conflict, canonical
from pitr.wiki.contracts import WikiJobRequest, WikiUpdateSchedule, CompanyRegistration, ProposalInput, RevisionDraft, Reference, DecisionRecord, QueryInput, AnswerInput
from pitr.wiki.jobs import WikiJobs, run, next_run
from pitr.wiki.store import state, get


@pytest.fixture
def lab(tmp_path, monkeypatch):
    desk=Desk(tmp_path/'desk'); queue=Queue(desk)
    service=WikiJobs(desk.wiki,queue)
    service.register(CompanyRegistration(operation_id='fixture-identity',company='TEST',name='Test Issuer',aliases=['测试公司'],official_domains=['issuer.example.com']))
    def discover(wiki,task,context,timeout,checkpoint):
        needs=context['needs']
        return {'search_log':['Official, industry and media fixture discovery'], 'gaps':[], 'excluded':['Unattributed search snippet'],
          'candidates':[
            {'url':'https://issuer.example.com/annual','title':'TEST annual','category':'official','subject':'TEST','publisher':'Test Issuer','rationale':'annual','period':next(n['period'] for n in needs if n['id'].startswith('annual')), 'needs':[n['id'] for n in needs if n['id'] not in ('industry','media')]},
            {'url':'https://industry.example.com/report','title':'Industry report','category':'industry','subject':'INDUSTRY','publisher':'Industry Office','rationale':'industry','needs':['industry']},
            {'url':'https://news.example.com/interview','title':'Public interview','category':'media','subject':'TEST','publisher':'News Desk','rationale':'media','needs':['media']}]}
    def fetch(url,timeout):
        period=''
        if url.endswith('/annual'):period=f'For the fiscal year ended December 31, {datetime.now(timezone.utc).year-1}.'
        import re
        quarter=re.search(r'(20\d{2})Q([1-4])$',url)
        if quarter:period=f"{['First','Second','Third','Fourth'][int(quarter[2])-1]} Quarter {quarter[1]} Financial Results."
        text=('Offline software fixture, not a financial claim. '+url+' '+period+'\n\nBusiness competition, industry markets, risk and investment influence research judgments. A separate source is needed to establish the magnitude and applicability of any claim.').encode()
        return text,'text/plain',url,[{'url':url,'status':200}]
    def compile(wiki,task,checkpoint):
        with wiki.store.connect() as db:
            sources=[get(db,'sources',s) for s in task['request']['parameters']['source_ids']]
            pages=wiki._visible(state(db),task['request']['company'])
        citations=[{'source_id':s['id'],'block_id':s['blocks'][-1]['id'],'quote':s['blocks'][-1]['text']} for s in sources]
        before=next((p for p in pages if p['id']=='company:TEST'),None)
        changes=[RevisionDraft(id='company:TEST',kind='page',page_type='company',title='TEST company research',content='竞争与投入仍需持续跟踪。',citations=citations,reason='跨来源综合',expected_version=before['version'] if before else 0)]
        changes += [RevisionDraft(id='source-note:'+s['id'],kind='page',page_type='source',title=s['title']+' 解读',content='这份资料为研究提供了线索，仍需核验适用范围。',citations=[c],reason='解释来源') for s,c in zip(sources,citations)]
        return {'wiki_proposal':ProposalInput(operation_id='fixture-compile:'+task['id'],company='TEST',policy=Reference(**task['request']['parameters']['policy']),changes=changes,reason='完整公司研究变更').model_dump()}
    monkeypatch.setattr('pitr.wiki.jobs.discover',discover)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public',fetch)
    monkeypatch.setattr('pitr.wiki.worker.compile_sources',compile)
    return SimpleNamespace(desk=desk,wiki=desk.wiki,queue=queue,jobs=service,fetch=fetch,discover=discover)


def test_build_atomic_task_and_structured_delivery_replay(lab):
    request=WikiJobRequest(operation_id='fixture-build',company='测试公司',years=1,quarters=1)
    created=lab.jobs.create(request)
    assert lab.jobs.create(request)['id']==created['id']
    with lab.desk.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1
        assert not state(db,'update_schedules')
    assert lab.queue.run_one()
    job=lab.jobs.get(created['id'])
    assert job['proposal_id'] and job['publication_status']=='waiting_review'
    assert {m['provider'] for m in job['materials']}=={'official','industry','media'}
    assert next(m for m in job['materials'] if m['provider']=='industry')['subject_company']=='INDUSTRY'
    assert not [p for p in lab.wiki.list('TEST') if p['kind']!='policy']
    with lab.desk.store.connect() as db:
        p=get(db,'proposals',job['proposal_id']);before=state(db)
        outbox=[dict(r) for r in db.execute('SELECT * FROM wiki_outbox')]
    lab.wiki.rebuild()
    with lab.desk.store.connect() as db:
        assert state(db)==before
        assert [dict(r) for r in db.execute('SELECT * FROM wiki_outbox')]==outbox
    lab.wiki.review(p['id'],DecisionRecord(operation_id='fixture-human-adoption',digest=p['digest'],action='adopt',reason='Offline fixture acceptance'))
    assert lab.jobs.get(job['id'])['publication_status']=='published'
    from pitr.wiki.workspace import workspace,page,source
    view=workspace(lab.wiki,'TEST')
    assert len(view['pages'])==4 and all(s['contributes_to'] for s in view['sources'])
    assert page(lab.wiki,'company:TEST')['policy']['version']==1
    assert source(lab.wiki,job['materials'][0]['source_id'])['contributes_to']


def test_partial_failure_resume_keeps_originals_and_retries_failed_sources(lab,monkeypatch):
    calls=[]
    def fail(url,timeout):
        calls.append(url)
        if 'news.' in url:raise ValueError('HTTP 503')
        return lab.fetch(url,timeout)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public',fail)
    created=lab.jobs.create(WikiJobRequest(operation_id='fixture-partial',company='TEST',years=1,quarters=1))
    lab.queue.run_one();first=lab.jobs.get(created['id'])
    assert first['execution_status']=='partial' and first['proposal_id']
    assert len(first['failures'])==1 and len([m for m in first['materials'] if m.get('source_id')])==2
    calls.clear()
    def recover(url,timeout):calls.append(url);return lab.fetch(url,timeout)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public',recover)
    second=lab.jobs.create(WikiJobRequest(operation_id='fixture-resume',company='TEST',years=1,quarters=1,resume_job_id=first['id']))
    lab.queue.run_one()
    assert calls==['https://news.example.com/interview']
    final=lab.jobs.get(second['id'])
    assert len(final['materials'])==3
    assert {m['source_id'] for m in first['materials'] if m.get('source_id')} <= {m['source_id'] for m in final['materials']}


def test_same_url_revision_and_no_automatic_publication(lab,monkeypatch):
    first=lab.jobs.create(WikiJobRequest(operation_id='fixture-a',company='TEST',years=1,quarters=1));lab.queue.run_one()
    old=lab.jobs.get(first['id'])['materials'][0]['source_id']
    def revised(url,timeout):
        raw,media,url,receipts=lab.fetch(url,timeout)
        return raw+b'\n\nA correction changes the scope of the earlier disclosure.',media,url,receipts
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public',revised)
    second=lab.jobs.create(WikiJobRequest(operation_id='fixture-b',company='TEST',intent='update',years=1,quarters=1));lab.queue.run_one()
    new=lab.jobs.get(second['id'])
    assert all(m['status']=='revised' for m in new['materials'])
    with lab.desk.store.connect() as db:
        assert get(db,'sources',old)['state']=='superseded'
        assert get(db,'sources',new['materials'][0]['source_id'])['revision_of']==old
        assert len(state(db,'proposals'))==2


def test_cancel_fences_source_writes_and_resume(lab):
    job=lab.jobs.create(WikiJobRequest(operation_id='fixture-cancel',company='TEST'))
    task=lab.queue.claim()
    lab.queue.cancel(task['id'])
    with pytest.raises((RuntimeError,Conflict)):
        run(lab.wiki,task,lab.queue.owner,lambda updates:lab.queue.checkpoint(task,updates))
    assert lab.jobs.get(job['id'])['execution_status']=='cancelled'
    with lab.desk.store.connect() as db:assert not state(db,'sources')


def test_schedule_timezone_sleep_coalescing_pause_and_idempotency(lab):
    req=WikiUpdateSchedule(operation_id='fixture-weekly',company='TEST',timezone='Asia/Shanghai')
    s=lab.jobs.schedule(req)
    assert lab.jobs.schedule(req)==s
    due=datetime.fromisoformat(s['next_at']).timestamp()
    lab.jobs.tick(due+21*86400)
    lab.jobs.tick(due+21*86400)
    jobs=lab.jobs.list('TEST')
    assert len(jobs)==1 and jobs[0]['request']['budget_seconds']==600
    lab.jobs.schedule(req.model_copy(update={'operation_id':'fixture-pause','enabled':False}))
    lab.queue.run_one()
    assert lab.jobs.get(jobs[0]['id'])['execution_status']=='cancelled'
    with lab.desk.store.connect() as db:assert not state(db,'sources')
    local=datetime.fromisoformat(next_run(req.model_dump(),datetime(2026,9,13,23,tzinfo=timezone.utc))).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai'))
    assert local.weekday()==0 and local.hour==9
    dst={'timezone':'America/New_York','frequency':'daily','weekdays':[0],'local_time':'02:30'}
    assert next_run(dst,datetime(2026,3,8,0,tzinfo=timezone.utc)).startswith('2026-03-09')


def test_api_company_registration_job_contract_and_agent_review_boundary(tmp_path):
    app=create_app(tmp_path/'api',worker=False)
    with TestClient(app) as client:
        unknown=client.post('/api/desk/wiki/jobs',json={'operation_id':'fixture-x','company':'UNKNOWN'})
        assert unknown.status_code==422
        assert client.post('/api/desk/wiki/companies',headers={'x-pitr-actor':'agent'},json={'operation_id':'fixture-a','company':'NEW','name':'New Co'}).status_code==403
        job=client.post('/api/desk/wiki/jobs',json={'operation_id':'fixture-j','company':'PDD','intent':'update'}).json()
        assert job['request']['budget_seconds']==600
        assert client.get('/api/desk/wiki/workspace?company=PDD').status_code==200
        assert client.post('/api/desk/wiki/jobs/'+job['id']+'/cancel',json={'operation_id':'fixture-cancel'}).json()['execution_status']=='cancelled'


def test_public_source_guard_and_stream_download(monkeypatch):
    from pitr.wiki.discovery import public_url,fetch_public
    import httpx,socket
    for url in ['http://example.com','https://localhost/a','https://127.0.0.1','https://169.254.169.254/latest','https://user:password@example.com','https://example.com:8765']:
        with pytest.raises(ValueError):public_url(url)
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('8.8.8.8',443))])
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(302,headers={'location':'https://127.0.0.1/private'}) if req.url.path=='/redirect' else httpx.Response(200,content=b'public data')))
    with pytest.raises(ValueError):fetch_public('https://example.com/redirect',client=client)
    assert fetch_public('https://example.com/report',client=client)[0]==b'public data'


def test_slack_natural_intent_precedes_material_capture_and_shares_jobs(lab):
    from pitr.desk.slack_adapter import DeskAdapter
    from pitr.integrations.slack import InboundEvent,ReplyTarget
    from pitr.wiki.slack_workflows import intent
    class Context:
        def __init__(self):self.messages=[];self.bound=[];self.prepared=None
        def publish(self,key,update,**kwargs):self.messages.append((key,update))
        def bind(self,tid):self.bound.append(tid)
        def prepare(self,fn):
            if self.prepared is None:self.prepared=fn()
            return self.prepared
    event=InboundEvent(id='slack-wiki-build-1',kind='message',text='帮我搜集不同来源公开资料，构建 测试公司 的 Wiki，研究利润率。',target=ReplyTarget(team_id='T1',channel_id='D1',user_id='U1',thread_ts='123.4'))
    adapter=DeskAdapter(lab.desk,lab.queue);context=Context()
    adapter.handle(event,context);adapter.handle(event,context)
    assert len(lab.jobs.list('TEST'))==1
    assert context.bound[0]==context.bound[1]
    with lab.wiki.store.connect() as db:assert not state(db,'sources')
    assert intent('这份资料请收录到 Wiki') is None
    follow=event.model_copy(update={'id':'slack-periodic-1','text':'定期更新 Wiki'})
    adapter.handle(follow,Context())
    with lab.wiki.store.connect() as db:
        schedule=get(db,'update_schedules','TEST')
    assert schedule['weekdays']==[0] and schedule['local_time']=='09:00' and schedule['timezone']=='Asia/Shanghai'


def test_answer_numeric_evidence_writeback_and_stale_target(tmp_path):
    from test_wiki_evidence import statement
    from pitr.wiki.evidence import number_catalog,bind_numbers
    from pitr.wiki.research import query,save_answer,generate_answer
    desk,doc,metrics,sources=statement(tmp_path)
    catalog=number_catalog(metrics,sources)
    number=next(v for v in catalog.values() if v['label']=='收入')
    draft=RevisionDraft.model_validate(bind_numbers(RevisionDraft(id='topic:PDD:cash',kind='page',page_type='topic',title='现金转化研究',
        content='## 当前认识\n\n原始收入为 '+number['token']+' 人民币百万元。',reason='建立研究上下文').model_dump(),catalog))
    p=desk.wiki.propose(ProposalInput(operation_id='initial-proposal',company='PDD',policy=Reference(id=desk.wiki.policy()['id'],version=1),changes=[draft],reason='研究基础'))
    desk.wiki.review(p['id'],DecisionRecord(operation_id='initial-review',digest=p['digest'],action='adopt',reason='fixture'))
    reading=query(desk.wiki,QueryInput(operation_id='numeric-query',company='PDD',question='收入是多少？',context_refs=[Reference(id=draft.id,version=1)]))
    reading['sources'][0]['blocks'].append({'id':'unrelated-annual-appendix','text':'Original appendix without relevant citations. '*50000})
    reading['items'][0]['evidence_observations']=[{'unused_cache':'duplicated cache '*50000}]
    from pitr.wiki.store import change
    with desk.store.connect(write=True) as db:
        desk.wiki._emit(db,'PDD','fixture.large_reading',[change('uses',reading['id'],reading)])
    def model(prompt,schema,**kw):
        assert len(prompt)<250000
        context=json.loads(prompt)
        assert any(s['context_complete'] is False for s in context['sources'])
        token=next(n['token'] for n in context['numbers'] if n['label']=='收入')
        return SimpleNamespace(data={'title':'数值回答','content':'披露收入为 '+token+' 人民币百万元，现金转化仍需后续证据。','used':[{'id':draft.id,'version':1}], 'citations':number['citations']},model='offline',provider='fixture')
    result=generate_answer(desk.wiki,{'id':'fake-answer-task','request':{'parameters':{'query_id':reading['id']},'budget_seconds':30}},lambda u:None,complete=model)
    request=AnswerInput.model_validate({**result['wiki_answer'],'save_proposal':True})
    saved=save_answer(desk.wiki,request)
    with desk.store.connect() as db:proposal=get(db,'proposals',saved['proposal_id'])
    revision=proposal['request']['changes'][0]
    assert revision['id']==draft.id and revision['expected_version']==1
    assert revision['content'].startswith(draft.content)
    assert len(revision['numeric_assertions'])==2
    duplicate=save_answer(desk.wiki,request.model_copy(update={'operation_id':'duplicate-answer'}))
    assert duplicate['proposal_id']==saved['proposal_id']
    desk.wiki.review(proposal['id'],DecisionRecord(operation_id='answer-adoption',digest=proposal['digest'],action='adopt',reason='fixture'))
    with pytest.raises(Conflict):
        save_answer(desk.wiki,request.model_copy(update={'operation_id':'stale-answer','content':request.content+'进一步研究。'}))


def test_history_workspace_does_not_expose_future_pages_jobs_or_policy(lab):
    before='2000-01-01T00:00:00+00:00'
    created=lab.jobs.create(WikiJobRequest(operation_id='history-job',company='TEST'))
    from pitr.wiki.workspace import workspace,page
    view=workspace(lab.wiki,'TEST',before)
    assert not view['pages'] and not view['jobs'] and view['policy'] is None and view['schedule'] is None
    with pytest.raises(KeyError):page(lab.wiki,'policy:company-research',as_of=before)


def test_no_change_requires_full_coverage_and_preserves_quiet_schedule(lab,monkeypatch):
    def complete_discovery(wiki,task,context,timeout,checkpoint):
        result=lab.discover(wiki,task,context,timeout,checkpoint)
        for need in context['needs']:
            if need['id'].startswith('quarter'):
                result['candidates'].append({**result['candidates'][0], 'url':'https://issuer.example.com/'+need['period'], 'title':need['period'], 'period':need['period'], 'needs':[need['id']]})
        return result
    monkeypatch.setattr('pitr.wiki.jobs.discover',complete_discovery)
    initial=lab.jobs.create(WikiJobRequest(operation_id='complete-build',company='TEST',years=1,quarters=1));lab.queue.run_one()
    first=lab.jobs.get(initial['id'])
    assert first['execution_status']=='completed'
    with lab.wiki.store.connect() as db:p=get(db,'proposals',first['proposal_id'])
    lab.wiki.review(p['id'],DecisionRecord(operation_id='complete-adopt',digest=p['digest'],action='adopt',reason='fixture'))
    update=lab.jobs.create(WikiJobRequest(operation_id='complete-update',company='TEST',intent='update',years=1,quarters=1),notification_event_id='fixture-schedule-notification');lab.queue.run_one()
    result=lab.jobs.get(update['id'])
    assert result['execution_status']=='completed' and not result['proposal_id']
    with lab.wiki.store.connect() as db:
        task=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(result['task_id'],)).fetchone()[0])
        assert task['result']['no_change'] is True
        assert not db.execute("SELECT 1 FROM wiki_outbox WHERE kind='slack'").fetchone()


def test_failed_parse_resumes_from_saved_bytes_without_redownload(lab,monkeypatch):
    from pitr.desk import sources
    original=sources.parse_document
    def interrupted(raw,media,url,*args,**kwargs):
        if 'news.' in url:raise ValueError('fixture parser interrupted')
        return original(raw,media,url,*args,**kwargs)
    monkeypatch.setattr(sources,'parse_document',interrupted)
    job=lab.jobs.create(WikiJobRequest(operation_id='parser-first',company='TEST',years=1,quarters=1));lab.queue.run_one()
    first=lab.jobs.get(job['id']);failed=next(m for m in first['materials'] if m['status']=='failed')
    assert failed['payload_object'] and lab.wiki.objects.get(failed['payload_object'])
    monkeypatch.setattr(sources,'parse_document',original)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public',lambda *a,**kw:pytest.fail('saved bytes must be reused'))
    resumed=lab.jobs.create(WikiJobRequest(operation_id='parser-resume',company='TEST',years=1,quarters=1,resume_job_id=first['id']));lab.queue.run_one()
    result=lab.jobs.get(resumed['id'])
    assert len([m for m in result['materials'] if m.get('source_id')])==3 and not result['failures']


def test_issuer_alias_and_period_coverage_are_independent(lab,monkeypatch):
    def discovery(*args,**kwargs):
        result=lab.discover(*args,**kwargs)
        result['candidates'][0]['subject']='Test Issuer'
        return result
    monkeypatch.setattr('pitr.wiki.jobs.discover',discovery)
    j=lab.jobs.create(WikiJobRequest(operation_id='alias-period',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result=lab.jobs.get(j['id'])
    assert result['materials'][0]['provider']=='official' and result['materials'][0]['subject_company']=='TEST'
    assert next(c for c in result['coverage'] if c['id'].startswith('quarter:'))['status']=='gap'
    assert next(c for c in result['checks'] if c['kind']=='publication')['status']=='passed'


def test_slack_build_attachments_join_one_batch_and_answer_can_write_back(lab):
    from pitr.desk.slack_adapter import DeskAdapter
    from pitr.integrations.slack import InboundEvent,ReplyTarget
    from pitr.integrations.slack.contracts import AttachmentRef
    class Context:
        def __init__(self):self.messages=[]
        def prepare(self,fn):return fn()
        def publish(self,key,update,**kwargs):self.messages.append(update)
        def bind(self,tid):pass
        def attachment_bytes(self,aid):return b'Business investment, margins and cash conversion require evidence. This attachment is a research lead, not an official disclosure.'
        def action(self,name,metadata):return 'fixture-action'
    context=Context();adapter=DeskAdapter(lab.desk,lab.queue)
    target=ReplyTarget(team_id='T1',channel_id='D1',user_id='U1',thread_ts='thread1')
    event=InboundEvent(id='wiki-attachment-build',kind='message',text='构建 TEST Wiki，研究利润率并参考附件',target=target,
        attachments=[AttachmentRef(id='attachment_fixture',file_id='F1',name='research.txt',media_type='text/plain',status='ready')])
    adapter.handle(event,context)
    job=lab.jobs.list('TEST')[0]
    assert len(job['request']['source_ids'])==1
    with lab.wiki.store.connect() as db:
        assert not db.execute("SELECT 1 FROM wiki_outbox WHERE kind='compile'").fetchone()
    lab.queue.run_one();result=lab.jobs.get(job['id'])
    assert any(m['status']=='provided' and m['provider']=='slack' for m in result['materials'])
    with lab.wiki.store.connect() as db:p=get(db,'proposals',result['proposal_id'])
    lab.wiki.review(p['id'],DecisionRecord(operation_id='fixture-attachment-adopt',digest=p['digest'],action='adopt',reason='fixture'))
    from pitr.wiki.research import query
    reading=query(lab.wiki,QueryInput(operation_id='slack-answer-query',company='TEST',question='竞争如何影响业务？'))
    used=next(r for r in reading['items'] if r['page_type']=='company')
    task={'id':'fixture-slack-answer','status':'completed','request':{'workflow':'wiki_answer','parameters':{'query_id':reading['id']}},
        'result':{'answer':{'title':'竞争与业务','content':'现有证据支持继续研究投入与竞争，仍需核验因果关系。','used':[{'id':used['id'],'version':used['version']}],'citations':used['citations'],'numeric_assertions':[]}}}
    with lab.wiki.store.connect(write=True) as db:db.execute('INSERT INTO tasks(id,status,body) VALUES(?,?,?)',(task['id'],'completed',canonical(task)))
    action=InboundEvent(id='save-answer',kind='action',target=target,action_id='wiki_save',metadata={'task_id':task['id']})
    modal=adapter.open_modal(action,context)
    submission=action.model_copy(update={'kind':'submission','action_id':modal.action_id,'values':{'writeback':{'value':{'selected_option':{'value':'analysis'}}}}})
    assert not adapter.validate_submission(submission)
    adapter.handle(submission,context)
    assert '修订草稿' in context.messages[-1].text
    assert not any(r['page_type']=='analysis' for r in lab.wiki.list('TEST') if r['kind']=='page')


def test_wrong_period_in_discovered_official_source_keeps_original_but_blocks_evidence(lab,monkeypatch):
    def discovery(*args,**kwargs):
        result=lab.discover(*args,**kwargs)
        result['candidates'][0]['period']='2026Q2'
        return result
    def fetch(url,timeout):
        raw,media,final,receipt=lab.fetch(url,timeout)
        if 'issuer.' in url:raw=b'TEST Announces First Quarter 2026 Results\n\n'+raw
        return raw,media,final,receipt
    monkeypatch.setattr('pitr.wiki.jobs.discover',discovery);monkeypatch.setattr('pitr.wiki.jobs.fetch_public',fetch)
    j=lab.jobs.create(WikiJobRequest(operation_id='wrong-period',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result=lab.jobs.get(j['id']);material=result['materials'][0]
    assert material['status']=='failed' and '期间' in material['error'] and not material.get('source_id')
    assert lab.wiki.objects.get(material['payload_object'])


def test_retry_receipts_and_failure_status_remain_available(monkeypatch):
    from pitr.wiki.discovery import fetch_public
    import httpx,socket
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('8.8.8.8',443))])
    calls=[]
    def serve(request):
        calls.append(request.url)
        return httpx.Response(503 if len(calls)==1 else 200,content=b'Public original')
    client=httpx.Client(transport=httpx.MockTransport(serve))
    raw,_,_,receipts=fetch_public('https://example.com/report',client=client)
    assert raw==b'Public original' and [r['status'] for r in receipts]==[503,200]
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(403)))
    with pytest.raises(ValueError) as caught:fetch_public('https://example.com/blocked',client=client)
    assert caught.value.receipts[0]['status']==403


def test_repeated_update_reuses_current_pending_batch(lab):
    first=lab.jobs.create(WikiJobRequest(operation_id='pending-first',company='TEST',years=1,quarters=1));lab.queue.run_one()
    original=lab.jobs.get(first['id'])
    second=lab.jobs.create(WikiJobRequest(operation_id='pending-check',company='TEST',intent='update',years=1,quarters=1),notification_event_id='fixture-repeat');lab.queue.run_one()
    again=lab.jobs.get(second['id'])
    assert again['proposal_id']==original['proposal_id'] and again['publication_status']=='waiting_review'
    with lab.wiki.store.connect() as db:
        assert len(state(db,'proposals'))==1
        assert not db.execute("SELECT 1 FROM wiki_outbox WHERE kind='slack'").fetchone()

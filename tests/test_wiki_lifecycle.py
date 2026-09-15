"""Frozen, synthetic PDD quarters exercise the whole knowledge lifecycle.

These are software acceptance fixtures, not actual company disclosures or human
utility results. No test invokes a remote model, installs global hooks or sends Slack.
"""
import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pitr.desk.service import Desk
from pitr.desk.sources import parse_document
from pitr.desk.storage import canonical, Conflict
from pitr.desk.contracts import Citation, Metric
from pitr.wiki.contracts import *
from pitr.wiki.store import state, get, reduce_event
from pitr.wiki.search import search, rrf


@pytest.fixture
def lab(tmp_path, monkeypatch):
    clock = ['2025-06-01T12:00:00+00:00']
    monkeypatch.setattr('pitr.wiki.service.utcnow', lambda: clock[0])
    desk = Desk(tmp_path / 'desk')
    raw = b'Synthetic software acceptance fixture.\n\nInvestment remains elevated while transaction service revenue grows.'
    doc = parse_document(raw, 'text/plain', 'https://investor.pddholdings.com/wiki-fixture-q1', 'PDD', 'PDD synthetic first quarter', observed_at='2025-05-01T00:00:00+00:00')
    (desk.files/doc.file_name).write_bytes(raw)
    desk.put_document(doc)
    citation = Citation(source_id=doc.id, block_id=doc.blocks[-1].id, quote=doc.blocks[-1].text)
    return SimpleNamespace(desk=desk, wiki=desk.wiki, clock=clock, doc=doc, citation=citation)


def draft(lab, identity='knowledge:PDD:margin', **kwargs):
    return RevisionDraft(id=identity, kind='knowledge', nature='interpretation', title='利润率持续性',
        content='投入增加可能压低短期利润率，仍需检查后续披露。', scope='当前公司披露的经营活动',
        citations=[lab.citation], reason='比较原始披露及替代解释', **kwargs)


def proposal(lab, changes=None, **kwargs):
    return lab.wiki.propose(ProposalInput(operation_id='proposal-'+__import__('uuid').uuid4().hex,
        company='PDD', policy=Reference(id=lab.wiki.policy()['id'],version=lab.wiki.policy()['version']),
        changes=changes or [draft(lab)], reason='完整研究变更', **kwargs))


def adopt(lab, p, **kwargs):
    return lab.wiki.review(p['id'], DecisionRecord(operation_id='review-'+__import__('uuid').uuid4().hex,
        digest=p['digest'], action='adopt', reason='人工核对原文和限制条件'), **kwargs)


def rev(lab, identity='knowledge:PDD:margin'):
    return next(r for r in lab.wiki.list() if r['id']==identity)


def test_two_quarter_lifecycle_rebuild_and_point_in_time(lab):
    knowledge = draft(lab)
    source = RevisionDraft(id='source:PDD:q1', kind='page', page_type='source', title='第一季披露解读',
        content='披露说明了投入变化，没有单独披露跨境业务利润。', citations=[lab.citation], reason='说明材料及边界')
    company = RevisionDraft(id='company:PDD', kind='page', page_type='company', title='PDD 公司研究',
        content='利润率变化需结合投入与收入结构判断。', summary='公司经营与研究问题的持续目录。',
        citations=[lab.citation], relations=[Relation(target=Reference(id=knowledge.id,version=1),relation='derived_from')], reason='更新公司认识')
    p = proposal(lab, [knowledge,source,company]); adopt(lab,p)
    first = copy.deepcopy(lab.wiki.list())
    assert len([r for r in first if r['kind']!='policy'])==3
    assert all(r['policy']['version']==1 for r in first if r['kind']!='policy')
    reference={'id':knowledge.id,'version':1}
    assert lab.wiki.validate_use('PDD',[reference])['valid']
    assert not lab.wiki.validate_use('BABA',[reference])['valid']
    from pitr.wiki.research import query,save_answer
    # Research use is timestamped now, never retroactively made an old summary.
    q=query(lab.wiki,QueryInput(operation_id='query-first-quarter',company='PDD',question='利润率持续性'))
    answer=save_answer(lab.wiki,AnswerInput(operation_id='answer-first-quarter',query_id=q['id'],title='利润率两种解释',
        content='投入解释与收入结构解释均需要后续证据，当前不作单一归因。',used=[Reference(id=knowledge.id,version=1)],citations=[lab.citation]))
    assert answer['proposal_id']
    duplicate=save_answer(lab.wiki,AnswerInput(operation_id='answer-first-duplicate',query_id=q['id'],title='相同分析',
        content='投入解释与收入结构解释均需要后续证据，当前不作单一归因。',used=[Reference(id=knowledge.id,version=1)],citations=[lab.citation]))
    assert duplicate['duplicate_of']==answer['id']
    assert duplicate['proposal_id']==answer['proposal_id']
    lab.clock[0]='2025-09-01T12:00:00+00:00'
    raw=b'Synthetic second quarter fixture.\n\nMargin pressure also reflects revenue mix, not only investment.'
    doc=parse_document(raw,'text/plain','https://investor.pddholdings.com/wiki-fixture-q2','PDD','PDD synthetic second quarter',observed_at='2025-08-01T00:00:00+00:00')
    (lab.desk.files/doc.file_name).write_bytes(raw);lab.desk.put_document(doc)
    issue=lab.wiki.report(IssueInput(operation_id='report-overstatement',target=Reference(id=knowledge.id,version=1),
        issue_type='semantic',paragraph='压低短期利润率',description='旧解释可能忽略收入结构变化'))
    assert 'company:PDD@v1' in issue['impacts']
    assert any(k.startswith('use:') for k in issue['impacts'])
    assert rev(lab)['availability']=='disputed'
    revised=knowledge.model_copy(update={'expected_version':1,'content':'投入和收入结构共同影响利润率，现有证据尚不能识别各自贡献。',
        'citations':[Citation(source_id=doc.id,block_id=doc.blocks[-1].id,quote=doc.blocks[-1].text)],
        'corrects':Reference(id=knowledge.id,version=1),'change_type':'correction'})
    revised_company=company.model_copy(update={'expected_version':1,'content':'研究同时追踪投入与收入结构，旧的单一解释已修订。',
        'citations':revised.citations,'relations':[Relation(target=Reference(id=knowledge.id,version=2),relation='derived_from')]})
    adopt(lab,proposal(lab,[revised,revised_company],issue_ids=[issue['id']]))
    assert rev(lab)['version']==2
    with pytest.raises(Conflict,match='下游'):
        lab.wiki.issue_decision(issue['id'],IssueDecision(operation_id='close-too-early',action='resolve',reason='修订已发'))
    for n,target in enumerate(issue['impacts']):
        lab.wiki.issue_decision(issue['id'],IssueDecision(operation_id='impact-'+str(n),action='impact',reason='已核对修订，历史报告显示提示',target=target,disposition='reviewed_unchanged'))
    closed=lab.wiki.issue_decision(issue['id'],IssueDecision(operation_id='close-fully-handled',action='resolve',reason='内容与传播影响均已处理'))
    assert closed['state']=='closed'
    historical=lab.wiki.list('PDD','2025-07-01T00:00:00+00:00')
    old=next(r for r in historical if r['id']==knowledge.id)
    assert old['version']==1 and old['availability']=='available'
    assert not lab.wiki.validate_use('PDD',[reference])['valid']
    assert lab.wiki.validate_use('PDD',[reference],'2025-07-01T00:00:00+00:00')['valid']
    lifecycle_types={event['kind'] for event in lab.wiki.history(knowledge.id)['events']}
    assert {'source.ingested','proposal.created','proposal.adopted','query.answered'}.issubset(lifecycle_types)
    assert not lab.wiki.list('PDD','2025-05-15T00:00:00+00:00')
    assert search(lab.wiki,'PDD','利润率',as_of='2025-07-01T00:00:00+00:00')['items'][0]['version']==1
    lab.wiki.render()
    before_manifest=json.loads((lab.wiki.markdown/'manifest.json').read_text())['files']
    with lab.desk.store.connect() as db:
        before=state(db);outbox=[dict(r) for r in db.execute('SELECT * FROM wiki_outbox')]
    rebuilt=lab.wiki.rebuild()
    with lab.desk.store.connect() as db:
        assert state(db)==before
        assert [dict(r) for r in db.execute('SELECT * FROM wiki_outbox')]==outbox
    assert rebuilt['external_effects']==0
    assert json.loads((lab.wiki.markdown/'manifest.json').read_text())['files']==before_manifest


def test_atomic_stale_and_concurrent_publish(lab):
    p1=proposal(lab);p2=proposal(lab)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda p: _try_adopt(lab,p),[p1,p2]))
    assert sorted(results)==['adopted','conflict']
    bad=RevisionDraft(id='page:PDD:bad',kind='page',page_type='topic',title='无效页',content='没有引文',reason='测试')
    with pytest.raises(ValueError):proposal(lab,[draft(lab,expected_version=1),bad])
    assert not any(r['id']==bad.id for r in lab.wiki.list())
    assert len(lab.wiki.history('knowledge:PDD:margin')['versions'])==1


def _try_adopt(lab,p):
    try:adopt(lab,p);return 'adopted'
    except Conflict:return 'conflict'


def test_policy_change_stales_proposal_and_triggers_review(lab):
    adopt(lab,proposal(lab));pending=proposal(lab,[draft(lab,expected_version=1)])
    policy=lab.wiki.policy()
    change=RevisionDraft(id=policy['id'],kind='policy',expected_version=1,title=policy['title'],content=policy['content']+'\n所有专题补充竞争性解释。',reason='加强专题维护')
    adopt(lab,proposal(lab,[change]))
    with pytest.raises(Conflict,match='规范'):adopt(lab,pending)
    assert rev(lab)['availability']=='needs_review'
    assert lab.wiki.policy()['version']==2


def test_hard_error_quarantine_is_reproduced_not_claimed(lab):
    adopt(lab,proposal(lab))
    false=lab.wiki.report(IssueInput(operation_id='false-citation-error',target=Reference(id='knowledge:PDD:margin',version=1),issue_type='citation',description='我认为引文不存在'))
    assert not false['confirmed_hard_error'] and rev(lab)['availability']=='disputed'
    lab.wiki.issue_decision(false['id'],IssueDecision(operation_id='dismiss-false-alarm',action='dismiss',reason='原文段落存在，已核对'))
    assert rev(lab)['availability']=='available'
    obj=lab.wiki.objects.path(lab.doc.digest);original=obj.read_bytes();obj.write_bytes(b'corrupt bytes')
    issue=lab.wiki.report(IssueInput(operation_id='real-object-error',target=Reference(id='knowledge:PDD:margin',version=1),issue_type='object',description='原件摘要损坏'))
    assert issue['confirmed_hard_error'] and rev(lab)['availability']=='quarantined'
    assert search(lab.wiki,'PDD','利润率')['items']==[]
    with pytest.raises(Conflict):lab.wiki.issue_decision(issue['id'],IssueDecision(operation_id='cannot-dismiss-corruption',action='dismiss',reason='暂时忽略'))
    obj.write_bytes(original)
    lab.wiki.issue_decision(issue['id'],IssueDecision(operation_id='repaired-backup',action='dismiss',reason='从已验证备份恢复原始字节'))
    assert rev(lab)['availability']=='available'


def test_source_withdrawal_and_unrelated_links(lab):
    parent=draft(lab)
    child=RevisionDraft(id='page:PDD:related',kind='page',page_type='topic',title='仅相关',content='另一个独立问题。',citations=[lab.citation],relations=[Relation(target=Reference(id=parent.id,version=1),relation='related')],reason='用于导航')
    adopt(lab,proposal(lab,[parent,child]))
    issue=lab.wiki.report(IssueInput(operation_id='semantic-parent',target=Reference(id=parent.id,version=1),issue_type='semantic',description='需要核对解释'))
    assert 'page:PDD:related@v1' not in issue['impacts']
    assert rev(lab,child.id)['availability']=='available'
    lab.desk.withdraw(lab.doc.id)
    with pytest.raises(Conflict):proposal(lab,[draft(lab,expected_version=1)])
    assert rev(lab)['availability']=='needs_review'


def test_causal_relation_directions_and_true_cycles(lab):
    upstream=draft(lab)
    child=RevisionDraft(id='topic:PDD:causal',kind='page',page_type='topic',title='依赖知识的专题',
        content='综合已披露证据与解释。',citations=[lab.citation],reason='研究综合',
        relations=[Relation(target=Reference(id=upstream.id,version=1),relation='derived_from')])
    upstream.relations=[Relation(target=Reference(id=child.id,version=1),relation='supports'),
                        Relation(target=Reference(id=child.id,version=1),relation='used_in')]
    adopt(lab,proposal(lab,[upstream,child]))
    with lab.desk.store.connect() as db:
        assert child.id+'@v1' in lab.wiki._downstream(db,upstream.id+'@v1')
        assert upstream.id+'@v1' not in lab.wiki._downstream(db,child.id+'@v1')
    # Following an older revision is acyclic even if the stable identities link back.
    newer=upstream.model_copy(update={'expected_version':1,'relations':[Relation(target=Reference(id=child.id,version=1),relation='derived_from')]})
    proposal(lab,[newer])
    reverse=child.model_copy(update={'id':'topic:PDD:cycle','relations':[Relation(target=Reference(id='knowledge:PDD:cycle',version=1),relation='supports')]})
    cyclic=draft(lab,identity='knowledge:PDD:cycle').model_copy(update={'relations':[Relation(target=Reference(id=reverse.id,version=1),relation='supports')]})
    with pytest.raises(ValueError,match='循环'):
        proposal(lab,[cyclic,reverse])


def test_captures_identity_content_revisions_and_no_fact_promotion(lab):
    request=CaptureEnvelope(operation_id='capture-slack-original',provider='slack',external_id='team:channel:ts',company='PDD',title='PDD 利润率讨论',text='PDD 利润率下降可能来自投入。')
    result=lab.wiki.capture(request)
    assert lab.wiki.capture(request)==result
    dup=lab.wiki.capture(request.model_copy(update={'operation_id':'capture-slack-retry'}))
    assert dup['status']=='duplicate'
    other=lab.wiki.capture(request.model_copy(update={'operation_id':'capture-claude-copy','provider':'claude'}))
    assert other['id']!=result['id']
    with lab.desk.store.connect() as db:
        a=get(db,'sources',result['id']);b=get(db,'sources',other['id'])
        assert a['payload_object']==b['payload_object']
    false_fact=draft(lab).model_copy(update={'nature':'fact','citations':[Citation(source_id=result['id'],block_id='text',quote=request.text)]})
    with pytest.raises(ValueError,match='公司披露事实'):proposal(lab,[false_fact])
    revised=lab.wiki.capture(request.model_copy(update={'operation_id':'capture-slack-edited','action':'revise','text':'PDD 利润率变化需结合收入结构。'}))
    with lab.desk.store.connect() as db:
        assert get(db,'sources',result['id'])['state']=='superseded'
        assert get(db,'sources',revised['id'])['revision_of']==result['id']
    lab.wiki.capture(request.model_copy(update={'operation_id':'capture-slack-deleted','action':'withdraw'}))
    with lab.desk.store.connect() as db:assert get(db,'sources',revised['id'])['state']=='withdrawn'
    assert lab.wiki.capture(request.model_copy(update={'operation_id':'capture-self-echo','origin':'pitr-wiki'}))['status']=='ignored_echo'
    attachment=lab.wiki.objects.put(b'PDD original attachment')
    attached=request.model_copy(update={'operation_id':'capture-with-attachment','external_id':'team:channel:attachment','attachments':[attachment]})
    initial=lab.wiki.capture(attached)
    changed_attachment=lab.wiki.objects.put(b'PDD revised original attachment')
    changed=lab.wiki.capture(attached.model_copy(update={'operation_id':'capture-attachment-edit','action':'revise','attachments':[changed_attachment]}))
    assert changed['status']=='captured' and changed['id']!=initial['id']
    with lab.desk.store.connect() as db:
        assert get(db,'sources',changed['id'])['revision_of']==initial['id']
    attachment_draft=draft(lab).model_copy(update={'citations':[Citation(source_id=changed['id'],block_id='text',quote=request.text)]})
    proposal(lab,[attachment_draft])
    lab.wiki.objects.path(changed_attachment).write_bytes(b'corrupted attachment')
    with pytest.raises(ValueError,match='摘要校验失败'):
        proposal(lab,[attachment_draft])


def test_cas_reducer_and_append_only_guard(lab):
    sha=lab.wiki.objects.put(b'content');assert len(sha)==64
    assert lab.wiki.objects.get(sha)==b'content'
    with pytest.raises(ValueError):lab.wiki.objects.get('../../secret')
    initial={'status':{'x':{'availability':'available'}}}
    event={'changes':[{'bucket':'status','key':'x','value':{'availability':'withdrawn'}}]}
    reduced=reduce_event(initial,event)
    assert initial['status']['x']['availability']=='available'
    assert reduced['status']['x']['availability']=='withdrawn'
    with lab.desk.store.connect(write=True) as db:
        with pytest.raises(Exception,match='append-only'):db.execute('DELETE FROM wiki_events')


def test_markdown_export_with_relative_desk_path(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    desk=Desk(Path('relative desk'))
    rendered=desk.wiki.render()
    assert Path(rendered['path']).is_absolute()
    assert (Path(rendered['path'])/'index.md').is_file()
    assert desk.wiki.markdown.is_symlink()


def test_chinese_search_company_filter_and_optional_fallback(lab):
    adopt(lab,proposal(lab))
    found=search(lab.wiki,'PDD','利润率')
    assert found['items'][0]['id']=='knowledge:PDD:margin'
    assert search(lab.wiki,'BABA','利润率')['items']==[]
    fallback=search(lab.wiki,'PDD','利润率',hybrid=True)
    assert fallback['mode']=='bm25' and fallback['warnings'] and fallback['items']
    ranks,scores=rrf(['a','b','a'],['b','c'])
    assert ranks[0]=='b' and scores['b']==pytest.approx(1/62+1/61)


def test_hooks_reversible_paths_spaces_and_durable_capture(lab,tmp_path):
    from pitr.wiki.hooks import install,config_path
    from pitr.wiki.capture import enqueue,connection
    project=tmp_path/'project with spaces';project.mkdir()
    for provider in ('claude','codex'):
        path=config_path(provider,project=project);path.parent.mkdir(exist_ok=True)
        own={'hooks':[{'type':'command','command':'echo existing'}]}
        path.write_text(json.dumps({'custom':'keep','hooks':{'Stop':[own]}}))
        installed=install(provider,lab.desk.root,project=project)
        assert installed['changed']
        assert not install(provider,lab.desk.root,project=project)['changed']
        config=json.loads(path.read_text());assert config['hooks']['Stop'][0]==own
        import shlex
        command=config['hooks']['Stop'][-1]['hooks'][0]['command']
        event={'hook_event_name':'Stop','session_id':'same-session','turn_id':'same-turn','last_assistant_message':'PDD revenue research margin pressure.','reasoning':'hidden reasoning must not persist','transcript_path':'never read this'}
        for _ in range(2):
            proc=subprocess.run(shlex.split(command),input=json.dumps(event),capture_output=True,text=True)
            assert proc.returncode==0 and proc.stdout.strip()=='{}'
        install(provider,lab.desk.root,project=project,uninstall=True)
        assert json.loads(path.read_text())['hooks']=={'Stop':[own]}
    db=connection(lab.desk.root)
    rows=db.execute('SELECT * FROM captures').fetchall();db.close()
    assert len(rows)==2
    assert all('hidden reasoning' not in r['body'] and 'transcript_path' not in r['body'] for r in rows)
    enqueue(lab.desk.root,'claude',{'hook_event_name':'Stop','session_id':'other','last_assistant_message':'Fix compiler typescript bug'})
    db=connection(lab.desk.root);assert db.execute("SELECT COUNT(*) FROM captures WHERE status='excluded'").fetchone()[0]==1;db.close()


def test_offline_spool_recovers_without_duplicate_knowledge(lab):
    from pitr.wiki.capture import enqueue,connection
    from pitr.wiki.worker import Worker
    from pitr.desk.tasks import Queue
    payload={'hook_event_name':'Stop','session_id':'finance-session','turn_id':'t1','last_assistant_message':'PDD revenue margin financial investigation.'}
    enqueue(lab.desk.root,'codex',payload)
    worker=Worker(lab.wiki,Queue(lab.desk));worker.drain_capture();worker.drain_capture()
    with lab.desk.store.connect() as db:
        captures=[s for s in state(db,'sources').values() if s['provider']=='codex']
        assert len(captures)==1
        assert not state(db,'proposals')
    for _ in range(4):worker.relay_one()
    with lab.desk.store.connect() as db:
        tasks=[json.loads(r['body']) for r in db.execute('SELECT body FROM tasks')]
        assert len([t for t in tasks if t['request']['workflow']=='wiki_compile'])==1


def test_numeric_bindings_require_scope_and_calculation(lab):
    with lab.desk.store.connect(write=True) as db:
        m=Metric(id='metric-revenue',name='revenue',label='收入',period='2025Q1',value=100,unit='RMB_mn',citation=lab.citation)
        db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,'PDD',lab.doc.id,canonical(m)))
    numeric=draft(lab).model_copy(update={'content':'收入为 100。'})
    with pytest.raises(ValueError,match='数字'):proposal(lab,[numeric])
    binding={'field':'content','start':4,'end':7,'observation_id':m.id,'name':m.name,'value':m.value,'unit':m.unit,'period':m.period,'basis':m.basis}
    numeric=numeric.model_copy(update={'numeric_assertions':[binding]})
    adopt(lab,proposal(lab,[numeric]))
    wrong=numeric.model_copy(update={'expected_version':1,'numeric_assertions':[{**binding,'period':'2024Q1'}]})
    with pytest.raises(ValueError,match='期间'):proposal(lab,[wrong])


def test_rule_inspection_does_not_invent_errors_and_records_budget(lab):
    from pitr.wiki.inspection import inspect
    adopt(lab,proposal(lab))
    run=inspect(lab.wiki,'PDD','rules')
    assert run['finished_at'] and len(run['scope'])==1 and not run['issues']
    def clean(*a,**kw):return SimpleNamespace(data={'findings':[]},provider='fixture',model='frozen')
    semantic=inspect(lab.wiki,'PDD','semantic',complete=clean,max_items=1)
    assert semantic['finished_at'] and len(semantic['scope'])==1 and not semantic['issues']


def test_agent_cannot_publish(lab):
    p=proposal(lab)
    with pytest.raises(PermissionError):adopt(lab,p,actor='agent')
    from pitr.desk.api import create_app
    with TestClient(create_app(lab.desk.root,worker=False)) as client:
        response=client.post('/api/desk/wiki/proposals/'+p['id']+'/review',json={'operation_id':'agent-no-adopt','digest':p['digest'],'action':'adopt','reason':'attempt'},headers={'x-pitr-actor':'agent'})
        assert response.status_code==403


def test_event_only_restore_preserves_numeric_evidence_and_cas(lab,tmp_path):
    from pitr.wiki.backup import backup
    adopt(lab,proposal(lab))
    before=lab.wiki.list()
    with lab.desk.store.connect() as db:sequence=db.execute('SELECT MAX(sequence) FROM wiki_events').fetchone()[0]
    destination=tmp_path/'verified-backup'
    result=backup(lab.wiki,destination)
    assert result['sequence']==sequence and (destination/'objects'/'sha256').is_dir()
    with lab.desk.store.connect(write=True) as db:db.execute('DELETE FROM wiki_state')
    recovered=Desk(lab.desk.root).wiki
    assert recovered.list()==before
    with lab.desk.store.connect() as db:assert db.execute('SELECT MAX(sequence) FROM wiki_events').fetchone()[0]==sequence
    with pytest.raises(ValueError):backup(recovered,destination)


def test_atomic_review_failure_rolls_back_all_pages(lab,monkeypatch):
    changes=[RevisionDraft(id='page:PDD:'+name,kind='page',page_type='topic',title=name,content='原始资料支持一个待检查问题。',citations=[lab.citation],reason='原子批次') for name in ('a','b')]
    p=proposal(lab,changes)
    original=lab.wiki.objects.json
    calls=[]
    def crash(revision):
        result=original(revision);calls.append(revision['id'])
        if len(calls)==2:raise RuntimeError('simulated crash before commit')
        return result
    monkeypatch.setattr(lab.wiki.objects,'json',crash)
    with pytest.raises(RuntimeError):adopt(lab,p)
    assert not [r for r in lab.wiki.list() if r['kind']=='page']
    with lab.desk.store.connect() as db:assert get(db,'proposals',p['id'])['status']=='pending'


def test_outbox_retries_same_batch_after_enqueue_crash(lab,monkeypatch):
    from pitr.wiki.worker import Worker
    from pitr.desk.tasks import Queue
    lab.wiki.capture(CaptureEnvelope(operation_id='another-capture',provider='manual',external_id='one',title='补充利润率研究',text='PDD 利润率研究',company='PDD'))
    queue=Queue(lab.desk);worker=Worker(lab.wiki,queue)
    enqueue=queue.enqueue
    def uncertain(request):
        result=enqueue(request)
        raise OSError('crash after durable task acceptance')
    monkeypatch.setattr(queue,'enqueue',uncertain)
    worker.relay_one();worker.relay_one()
    with lab.desk.store.connect(write=True) as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1
        db.execute("UPDATE wiki_outbox SET next_at=0 WHERE kind='compile' AND status='pending'")
    # A later capture must not change the frozen, already-accepted batch request.
    lab.wiki.capture(CaptureEnvelope(operation_id='capture-after-crash',provider='manual',external_id='two',title='后续现金流研究',text='PDD 现金流研究',company='PDD'))
    monkeypatch.setattr(queue,'enqueue',enqueue)
    for _ in range(5):worker.relay_one()
    with lab.desk.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==2
        assert not db.execute("SELECT 1 FROM wiki_outbox WHERE status IN ('pending','coalesced','sending')").fetchone()


def test_compile_and_generated_answer_are_reviewable_not_published(lab,monkeypatch):
    from pitr.wiki.worker import compile_sources
    from pitr.wiki.research import query,generate_answer,save_answer
    company=RevisionDraft(id='company:PDD',kind='page',page_type='company',title='公司页',content='研究利润率的持续性。',citations=[lab.citation],reason='更新公司认识')
    source=RevisionDraft(id='source-note:'+lab.doc.id,kind='page',page_type='source',title='来源解读',content='原件披露投入变化，仍有未知事项。',citations=[lab.citation],reason='解释材料')
    def complete(*args,**kwargs):
        from pitr.llm import strict_json_schema
        def check_strict(node):
            if isinstance(node,dict):
                if node.get('type')=='object':
                    assert node.get('additionalProperties') is False
                    assert set(node.get('required',[]))==set(node.get('properties',{}))
                for child in node.values():check_strict(child)
            elif isinstance(node,list):
                for child in node:check_strict(child)
        check_strict(strict_json_schema(args[1]))
        return SimpleNamespace(provider='fixture',model='frozen',data={'reason':'跨页面整理','changes':[c.model_dump(exclude={'numeric_assertions'}) for c in [draft(lab),company,source]]})
    task={'id':'fixture-compile','request':{'company':'PDD','parameters':{'source_ids':[lab.doc.id]},'budget_seconds':30}}
    result=compile_sources(lab.wiki,task,lambda u:None,complete=complete)
    p=lab.wiki.propose(ProposalInput.model_validate(result['wiki_proposal']))
    assert p['status']=='pending' and len(p['request']['changes'])==3
    assert len(lab.wiki.list())==1
    adopt(lab,p)
    reading=query(lab.wiki,QueryInput(operation_id='query-generated-answer',company='PDD',question='利润率'))
    def answer(*args,**kwargs):
        return SimpleNamespace(provider='fixture',model='frozen',data={'title':'两种解释','content':'投入和收入结构是并存的解释。',
            'used':[{'id':'knowledge:PDD:margin','version':1}],'citations':[lab.citation.model_dump()]})
    task={'id':'fixture-answer','request':{'parameters':{'query_id':reading['id']},'budget_seconds':30}}
    result=generate_answer(lab.wiki,task,lambda u:None,complete=answer)
    record=save_answer(lab.wiki,AnswerInput.model_validate(result['wiki_answer']))
    assert 'proposal_id' not in record
    saved=save_answer(lab.wiki,AnswerInput.model_validate({**result['wiki_answer'],'operation_id':'adopt-answer-as-draft','save_proposal':True}))
    assert saved['proposal_id']


def test_scheduler_coalesces_sleep_and_semantic_foreground_priority(lab):
    from pitr.wiki.worker import Worker
    from pitr.desk.tasks import Queue
    from pitr.desk.contracts import TaskInput
    from pitr.wiki.inspection import inspect
    adopt(lab,proposal(lab))
    queue=Queue(lab.desk);worker=Worker(lab.wiki,queue)
    worker.schedule(clock=1000);worker.schedule(clock=1000+86400*30);worker.schedule(clock=1000+86400*30)
    with lab.desk.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_outbox WHERE kind='inspect'").fetchone()[0]==2
    queue.enqueue(TaskInput(operation_id='foreground-priority',workflow='disclosures',company='PDD'))
    run=inspect(lab.wiki,'PDD','semantic',complete=lambda *a,**kw:pytest.fail('Must yield before model call'))
    assert not run['scope'] and run['skipped'][0]['reason']=='前台研究优先'


def test_hidden_reasoning_blocks_and_credentials_are_excluded(lab):
    from pitr.wiki.capture import enqueue,connection
    payload={'hook_event_name':'PostToolUse','session_id':'s','turn_id':'t','tool_use_id':'u','tool_name':'search',
        'tool_response':{'content':[{'type':'reasoning','text':'private hidden reasoning'}, {'type':'text','text':'PDD revenue margin research sk-abcdefghijklmnop'}],
                         'api_key':'must never persist'}}
    enqueue(lab.desk.root,'codex',payload)
    db=connection(lab.desk.root)
    row=db.execute('SELECT body FROM captures').fetchone();db.close()
    assert all(v not in row['body'] for v in ('private hidden reasoning','sk-abcdefghijklmnop','must never persist'))


def test_numeric_projection_rebuild_without_mutable_metric_table(lab):
    with lab.desk.store.connect(write=True) as db:
        metric=Metric(id='frozen-revenue',name='revenue',label='收入',value=100,unit='RMB_mn',period='2025Q1',citation=lab.citation)
        db.execute('INSERT INTO observations VALUES(?,?,?,?)',(metric.id,'PDD',lab.doc.id,canonical(metric)))
    item=draft(lab).model_copy(update={'content':'收入为 100。','numeric_assertions':[{'field':'content','start':4,'end':7,
        'observation_id':metric.id,'name':metric.name,'value':metric.value,'unit':metric.unit,'period':metric.period,'basis':metric.basis}]})
    adopt(lab,proposal(lab,[item]))
    with lab.desk.store.connect(write=True) as db:db.execute('DELETE FROM observations')
    lab.wiki.rebuild()
    assert search(lab.wiki,'PDD','收入')['items'][0]['version']==1


def test_inspection_feedback_requires_real_review_and_is_not_overwritten(lab):
    from pitr.wiki.inspection import inspect
    from pitr.wiki.evaluation import record_feedback,inspection_metrics
    adopt(lab,proposal(lab))
    run=inspect(lab.wiki,'PDD','rules')
    feedback=InspectionFeedback(operation_id='human-inspection-feedback',reviewed_all=True,false_positives=0,missed_issues=1,review_minutes=4.5,note='人工逐项核对后，发现一处遗漏的适用限制')
    saved=record_feedback(lab.wiki,run['id'],feedback)
    assert saved['feedback']['review_minutes']==4.5
    metrics=inspection_metrics(lab.wiki,'PDD')
    assert metrics['human_rework_minutes']==4.5 and metrics['missed_issue_rate']==1.0
    assert record_feedback(lab.wiki,run['id'],feedback)==saved
    with pytest.raises(ValueError):record_feedback(lab.wiki,run['id'],feedback.model_copy(update={'operation_id':'different-feedback'}))
    from pitr.desk.api import create_app
    with TestClient(create_app(lab.desk.root,worker=False)) as client:
        assert client.get('/openapi.json').status_code==200

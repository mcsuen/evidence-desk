import pytest
from fastapi.testclient import TestClient
from pitr.adapters.api import create_app
from pitr.application.trace import span, trace_view
from pitr.application.views import company_view
from pitr.domain.common import Forbidden, utcnow
from pitr.domain.contracts import Ref, Scope, ContinueRun, Decide, ExportRequest, CreateCase, StartRun
from conftest import report_fixture


def test_trace_records_parent_failures_duplicate_and_cancel_without_business_writes(running):
    station, source, run, queue, tools, token, call = running
    with span(station.store, run, '真实工具边界测试', 'agent') as (parent, _):
        linked = tools.issue(run.id, run.generation, parent_span=parent)
        request = {'operation_id':'same-read','name':'context','arguments':{}}
        first = tools.call(linked, request)
        assert tools.call(linked, request) == first
        with pytest.raises(KeyError):
            tools.call(linked, {'operation_id':'bad-read','name':'source.read','arguments':{'ref':source.ref.model_dump(),'block_id':'absent'}})
        station.cancel(run.id, 'cancel')
        with pytest.raises(Forbidden):tools.call(linked, request)
    view = trace_view(station, run.id)
    children = [s for s in view.spans if s.parent_id == parent]
    assert len(children) == 4 and all(s.duration_ms is not None for s in children)
    assert len([s for s in children if s.status == 'completed']) == 2
    assert any(s.metadata.get('rejected') for s in children)
    assert station.get_run(run.id).tool_calls == 1
    assert station.get_run(run.id).status == 'cancelled'
    replay = trace_view(station, run.id, children[0].first_seq)
    observed = next(s for s in replay.spans if s.id == children[0].id)
    assert observed.ended_at is None and observed.duration_ms is None
    assert not observed.artifact_refs and not observed.metadata.get('error')
    assert replay.summary.active_seconds is None
    assert replay.task_status == 'running'


def test_trace_generation_recovery_and_api_contract(running):
    station, source, run, queue, tools, token, call = running
    station.cancel(run.id, 'cancel-for-resume')
    station.continue_run(run.id, ContinueRun(operation_id='resume', expected_generation=run.generation))
    newer = queue.claim('local')
    assert newer.generation > run.generation
    view = trace_view(station, run.id)
    assert any(link.kind == 'recovery' for link in view.links)
    client = TestClient(create_app(station.root, station=station, workers=False))
    response = client.get('/api/v1/runs/'+run.id+'/trace')
    assert response.status_code == 200 and response.json()['version'] == 'trace.1'
    rows = client.get('/api/v1/runs/'+run.id+'/trace/records').json()
    assert rows and all(r['seq'] <= response.json()['latest_seq'] for r in rows)
    assert client.get('/api/v1/runs/'+run.id+'/trace?at_seq=-1').status_code == 422
    assert client.get('/api/v1/runs/unknown/trace/events').status_code == 404


def test_cancel_before_first_claim_is_still_a_continuation(running):
    station, source, original, queue, *_ = running
    station.cancel(original.id, 'stop-first')
    case=station.create_case(CreateCase(operation_id='queued-case',question='queued cancel fixture',scope=Scope(subjects=['PDD']),sources=[source.ref]))
    run=station.start_run(case['id'],StartRun(operation_id='queued-start',expected_revision=1),binding={'provider':'local'})
    station.cancel(run['id'],'queued-cancel')
    station.continue_run(run['id'],ContinueRun(operation_id='queued-continue',expected_generation=0))
    claimed=queue.claim('local')
    assert claimed.id==run['id'] and claimed.generation==1
    view=trace_view(station,claimed.id)
    assert any(s.name=='恢复执行' for s in view.spans)
    assert any(link.kind=='recovery' for link in view.links)


def test_company_projection_rebuild_scope_history_and_withdrawal(running):
    station, source, run, queue, tools, token, call = running
    report, value, evidence, assertion = report_fixture(running)
    with station.store.connect(write=True) as db:
        station.reports.check(db, report.document.ref, 'independent', 'passed', coverage=[assertion['id']+'@1'])
    group = station.reports.groups()[0]
    station.reports.decide(group['id'], Decide(operation_id='adopt', expected_revision=1, action='adopt', reason='离线投影视图测试'))
    before = utcnow()
    view = company_view(station, 'PDD', Scope(subjects=['PDD']))
    assert len(view.knowledge) == 1 and len(view.values) == 1
    assert view.values[0].object.ref == Ref(id=value['id'], revision=1)
    assert any(h.kind=='decision' for h in view.history)
    station.register_subject('other', identity='OTHER', name='无关公司')
    unrelated = company_view(station, 'OTHER', Scope(subjects=['OTHER']))
    assert not unrelated.values and not unrelated.sources and not unrelated.knowledge
    station.withdraw_source(source.ref, 'withdraw', '披露撤回')
    after = company_view(station, 'PDD', Scope(subjects=['PDD']))
    assert after.knowledge[0].current_validity.status == 'needs_review'
    assert after.reports[0] == view.reports[0]
    # Historical objects remain available with a separate current validity notice.
    historical = Scope(subjects=['PDD'], mode='historical', as_of=before, allow_public_search=False)
    old = company_view(station, 'PDD', historical)
    assert old.knowledge[0].object == view.knowledge[0].object
    assert old.knowledge[0].current_validity.status == 'needs_review'


def test_export_fail_retry_is_connected_to_report_trace(running):
    from pitr.artifacts.queue import ExportQueue
    station, source, run, queue, tools, token, call = running
    report, *_ = report_fixture(running)
    request = ExportRequest(operation_id='export', report=report.document.ref, paper='A4')
    job = station.reports.export(request)
    def failure(*args):raise RuntimeError('offline renderer failure')
    exports = ExportQueue(station, start=False, renderer=failure)
    exports.perform(exports.claim())
    station.reports.retry_export(job['id'], 'retry')
    exports.perform(exports.claim())
    view = trace_view(station, run.id)
    attempts = [s for s in view.spans if s.kind == 'export']
    assert len(attempts)==2 and all(s.status=='failed' for s in attempts)
    assert all(s.duration_ms is not None and s.artifact_refs[0] == report.document.ref for s in attempts)
    assert any(e.kind=='recovery' and e.source==attempts[0].id and e.target==attempts[1].id for e in view.links)


def test_historical_subject_and_lazy_trace_detail(running):
    station, source, run, queue, tools, token, call = running
    cutoff=utcnow()
    station.register_subject('rename',identity='PDD',name='当前名称',expected_revision=1)
    past=company_view(station,'PDD',Scope(subjects=['PDD'],mode='historical',as_of=cutoff,allow_public_search=False))
    assert past.subject.name=='拼多多' and past.subject.revision==1 and past.subject_at_time
    assert company_view(station,'PDD',Scope(subjects=['PDD'])).subject.revision==2
    call('source.read',ref=source.ref.model_dump(),block_id=source.blocks[0].id)
    view=trace_view(station,run.id)
    selected=next(s for s in view.spans if s.name=='source.read')
    assert 'arguments' not in selected.metadata and 'result' not in selected.metadata
    details=trace_view(station,run.id,detail_id=selected.id)
    detail=next(s for s in details.spans if s.id==selected.id)
    assert detail.metadata['arguments']['ref']==source.ref.model_dump()
    assert 'Revenue 100.000' in detail.metadata['result']['text']
    client=TestClient(create_app(station.root,station=station,workers=False))
    url=f'/api/v1/runs/{run.id}/trace/spans/{selected.id}'
    assert client.get(url).json()['metadata']['result']['text']
    assert client.get(url+'?at_seq='+str(selected.first_seq-1)).status_code==404


def test_event_subscription_resumes_from_last_received_sequence(running):
    import asyncio
    station, source, run, queue, tools, token, call = running
    call('context')
    events=station.trace(run.id)
    cursor=events[-3]['seq']
    app=create_app(station.root,station=station,workers=False)
    async def read():
        delivered=asyncio.Event()
        chunks=[]
        async def receive():
            await delivered.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.start':assert message['status']==200
            if message['type']=='http.response.body' and message.get('body'):
                chunks.append(message['body'].decode())
                if f"id: {events[-1]['seq']}\n" in chunks[-1]:delivered.set()
        scope={'type':'http','asgi':{'version':'3.0'},'method':'GET','scheme':'http',
            'path':f'/api/v1/runs/{run.id}/trace/events','query_string':b'',
            'headers':[(b'last-event-id',str(cursor).encode())],
            'server':('testserver',80),'client':('127.0.0.1',1000),'root_path':''}
        await asyncio.wait_for(app(scope,receive,send),timeout=3)
        return chunks
    chunks=asyncio.run(read())
    assert [int(c.splitlines()[0].split(': ')[1]) for c in chunks]==[e['seq'] for e in events if e['seq']>cursor]
    assert all('event: trace' in c for c in chunks)
    assert all('"arguments"' not in c and '"result"' not in c for c in chunks)


def test_large_trace_payload_is_read_from_content_storage_only_in_node_detail(running):
    station, source, run, *_=running
    payload={'name':'object.read','generation':run.generation,'result':{'id':source.id,'revision':source.revision,'text':'x'*65000}}
    with station.store.connect(write=True) as db:
        station.store.event(db,run.id,'tool.called',payload)
    event=station.trace(run.id)[-1]
    assert 'content_digest' in event['data']
    view=trace_view(station,run.id)
    selected=next(s for s in view.spans if s.name=='object.read')
    assert len(view.model_dump_json())<10000 and selected.duration_ms is None
    assert selected.artifact_refs==[source.ref]
    detail=trace_view(station,run.id,detail_id=selected.id)
    assert next(s for s in detail.spans if s.id==selected.id).metadata['result']==payload['result']

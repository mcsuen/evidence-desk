"""Regression evidence from real-host, browser and artifact acceptance failures."""
import json
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from pitr.domain.common import Conflict, Forbidden, BudgetExhausted, uid
from pitr.domain.contracts import Ref,Scope,UpdateInput,StartRun,ReviseReport,Decide,ExportRequest
from pitr.application.tools import Bind
from conftest import report_fixture,ref


def test_unit_catalog_and_header_proofs_reject_misleading_bindings(running):
    station,source,run,queue,tools,token,call=running
    e=call('evidence.quote',source=source.ref.model_dump(),block_id=source.blocks[0].id,quote=source.blocks[0].text)
    args=dict(evidence=ref(e),literal='100.000',metric='revenue',subject='PDD',period='2025Q2',original_unit='RMB_mn',unit='RMB_mn',unit_evidence=ref(e),period_evidence=ref(e),basis_evidence=ref(e),basis='GAAP',frequency='quarter',currency='CNY')
    for changes in ({'original_unit':'RMB thousand'},{'original_unit':'RMB_thousand'},{'currency':'USD'},{'period':'2026Q2'},{'basis':'non-gaap'}):
        with pytest.raises((ValueError,ValidationError)):call('value.bind',**{**args,**changes})
    assert 'RMB_thousand' in Bind.model_json_schema()['properties']['original_unit']['enum']


def test_cached_read_does_not_bypass_source_revocation(running):
    station,source,run,queue,tools,token,call=running
    request={'operation_id':'read-repeat','name':'source.read','arguments':{'ref':source.ref.model_dump()}}
    tools.call(token,request)
    station.withdraw_source(source.ref,'withdraw','mismatched issuer')
    with pytest.raises(Conflict):tools.call(token,request)


def test_public_fetch_budget_checked_before_network(running,monkeypatch):
    station,source,run,queue,tools,token,call=running
    def fail(*a,**kw):pytest.fail('Budget exhausted request reached network')
    monkeypatch.setattr('pitr.adapters.public_fetch.fetch_public',fail)
    with station.store.connect(write=True) as db:
        run.tool_calls=run.budget.tool_calls;station.save_run(db,run)
    with pytest.raises(BudgetExhausted):call('source.fetch',url='https://example.com',subjects=['PDD'])


def test_partial_report_revision_preserves_completed_content(running):
    station,source,run,queue,tools,token,call=running
    view,*_=report_fixture(running);before=view.document.model_dump(mode='json')
    queue.partial(run,'预算耗尽，继续研究后核验')
    queue.finish(run,'budget_exhausted')
    new=station.reports.view(station.get_run(run.id).report)
    assert new.document.revision==2 and new.delivery=='partial'
    assert new.document.sections==view.document.sections
    assert station.reports.view(view.document.ref).document.model_dump(mode='json')==before


def test_naked_financial_number_requires_typed_reference(running):
    station,source,run,queue,tools,token,call=running
    view,*_=report_fixture(running)
    doc=view.document.model_dump(mode='json');doc['summary'][0]['inlines']=[{'type':'text','text':'收入 100 百万元，同比增长 25%'}]
    with pytest.raises(ValueError,match='类型化'):
        call('report.save',**{k:doc[k] for k in ('title','summary','sections','assertions')})


def test_incremental_input_reuses_only_unchanged_dependencies(running):
    station,source,run,queue,tools,token,call=running
    view,value,evidence,claim=report_fixture(running)
    second=station.import_source(b'PDD unrelated new product announcement','text/plain',subjects=['PDD'])
    queue.finish(run,'completed');case=station.get_case(run.case_id)
    station.update_input(case.id,UpdateInput(operation_id='input-2',expected_revision=1,question='增加资料继续研究',scope=case.input.scope,sources=[source.ref,second.ref]))
    station.start_run(case.id,StartRun(operation_id='start-2',expected_revision=2),binding={'provider':'local'})
    next_run=queue.claim('local');snapshot=station.store.get(next_run.snapshot,'snapshot')
    assert Ref.model_validate(ref(value)) in snapshot.reused
    queue.finish(next_run,'completed')
    station.withdraw_source(source.ref,'withdraw','source corrected')
    station.update_input(case.id,UpdateInput(operation_id='input-3',expected_revision=2,question='只用有效原件重查',scope=case.input.scope,sources=[second.ref]))
    third=station.start_run(case.id,StartRun(operation_id='start-3',expected_revision=3),binding={'provider':'local'})
    assert not station.store.get(third['snapshot'],'snapshot').reused


def test_forecast_arithmetic_cannot_become_actual_chart(running):
    station,source,run,queue,tools,token,call=running
    view,value,evidence,claim=report_fixture(running)
    assumption=call('value.assume',metric='multiple',amount='2',unit='multiple',subject='PDD',period='2025Q2',basis='GAAP',frequency='quarter',reason='场景假设',dependencies=[ref(evidence)],limitations=['不是实际披露'])
    forecast=call('value.calculate',operation='multiply',inputs=[ref(value),ref(assumption)],metric='scenario_revenue')
    assert forecast['role']=='assumption'
    body=view.document.model_dump(mode='json');body['sections'][0]['blocks'][1]['series'][0]['values']=[ref(forecast),None]
    with pytest.raises(ValueError,match='预测或假设'):
        call('report.save',**{k:body[k] for k in ('title','summary','sections','assertions')})


def test_revised_report_supersedes_only_pending_equivalent_review_group(running):
    station,*_=running
    view,*_=report_fixture(running)
    old=station.reports.groups()[0]
    body={k:view.document.model_dump(mode='json')[k] for k in ('title','summary','sections','gaps','next_steps')}
    result=station.reports.revise(view.document.id,ReviseReport(operation_id='edit',expected_revision=1,reason='澄清',**body))
    groups=[g for g in station.reports.groups() if g["status"]=="pending"]
    assert len(groups)==1 and groups[0]['id']!=old['id']
    station.reports.decide(groups[0]['id'],Decide(operation_id='adopt-new',expected_revision=1,action='adopt',reason='已核对新修订'))
    assert len(station.knowledge())==1


def test_discovery_operation_id_does_not_repeat_acquisition(station,monkeypatch):
    from pitr.research.discovery import directory
    calls=[]
    class Adapter:
        def find_candidates(self,*a):calls.append('lookup');return []
    monkeypatch.setattr('pitr.adapters.sources.protocol.adapter',lambda name:Adapter())
    a=directory(station,'PDD','SEC',operation_id='discover')
    assert directory(station,'PDD','SEC',operation_id='discover')==a and calls==['lookup']
    with pytest.raises(Conflict):directory(station,'PDD','SEC',since='2024',operation_id='discover')


def test_model_gateway_denies_public_web_and_other_ports(tmp_path):
    from pitr.agent_runtime.egress import ModelEgress
    env={}
    with ModelEgress('codex',env,{},tmp_path) as gateway:
        for target in ('example.com:443','api.openai.com:80','other.api.openai.com:443','api.openai.com:443/path'):
            with socket.create_connection(gateway.server.server_address) as sock:
                sock.sendall(f'CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n'.encode())
                assert b' 403 ' in sock.recv(4096)
        assert env['PITR_MODEL_GATEWAY_PORT']==str(gateway.server.server_port)
    assert len((tmp_path/'egress.jsonl').read_text().splitlines())==4


def test_backup_restores_artifacts_and_holds_slack_delivery(running,tmp_path):
    from pitr.application.maintenance import backup,restore
    from pitr.application.service import Workstation
    from pitr.integrations.slack.store import Journal
    station,*_=running;view,*_=report_fixture(running)
    # Existing channel state is retained but no pending external post can restart.
    slack=Journal(station.root/'channels/slack')
    with slack.connect(write=True) as db:
        db.execute("INSERT INTO bindings VALUES('research',?, 'event-1')",(view.document.run_id,))
        db.execute("INSERT INTO outbox(id,event_id,target,payload,status,created) VALUES('delivery-1','event-1','{}','{}','pending',0)")
        db.execute("INSERT INTO inbox(id,adapter,event,status,created) VALUES('event-1','research','{}','pending',0)")
    archive=backup(station);target=tmp_path/'restored';restore(archive,target)
    restored=Workstation(target,runtime=False)
    assert restored.reports.view(view.document.ref).document==view.document
    for source in view.sources:assert restored.store.read_blob(source.digest)==station.store.read_blob(source.digest)
    with restored.store.connect() as db:assert not db.execute('SELECT 1 FROM grants WHERE active=1').fetchone()
    with Journal(target/'channels/slack').connect() as db:
        assert db.execute('SELECT status FROM outbox').fetchone()[0]=='held_after_restore'
        assert db.execute('SELECT status FROM inbox').fetchone()[0]=='held_after_restore'
        assert db.execute("SELECT value FROM state WHERE key LIKE 'held_binding:%'").fetchone()[0]=='true'


def test_human_evaluation_records_do_not_imply_machine_blind_review(running):
    from pitr.application.evaluation import BlindPack,HumanEvaluation,blind_pack,record,summary,calibrate
    import io,zipfile
    station,*_=running;view,*_=report_fixture(running)
    raw=blind_pack(station,BlindPack(operation_id='pack',reports=[view.document.ref]))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:template=json.loads(archive.read('review-template.json'))[0]
    for person in ('reviewer-a','reviewer-b'):
        record(station,HumanEvaluation(operation_id=person,blind_id=template['blind_id'],annotator=person,edit_effort='light',major_error=False,editing_minutes=10))
    result=summary(station)
    assert result['paired_reports']==1 and result['light_edit_ratio']==1 and not result['human_validation_complete']
    assert calibrate(station,'standard')['status']=='insufficient_samples'


def test_v1_routes_request_schema_and_no_old_api(station):
    from fastapi.testclient import TestClient
    from pitr.adapters.api import create_app
    from pitr.schemas import build_schema
    app=create_app(station.root,station=station,workers=False)
    with TestClient(app) as client:
        for path in ('health','subjects','sources','cases','runs','reports','review','knowledge','graph','today','maintenance','settings','evaluations','source-adapters'):
            assert client.get('/api/v1/'+path).status_code==200,path
        assert client.get('/api/desk/state').status_code==404
        assert client.post('/api/v1/cases',json={'question':'missing operation ID','scope':{}}).status_code==422
        schema=app.openapi()
        assert schema['components']['schemas']['CreateCase']['required']==['operation_id','question']
    request=build_schema('create_case.v1.json');response=build_schema('report_document.v1.json')
    assert 'sources' not in request['required'] and 'gaps' in response['required']


def test_slack_commands_use_current_kernel_and_exact_attachment(station):
    from pitr.adapters.slack import ResearchWorkflow
    from pitr.integrations.slack.contracts import InboundEvent,ReplyTarget,AttachmentRef
    station.agents=SimpleNamespace(selection=lambda *a,**kw:{'provider':'local'},cancel=lambda *a:None)
    messages=[];bindings=[];prepared=[]
    def prepare(fn):
        if not prepared:prepared.append(fn())
        return prepared[0]
    context=SimpleNamespace(attachment_bytes=lambda identity:b'PDD news original',prepare=prepare,
        bind=bindings.append,publish=lambda *a,**kw:messages.append((a,kw)))
    target=ReplyTarget(team_id='T',user_id='U',channel_id='C')
    event=InboundEvent(id='slack-1',kind='command',target=target,text='new PDD 核对这份原件',
        attachments=[AttachmentRef(id='attachment_1',file_id='F',name='news.txt',media_type='text/plain')])
    workflow=ResearchWorkflow(station);workflow.handle(event,context);workflow.handle(event,context)
    assert len(station.runs())==1 and len(station.store.list('source'))==1
    run=station.runs()[0];source=station.store.list('source')[0]
    assert station.store.read_blob(source.digest)==b'PDD news original'
    workflow.handle(InboundEvent(id='slack-cancel',kind='command',target=target,text='cancel '+run.id),context)
    assert station.get_run(run.id).status=='cancelled'
    workflow.handle(InboundEvent(id='slack-resume',kind='command',target=target,text='continue '+run.id),context)
    assert station.get_run(run.id).status=='queued' and len(station.runs())==1


def test_source_acquisition_is_stable_on_duplicate_command(station,monkeypatch):
    calls=[]
    def fetch(url,**kw):calls.append(url);return b'first original','text/plain',url,{}
    monkeypatch.setattr('pitr.adapters.public_fetch.fetch_public',fetch)
    first=station.fetch_source('https://example.com/report',operation_id='fetch-original',subjects=['PDD'])
    second=station.fetch_source('https://example.com/report',operation_id='fetch-original',subjects=['PDD'])
    assert first==second and len(calls)==1


def test_live_refetch_replaces_snapshot_version_and_preserves_history(running,monkeypatch):
    station,source,run,queue,tools,token,call=running
    bodies=iter((b'PDD initial disclosure',b'PDD corrected disclosure'))
    monkeypatch.setattr('pitr.adapters.public_fetch.fetch_public',lambda url,**kw:(next(bodies),'text/plain',url,{}))
    first=call('source.fetch',url='https://example.com/disclosure',subjects=['PDD'])
    first_snapshot=station.store.get(first['snapshot'],'snapshot')
    second=call('source.fetch',url='https://example.com/disclosure',subjects=['PDD'])
    current=station.store.get(second['snapshot'],'snapshot')
    assert first['source']['id']==second['source']['id']
    assert second['source']['revision']==2
    assert Ref.model_validate(first['source']) in first_snapshot.sources
    assert Ref.model_validate(first['source']) not in current.sources
    assert Ref.model_validate(second['source']) in current.sources
    assert call('source.search',query='corrected')['hits'][0]['source']==second['source']
    with pytest.raises(Forbidden):call('source.read',ref=first['source'])


def test_old_review_job_on_changed_source_terminates_without_retry_loop(running):
    station,source,run,queue,tools,token,call=running
    view,*_=report_fixture(running);queue.finish(run,'completed')
    body={k:view.document.model_dump(mode='json')[k] for k in ('title','summary','sections','gaps','next_steps')}
    station.reports.revise(view.document.id,ReviseReport(operation_id='revise-for-review',expected_revision=1,reason='更正表述',**body))
    station.withdraw_source(source.ref,'withdraw-for-review','原件已更正')
    queue.review_revision('local')
    with station.store.connect() as db:
        assert db.execute('SELECT status FROM outbox').fetchone()[0]=='failed'
        assert not db.execute('SELECT 1 FROM job_leases').fetchone()


def test_pdf_consistency_ignores_page_furniture_but_keeps_numbered_body():
    from pitr.artifacts.render import verify_text
    pages=['PITR  /  研究报告\n修订 2  ·  4 / 11\n3）研究解释：2024Q2 披露',
           'PITR  /  研究报告\n修订 2  ·  5 / 11\n显示原件与金额均相同。']
    assert verify_text(pages,['3）研究解释：2024Q2 披露显示原件与金额均相同。'],2)['status']=='passed'
    with pytest.raises(ValueError):verify_text(pages,['收入为999百万元。'],2)


def test_view_rebuild_retry_is_bound_to_original_command(station):
    from pitr.application.maintenance import rebuild
    first=rebuild(station.store,'rebuild-one')
    station.import_source(b'PDD new material','text/plain',subjects=['PDD'])
    assert rebuild(station.store,'rebuild-one')==first
    assert rebuild(station.store,'rebuild-two')['rebuilt']==first['rebuilt']+1
    with pytest.raises(Conflict):
        station.register_subject('rebuild-one',identity='OTHER',name='Other issuer')

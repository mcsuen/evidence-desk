import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
import pytest

from pitr.domain.common import Conflict, Forbidden, BudgetExhausted
from pitr.domain.contracts import Ref, UpdateInput, ReviseReport, Decide, ExportRequest, ContinueRun
from conftest import report_fixture,ref


def test_exact_values_citations_and_native_word(running):
    from pitr.artifacts.docx import compile_docx,validate
    view,value,evidence,claim=report_fixture(running)
    assert str(view.values[0].amount)=='100.000'
    assert view.delivery=='draft'
    raw,manifest=compile_docx(view)
    assert validate(raw,manifest)['status']=='passed'
    assert compile_docx(view)[0]==raw
    assert manifest['charts'][0]['points'][0]['amount']=='100.000'
    assert len(manifest['charts'][0]['points'])==1
    raw_a4,other=compile_docx(view,'A4')
    assert raw_a4!=raw and other['paper']=='A4'


def test_cancel_fences_even_cached_requests(running):
    station,source,run,queue,tools,token,call=running
    request={'operation_id':'repeat','name':'context','arguments':{}}
    assert tools.call(token,request)==tools.call(token,request)
    station.cancel(run.id,'cancel')
    with pytest.raises(Forbidden):tools.call(token,request)


def test_scope_does_not_leak_through_cache(running):
    station,source,run,queue,tools,token,call=running
    other=station.import_source(b'private other input','text/plain')
    station.store.get(other.ref)
    with pytest.raises(Forbidden):call('object.read',ref=other.ref.model_dump())


def test_lease_generation_and_old_input(running):
    station,source,run,queue,tools,token,call=running
    with station.store.connect(write=True) as db:db.execute('UPDATE runs SET lease_until=? WHERE id=?',(time.time()-1,run.id))
    recovered=queue.claim('local')
    assert recovered.generation==run.generation+1
    with pytest.raises(Forbidden):call('context')
    new_token=tools.issue(run.id,recovered.generation)
    case=station.get_case(run.case_id)
    station.update_input(case.id,UpdateInput(operation_id='edit',expected_revision=1,
        question='不同问题',scope=case.input.scope,sources=case.input.sources))
    with pytest.raises(Forbidden):tools.call(new_token,{'operation_id':'old','name':'context'})


def test_operation_id_is_payload_bound_and_atomic(running):
    station,source,run,queue,tools,token,call=running
    request={'operation_id':'concurrent','name':'evidence.quote','arguments':{
        'source':source.ref.model_dump(),'block_id':source.blocks[0].id,'quote':source.blocks[0].text}}
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:tools.call(token,request),range(8)))
    assert all(r==results[0] for r in results)
    assert len(station.store.list('evidence'))==1
    with pytest.raises(Conflict):tools.call(token,{**request,'arguments':{**request['arguments'],'quote':'100.000'}})


def test_reviewer_cannot_write(running):
    station,source,run,queue,tools,token,call=running
    reviewer=tools.issue(run.id,run.generation,'reviewer')
    with pytest.raises(Forbidden):tools.call(reviewer,{'operation_id':'bad','name':'checkpoint.save',
        'arguments':{'summary':'a','next_actions':[]}})


def test_revision_and_current_validity_leave_history_immutable(running):
    station,source,run,queue,tools,token,call=running
    view,*_=report_fixture(running)
    original=view.document.model_dump(mode='json')
    body={k:original[k] for k in ('title','summary','sections','gaps','next_steps')}
    body['title']='修订后的报告'
    new=station.reports.revise(view.document.id,ReviseReport(operation_id='revise',expected_revision=1,reason='澄清措辞',**body))
    assert new['revision']==2
    assert station.reports.view(view.document.ref).document.model_dump(mode='json')==original
    station.withdraw_source(source.ref,'withdraw','原件更正')
    assert station.reports.view(view.document.ref).document.model_dump(mode='json')==original
    assert station.reports.view(view.document.ref).current_validity['status']=='needs_review'
    assert station.reports.view(view.document.ref).checks[0].status=='passed'
    with station.store.connect(write=True) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE revisions SET body=?',('{}',))


def test_adoption_not_implied_by_source_or_report(running):
    station,*_=running
    view,*_=report_fixture(running,risk='source_statement')
    assert view.delivery=='draft'
    assert not station.knowledge()
    group=station.reports.groups()[0]
    station.reports.decide(group['id'],Decide(operation_id='accept',expected_revision=1,action='adopt',reason='已人工核对原文'))
    assert len(station.knowledge())==1


def test_export_failure_retry_does_not_research(running):
    from pitr.artifacts.queue import ExportQueue
    station,*_=running
    view,*_=report_fixture(running)
    job=station.reports.export(ExportRequest(operation_id='export',report=view.document.ref))
    def broken(*args):raise RuntimeError('renderer unavailable')
    queue=ExportQueue(station,start=False,renderer=broken)
    queue.perform(queue.claim())
    station.reports.retry_export(job['id'],'retry')
    assert len(station.runs())==1
    assert queue.claim().attempts==2

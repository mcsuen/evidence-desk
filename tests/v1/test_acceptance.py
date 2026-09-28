"""Six families, 10 distinct cases each; cases 09/10 are final-evaluation holdouts.

These are engineering checks. They do not stand in for human research evaluation.
"""
import io
import json
import time
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from pitr.domain.common import Forbidden,Conflict,BudgetExhausted,canonical,utcnow,uid
from pitr.domain.contracts import *
from pitr.domain.numbers import parse_literal,locate,conversion,calculate,display
from pitr.domain.policy import source_allowed
from conftest import ref,report_fixture


def value(**changes):
    return Value(id=uid('value'),created_at=utcnow(),kind='observed',metric='revenue',amount=Decimal('100'),
        unit='RMB_mn',subject='PDD',period='2025Q2',basis='GAAP',frequency='quarter',currency='CNY',role='actual',**changes)


def changed(v,**changes):return Value.model_validate({**v.model_dump(),**changes})


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'numeric_{c:02}')
def test_numeric(case):
    if case==1:assert parse_literal('(1,230.50)')==Decimal('-1230.50')
    if case==2:
        with pytest.raises(ValueError):locate('revenue 12345','234')
    if case==3:
        with pytest.raises(ValueError):parse_literal('1,00,000')
    if case==4:
        with pytest.raises(ValueError):locate('100 100','100')
        assert locate('100 100','100',4)==4
    if case==5:assert parse_literal('103,984,832')*conversion('RMB_thousand','RMB_mn')==Decimal('103984.832')
    if case==6:assert parse_literal('−2.75%')==Decimal('-2.75')
    if case==7:
        a=changed(value(),metric='margin',unit='percent',currency='',amount='24.804')
        b=changed(a,amount='33.551',period='2024Q2')
        result=calculate('change',a,b);assert result[:2]==(Decimal('-8.747'),'percentage_points')
    if case==8:
        with pytest.raises(ValueError):calculate('ratio',value(),changed(value(),amount=0))
    if case==9:
        denominator=changed(value(),metric='shares',unit='ADS_mn',currency='',share_basis='ADS',amount=25)
        assert calculate('divide',value(),denominator)[:2]==(Decimal(4),'RMB_per_ADS')
    if case==10:
        denominator=changed(value(),metric='shares',unit='ADS_mn',share_basis='ordinary')
        with pytest.raises(ValueError):calculate('divide',value(),denominator)


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'accounting_{c:02}')
def test_accounting(case):
    a=value()
    if case<=5:
        key,val=[('basis','non-GAAP'),('frequency','ytd'),('currency','USD'),('subject','BABA'),('unit','USD_mn')][case-1]
        with pytest.raises(ValueError):calculate('add',a,changed(a,**{key:val}))
    if case==6:
        a=changed(a,frequency='ytd',period='2025Q3',amount=160)
        with pytest.raises(ValueError):calculate('quarterize',a,changed(a,period='2025Q1',amount=50))
    if case==7:
        a=changed(a,frequency='ytd',period='2025Q2',amount=160)
        assert calculate('quarterize',a,changed(a,period='2025Q1',amount=60))==(Decimal(100),'RMB_mn','2025Q2','quarter')
    if case==8:
        with pytest.raises(ValueError):calculate('growth',changed(a,period='2024Q2'),a)
    if case==9:
        with pytest.raises(ValueError):calculate('growth',a,changed(a,period='2024Q2',role='guidance'))
    if case==10:
        v=changed(a,amount='-12.3455',precision=3)
        assert '-12.346' in display(v)
        assert '百万元人民币' in display(v)


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'scope_{c:02}')
def test_scope(running,case):
    station,source,run,queue,tools,token,call=running
    historic=Scope(subjects=['PDD'],mode='historical',as_of='2025-07-01T00:00:00+00:00',allow_public_search=False)
    if case==1:
        with pytest.raises(Forbidden):source_allowed(source,Scope(subjects=['BABA']))
    if case==2:
        with pytest.raises(Forbidden):source_allowed(source,historic)
    if case==3:
        old=source.model_copy(update={'available_at':'2025-06-01T00:00:00+00:00','availability_basis':'declared'})
        with pytest.raises(Forbidden):source_allowed(old,historic)
    if case==4:
        old=source.model_copy(update={'available_at':'2025-06-01T00:00:00+00:00','availability_basis':'authoritative'})
        assert source_allowed(old,historic)
    if case==5:
        old=source.model_copy(update={'available_at':'2025-06-01T00:00:00+00:00','observed_at':'2025-06-01T00:00:00+00:00'})
        assert source_allowed(old,historic)
    if case==6:
        with pytest.raises(Forbidden):station.import_source(b'fake proof','text/plain',published_at='2020-01-01T00:00:00+00:00',availability_basis='authoritative',availability_evidence='self claim')
    if case==7:
        private=station.import_source(b'outside input','text/plain');station.store.get(private.ref)
        with pytest.raises(Forbidden):call('object.read',ref=private.ref.model_dump())
    if case==8:
        station.register_subject('baba',identity='BABA',name='BABA')
        e=call('evidence.quote',source=source.ref.model_dump(),block_id=source.blocks[0].id,quote=source.blocks[0].text)
        with pytest.raises(Forbidden):call('value.bind',evidence=ref(e),literal='100.000',metric='revenue',subject='BABA',period='2025Q2',original_unit='RMB_mn',unit='RMB_mn',unit_evidence=ref(e),period_evidence=ref(e),basis_evidence=ref(e),basis='GAAP',frequency='quarter')
    if case==9:
        view,*_=report_fixture(running)
        group=station.reports.groups()[0]
        station.reports.decide(group['id'],Decide(operation_id='adopt',expected_revision=1,action='adopt',reason='人工核对'))
        assert not station.knowledge(historic)
    if case==10:
        copy=station.import_source(('\n\n'.join(b.text for b in source.blocks)).encode(),'text/plain',url='https://example.org/reprint',subjects=['PDD'])
        assert copy.origin_group==source.origin_group and copy.ref!=source.ref


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'execution_{c:02}')
def test_execution(running,case):
    station,source,run,queue,tools,token,call=running
    if case==1:
        request=ToolRequest(operation_id='cached',name='context');tools.call(token,request)
        station.cancel(run.id,'cancel')
        with pytest.raises(Forbidden):tools.call(token,request)
    if case==2:
        station.cancel(run.id,'cancel')
        with pytest.raises(Forbidden):call('checkpoint.save',summary='late',next_actions=[])
    if case==3:
        call('checkpoint.save',summary='已读取原件',next_actions=['计算'])
        station.cancel(run.id,'cancel')
        station.continue_run(run.id,ContinueRun(operation_id='continue',expected_generation=run.generation))
        recovered=queue.claim('local');assert recovered.checkpoint['research']['summary']=='已读取原件'
    if case==4:
        tools.call(token,ToolRequest(operation_id='same',name='context'))
        with pytest.raises(Conflict):tools.call(token,ToolRequest(operation_id='same',name='source.search',arguments={'query':'100'}))
    if case==5:
        reviewer=tools.issue(run.id,run.generation,'reviewer')
        with pytest.raises(Forbidden):tools.call(reviewer,ToolRequest(operation_id='write',name='checkpoint.save',arguments={'summary':'x','next_actions':[]}))
    if case==6:
        with station.store.connect(write=True) as db:
            latest=station.get_run(run.id,db=db);latest.tool_calls=162;station.save_run(db,latest)
        with pytest.raises(BudgetExhausted):call('source.search',query='Revenue')
        assert call('checkpoint.save',summary='收尾',next_actions=[])['saved']
    if case==7:
        current=station.get_case(run.case_id)
        station.update_input(current.id,UpdateInput(operation_id='changed',expected_revision=1,question='修订问题',scope=current.input.scope,sources=current.input.sources))
        with pytest.raises(Forbidden):call('context')
    if case==8:
        with station.store.connect(write=True) as db:db.execute('UPDATE runs SET lease_until=?',(time.time()-1,))
        with pytest.raises(Forbidden):call('context')
    if case==9:
        from pitr.research.queue import ResearchQueue
        other=ResearchQueue(station,start=False);assert other.claim('local') is None
        with station.store.connect(write=True) as db:db.execute('UPDATE runs SET lease_until=?',(time.time()-1,))
        recovered=other.claim('local');assert recovered.generation==run.generation+1
        with pytest.raises(Forbidden):queue.finish(run,'completed')
    if case==10:
        import httpx
        from pitr.adapters.tool_http import ToolServer
        server=ToolServer(station)
        try:
            station.cancel(run.id,'cancel')
            response=httpx.post(server.url+'/call',headers={'Authorization':'Bearer '+token},json={'operation_id':'after','name':'context'},trust_env=False)
            assert response.status_code==403
        finally:server.close()


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'report_{c:02}')
def test_report(running,tmp_path,case):
    station,source,run,queue,tools,token,call=running
    view,number,evidence,claim=report_fixture(running)
    if case==1:
        with pytest.raises(ValueError):ValueSpan.model_validate({'type':'value','ref':ref(number),'amount':'999'})
    if case==2:
        body=view.document.model_dump();body['sections'][0]['blocks'][1]['unit']='USD_mn';body['revision']=2
        with station.store.connect(write=True) as db:
            with pytest.raises(ValueError):station.reports.freeze(db,ReportDocument.model_validate(body),expected=1)
    if case==3:
        from pitr.artifacts.docx import compile_docx,validate
        raw,manifest=compile_docx(view);assert validate(raw,manifest)['status']=='passed'
        assert len(manifest['charts'][0]['points'])==1
    if case==4:
        with pytest.raises(ValueError):TableBlock(id='bad',title='bad',columns=['A','B'],rows=[[[TextSpan(text='one')]]])
    if case==5:
        original=view.document.model_dump();body={k:original[k] for k in ('title','summary','sections','gaps','next_steps')}
        revised=station.reports.revise(view.document.id,ReviseReport(operation_id='edit',expected_revision=1,reason='test',**{**body,'title':'修改标题'}))
        assert revised['revision']==2 and station.store.get(view.document.ref).title==original['title']
    if case==6:
        unrelated=station.import_source(b'unused material','text/plain',subjects=['PDD']);station.withdraw_source(unrelated.ref,'withdraw','test')
        assert station.reports.view(view.document.ref).current_validity['status']=='available'
    if case==7:
        from pitr.artifacts.queue import ExportQueue
        job=station.reports.export(ExportRequest(operation_id='export',report=view.document.ref))
        q=ExportQueue(station,start=False,renderer=lambda *_:(_ for _ in ()).throw(ValueError('render failure')))
        q.perform(q.claim());station.reports.retry_export(job['id'],'retry')
        assert q.claim().attempts==2 and len(station.runs())==1
    if case==8:
        from pitr.application.maintenance import backup,restore
        from pitr.application.service import Workstation
        raw=backup(station);restore(raw,tmp_path/'restored');other=Workstation(tmp_path/'restored',runtime=False)
        assert other.store.get(view.document.ref)==view.document
        assert other.store.read_blob(source.digest)==station.store.read_blob(source.digest)
    if case==9:
        from pitr.application.maintenance import restore
        from pitr.domain.common import digest
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as z:
            z.writestr('../escape','bad');z.writestr('manifest.json',canonical({'schema':'research-backup.1','files':{'../escape':digest(b'bad')}}))
        with pytest.raises(ValueError):restore(output.getvalue(),tmp_path/'restore')
        assert not (tmp_path/'escape').exists()
    if case==10:
        from pitr.skills.library import catalog,load
        assert len(catalog())==7
        package=call('skill.load',name='earnings',reason='季度经营分析')
        assert package['digest']==load('earnings')['digest']
        assert station.get_run(run.id).checkpoint['skills'][0]['reason']=='季度经营分析'


@pytest.mark.parametrize('case',range(1,11),ids=lambda c:f'review_{c:02}')
def test_review(running,case):
    station,source,run,queue,tools,token,call=running
    view,number,evidence,claim=report_fixture(running,risk='source_statement')
    group=station.reports.groups()[0]
    decision=Decide(operation_id='adopt',expected_revision=1,action='adopt',reason='人工核对')
    if case==1:assert view.checks[-1].status=='not_run'
    if case==2:assert not station.knowledge()
    if case==3:
        station.withdraw_source(source.ref,'withdraw','correction')
        with pytest.raises(Conflict):station.reports.decide(group['id'],decision)
    if case in (4,5):
        second=call('assertion.propose',title='关联判断',statement='test',kind='fact',subjects=['PDD'],support=[ref(evidence)],
                    depends_on=[ref(claim)] if case==4 else [])
        with station.store.connect(write=True) as db:
            # A separate report groups a dependent pair atomically, or leaves independent choices separate.
            doc=view.document.model_copy(update={'id':uid('report'),'assertions':[ref_to_model(claim),ref_to_model(second)]})
            station.reports.freeze(db,doc)
        groups=station.reports.groups()
        if case==4:assert any(len(g['targets'])==2 for g in groups)
        else:assert all(len(g['targets'])==1 for g in groups)
    if case==6:
        with pytest.raises(ValueError):call('assertion.propose',title='关系',statement='官方来源',kind='relationship',subjects=['PDD'],support=[ref(evidence)],alternative='还需核验',relation={'from':'PDD','to':'PDD','type':'supplier','maturity':'official','semantic_basis':'官方披露'})
    if case==7:assert view.delivery=='draft'
    if case==8:
        statuses=['not_run','unavailable','error','not_applicable','passed']
        for status in statuses:
            with station.store.connect(write=True) as db:station.reports.check(db,view.document.ref,'independent',status)
            assert station.reports.view(view.document.ref).checks[-1].status==status
    if case==9:
        saved=station.reports.decide(group['id'],decision)
        station.withdraw_source(source.ref,'withdraw','later correction')
        assert station.store.get(saved['id'],'decision').action=='adopt'
        assert station.knowledge()[0]['current_validity']['status']=='needs_review'
    if case==10:
        with station.store.connect(write=True) as db:station.reports.check(db,view.document.ref,'independent','failed',findings=[{'message':'wrong value'}])
        with pytest.raises(Conflict):station.reports.decide(group['id'],decision)


def ref_to_model(obj):return Ref.model_validate(ref(obj))

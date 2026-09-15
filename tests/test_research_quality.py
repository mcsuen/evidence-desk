"""Regressions from the real CMBI report and the quality-driven controller."""
import json
from pathlib import Path
import pytest
from test_native_research import plane as base_plane, claim, draft

@pytest.fixture
def plane(base_plane):
    base_plane.input.update(workflow_version=3,budget_seconds=None,tool_budget=None)
    base_plane.bootstrap_requirements()
    return base_plane
from pitr.desk.research.contracts import ResearchRequest, AgentDraft
from pitr.desk.research.verify import validate
from research_fixtures import Research
from pitr.desk.storage import canonical


def test_unlimited_default_respects_explicit_limits(plane):
    request=ResearchRequest(operation_id='unlimited')
    assert request.budget_seconds is None and request.tool_budget is None
    plane.state.update(active_seconds=999999,tool_calls=10000,repairs=100)
    assert plane.call('context',{})['usage']['tool_calls']==10001
    plane.input['tool_budget']=10001
    with pytest.raises(ValueError,match='预算耗尽'):plane.call('context',{})


@pytest.mark.parametrize('text',['报告第1页和第1-2页。','2025E、2026-2027E、FY25E。'.replace('FY25E','FY2025E'),
    '2025年8月、2025年8月26日。','4Q25E 与 2025Q2。','研报页1及页3。','FY25E合并收入仍需核对。','白宫 EO 14256 与 Executive Order 14257。'])
def test_page_and_forecast_dates_are_not_money(plane,text):
    e=plane.read_source('source_fixture')['blocks'][0]
    result=validate(draft(claim(text=text,evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in result['issues'])


@pytest.mark.parametrize('date',['7月','7月30日','07月30号','12 月 31 日','1月2日'])
def test_month_without_year_is_not_money_but_adjacent_amount_is_checked(plane,date):
    e=plane.read_source('source_fixture')['blocks'][0]
    text='政策在'+date+'公布。'
    result=validate(draft(claim(text=text,evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in result['issues'])
    result=validate(draft(claim(text=text+'涉及 800 美元门槛。',evidence=[e['id']])),plane)
    assert any(i['code']=='unbound_number' and i['value']=='800' for i in result['issues'])


@pytest.mark.parametrize('text',['7个月内收入增加。','13月数据待查。','1.7月数据待查。'])
def test_duration_or_invalid_month_is_not_silently_discarded(plane,text):
    e=plane.read_source('source_fixture')['blocks'][0]
    result=validate(draft(claim(text=text,evidence=[e['id']])),plane)
    assert any(i['code']=='unbound_number' for i in result['issues'])


@pytest.mark.parametrize('prefix',['EO 14256','白宫EO 14256','E.O.14256','Executive Order No. 14256'])
def test_policy_identifier_does_not_hide_unbound_threshold(plane,prefix):
    e=plane.read_source('source_fixture')['blocks'][0]
    result=validate(draft(claim(text=prefix+' 的政策日期需要核对。',evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in result['issues'])
    result=validate(draft(claim(text=prefix+' 涉及 800 美元门槛。',evidence=[e['id']])),plane)
    assert any(i['code']=='unbound_number' and i['value']=='800' for i in result['issues'])


@pytest.mark.parametrize('form',['6-K','10-K','10-Q','20-F','6‑K/A'])
def test_filing_form_is_a_locator_but_nearby_money_still_needs_binding(plane,form):
    e=plane.read_source('source_fixture')['blocks'][0]
    text='已核对公司'+form+'文件原文。'
    result=validate(draft(claim(text=text,counterevidence_notes=text,evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in result['issues'])
    result=validate(draft(claim(text=text+'收入增加 6 百万元。',evidence=[e['id']])),plane)
    assert any(i['code']=='unbound_number' and i['value']=='6' for i in result['issues'])


@pytest.mark.parametrize('text',['1) Bloomberg共识样本和口径；2) 完整券商模型。','（1）核对原件；（2）复核口径。','1. 核对原件\n2. 复核口径'])
def test_list_numbers_are_not_amounts_but_listed_money_still_needs_binding(plane,text):
    e=plane.read_source('source_fixture')['blocks'][0]
    result=validate(draft(claim(next_check=text,evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in result['issues'])
    result=validate(draft(claim(next_check='1) 收入为 999 百万元；2) 检查口径。',evidence=[e['id']])),plane)
    assert any(i['code']=='unbound_number' and i['value']=='999' for i in result['issues'])


@pytest.mark.parametrize('text',['收入同比增加 2025 百万元。','利润下降 2025 美元。','毛利率为 2025%。'])
def test_amounts_that_look_like_years_never_bypass_numeric_binding(plane,text):
    e=plane.read_source('source_fixture')['blocks'][0]
    assert any(i['code']=='unbound_number' for i in validate(draft(claim(text=text,evidence=[e['id']])),plane)['issues'])


def test_calendar_relations_accept_dates_but_reject_identifiers_and_overlap(plane):
    from pitr.desk.research.contracts import AgentTemporalRelation
    from pydantic import ValidationError
    e=plane.read_source('source_fixture')['blocks'][0]
    result=validate(draft(claim(evidence=[e['id']],chronology=[{'earlier':'2025-04-08','later':'2025-05-02'}])),plane)
    assert not any(i['code']=='chronology' for i in result['issues'])
    result=validate(draft(claim(evidence=[e['id']],chronology=[{'earlier':'2025Q2','later':'2025-05-02'}])),plane)
    assert any(i['code']=='chronology' for i in result['issues'])
    with pytest.raises(ValidationError):AgentTemporalRelation(earlier=e['id'],later='2025Q3')


def test_agent_reference_contract_rejects_truncated_identifiers(plane):
    from pydantic import ValidationError
    e=plane.read_source('source_fixture')['blocks'][0]
    AgentDraft.model_validate(draft(claim(evidence=[e['id']])))
    with pytest.raises(ValidationError):AgentDraft.model_validate(draft(claim(evidence=[e['id'][:-4]])))


def test_specific_counterevidence_error_preserves_support(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(evidence=[e['id']],counterevidence=['同比下降不证明预期差']))
    first=validate(raw,plane)
    issue=next(i for i in first['issues'] if i['code']=='evidence')
    assert issue['field']=='counterevidence[0]' and issue['value']=='同比下降不证明预期差'
    assert first['verification']['numeric_integrity']=='checked'
    with plane.desk.store.connect(write=True) as db:
        db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,canonical({'raw':raw,'validated':first})))
    revised=validate(draft(claim(evidence=[],counterevidence=[])),plane)
    assert any(i['code']=='regression' and i['field']=='evidence' for i in revised['issues'])
    good=validate(draft(claim(evidence=[e['id']],counterevidence=[],counterevidence_notes='同比变化和预期差需要分别核对。')),plane)
    assert not good['issues']
    with pytest.raises(Exception):AgentDraft.model_validate(raw)


def test_thirty_to_twenty_one_to_zero_references_cannot_pass_as_repair(plane):
    upload=Research(plane.desk).upload('\n\n'.join('原文依据 '+chr(0x4e00+i) for i in range(30)).encode(),'text/plain','thirty-originals.txt','PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    refs=[e['id'] for e in plane.read_source(upload['source_id'],limit=60)['blocks']]
    assert len(refs)==30
    first=draft(claim(evidence=refs,counterevidence=['这是反证说明，不是编号']))
    report=validate(first,plane)
    assert len(report['evidence'])==30 and report['issues'][0]['field']=='counterevidence[0]'
    with plane.desk.store.connect(write=True) as db:
        db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,canonical({'raw':first,'validated':report})))
    for kept,missing in [(refs[:21],9),([],30)]:
        revised=validate(draft(claim(evidence=kept)),plane)
        loss=next(i for i in revised['issues'] if i['code']=='regression' and i['field']=='evidence')
        assert len(loss['value'])==missing and revised['verification']['retained_claims']==1
    assert not validate(draft(claim(evidence=refs,counterevidence_notes='缺口不等于真实反证')),plane)['issues']


def test_search_official_not_first_uploaded_hits_and_context_small(plane):
    upload=Research(plane.desk).upload(b'official PDD revenue author interpretation','text/plain','author.txt','PDD')
    plane.frozen['sources']={upload['source_id']:upload['digest'],**plane.frozen['sources']}
    found=plane.search_sources('PDD official revenue')
    assert found and all(x['source_id']=='source_fixture' for x in found)
    ctx=plane.context()
    assert 'objects' not in ctx and 'wiki' not in ctx and 'input' not in ctx
    assert len(canonical(ctx))<18000


def test_report_number_provenance_and_period_comparison(plane):
    data=b'Operating profit actual 25,793 consensus 21,494. Non-GAAP net profit actual 32,708 consensus 22,390. Forecast current 104.0 previous 94.9.'
    upload=Research(plane.desk).upload(data,'text/plain','report.txt','PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    e=plane.read_source(upload['source_id'])['blocks'][0]
    def number(text,metric,role,period='2025Q2'):
        return {'evidence_id':e['id'],'text':text,'metric':metric,'unit':'RMB_mn','period':period,'role':role,'frequency':'quarter','basis':'disclosed','row_label':metric,'column_label':role}
    with pytest.raises(ValueError,match='官方'):plane.register_numbers([number('25,793','operating_profit','company_actual')])
    inputs=plane.register_numbers([number('25,793','operating_profit','broker_forecast'),number('21,494','operating_profit','reported_consensus'),
        number('32,708','non_gaap_net_income','broker_forecast'),number('22,390','non_gaap_net_income','reported_consensus'),
        number('104.0','forecast_net_income','broker_forecast','2025FY'),number('94.9','forecast_net_income','broker_forecast','2025FY')])
    result=plane.calculate_batch([{'operation':'compare','left':inputs[i]['id'],'right':inputs[i+1]['id']} for i in (0,2,4)])['results']
    assert [r['value'] for r in result]==pytest.approx([20.00093049,46.0830728,9.5890411])
    assert all(r['verification_status']=='quoted_not_independently_verified' for r in result)
    raw=draft(claim(claim_type='calculation',text='表内预期差为 {{'+result[0]['id']+'}}。',calculations=[result[0]['id']]))
    checked=validate(raw,plane)
    assert not any(i['code']=='missing_evidence' for i in checked['issues'])
    assert e['id'] in checked['claims'][0]['calculation_evidence']


def test_real_pdf_page_three_and_three_tables(plane):
    pdf=Path(__file__).parents[1]/'CMBI-PDD-2025-08-26.pdf'
    if not pdf.is_file():pytest.skip('local licensed regression original unavailable')
    upload=Research(plane.desk).upload(pdf.read_bytes(),'application/pdf',pdf.name,'PDD')
    assert upload['reading_status']=='not_started'
    assert 'PDF 图表未进行视觉解析' not in upload['issues']
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    page=plane.read_page(upload['source_id'],3)
    text='\n'.join(b['quote'] for b in page['blocks'])
    assert all(word in text for word in ['21,494','22,390','94.9','SOTP','322,028'])
    table=plane.read_table(upload['source_id'],3,0)
    assert table['table_count']>=3 and table['source_version']==upload['digest']
    assert any(r['page']==3 and r['status']=='read' for r in plane.reading_status() if r['source_id']==upload['source_id'])
    plane.input['source_ids']=[upload['source_id']];plane.input['intent']='report_review'
    plane.state['requirements']={};plane.bootstrap_requirements()
    revision=next(r for r in plane.requirements() if r['check']=='forecast_revision_ratios')
    assert revision['required_metrics']==['revenue','gross_profit','operating_profit','net_income']
    assert revision['required_periods']==['2025E','2026E','2027E']
    assert any(r['check']=='valuation_price_reconciliation' for r in plane.requirements())
    actual=next(r for r in plane.requirements() if r['check']=='consensus_comparison_ratios')
    assert any(t['metric']=='operating_profit' for t in actual['required_comparisons'])
    assert any(t['metric']=='net_income' and t['basis']=='non-GAAP' for t in actual['required_comparisons'])


class FakeNative:
    def __init__(self,p,role,turns):self.p=p;self.role=role;self.turns=turns;self.calls=0;self.current_ordinal=0
    def session_id(self):return self.role+'-separate-session'
    def attempt(self,prompt):
        self.calls+=1;self.current_ordinal+=1;self.p.role=self.role
        if self.calls>7:raise AssertionError('Unexpected loop: '+prompt)
        e=self.p.read_source('source_fixture')['blocks'][0]
        if self.role=='reviewer':
            reading=next(r for r in self.p.receipts('reading').values() if r['role']=='reviewer')
            passed=self.calls>self.turns
            return {'verdict':'pass' if passed else 'revise','summary':'已独立核对原件。','findings':[] if passed else [{'id':'reason','severity':'blocking','code':'inference','claim_id':'changes','requirement_id':'','field':'alternative','message':'还需解释','requested_change':'补查','evidence':[e['id']]}],
                'additional_requirements':[],'checked_requirements':[r['id'] for r in self.p.requirements()],
                'check_receipts':[reading['id']],'blocking_reason':''}
        # Each pass records one additional genuine calculation, not cosmetic prose changes.
        refs=self.p.financial_observations('revenue')
        calculations=[r['id'] for r in refs]
        for i in range(self.calls):
            calculations.append(self.p._calc('scenario_revenue',i+1,'RMB_mn','2025Q2','explicit scenario assumption',[],basis='GAAP',assumption=True)['id'])
        claims=[claim(id=k,section=k,evidence=[e['id']],calculations=calculations) for k in ('changes','persistence','questions')]
        return {**draft(*claims),'requirement_resolutions':[{'requirement_id':r['id'],'status':'answered','claim_ids':['changes'],'explanation':'已检查','check_receipts':[],'needed_input':''} for r in self.p.requirements()]}


def test_independent_review_can_repair_more_than_two_rounds(plane):
    from pitr.desk.research.quality import run_quality
    researcher=FakeNative(plane,'researcher',3);reviewer=FakeNative(plane,'reviewer',3)
    report=run_quality(plane,researcher,reviewer)
    assert researcher.calls==4 and reviewer.calls==4 and plane.state['repairs']==3
    assert report['verification']['independent_review']=='passed'
    assert len(report['reviews'])==4 and report['delivery']['status'] in ('ready','partial')
    assert researcher.session_id()!=reviewer.session_id()


def test_mechanical_repairs_do_not_anchor_independent_content_review(plane):
    from pitr.desk.research.quality import run_quality
    class BrokenFirst(FakeNative):
        def attempt(self,prompt):
            value=super().attempt(prompt)
            if self.calls==1:value['claims'][0]['evidence'].append('evidence_deadbeef')
            return value
    researcher=BrokenFirst(plane,'researcher',0);reviewer=FakeNative(plane,'reviewer',0)
    report=run_quality(plane,researcher,reviewer)
    assert researcher.calls==2 and reviewer.calls==1
    assert report['verification']['independent_review']=='passed' and plane.state['repairs']==1


def test_review_cannot_pass_without_independent_reading(plane):
    from pitr.desk.research.quality import review_feedback
    review={'checked_requirements':[r['id'] for r in plane.requirements()],'check_receipts':[], 'findings':[], 'additional_requirements':[]}
    assert any(x['code']=='review_reading' for x in review_feedback(plane,review,{}))


def test_unpaginated_original_names_correct_reader_and_never_claims_empty_page_read(plane):
    source=plane.desk.ingest(b'<html><title>Policy original</title><article><p>Official policy applies to covered imports.</p></article></html>',
                           'text/html','https://www.whitehouse.gov/policy-fixture','PDD')
    plane.frozen['sources'][source.id]=source.digest
    with pytest.raises(ValueError,match='read_source'):
        plane.read_page(source.id,1)
    assert not any(r['source_id']==source.id for r in plane.receipts('reading').values())
    result=plane.read_source(source.id)
    assert result['blocks'] and any('covered imports' in b['quote'] for b in result['blocks'])


def test_failed_reading_does_not_satisfy_independent_reading(plane):
    from pitr.desk.research.quality import review_feedback
    plane.role='reviewer';receipt=plane._record_reading('source_fixture',[],error='Wrong page')
    review={'checked_requirements':[r['id'] for r in plane.requirements()],'check_receipts':[receipt['id']],'findings':[],'additional_requirements':[]}
    assert any(x['code']=='review_reading' for x in review_feedback(plane,review,{}))


def test_review_new_source_requires_own_reading_and_report_binding(plane):
    from pitr.desk.research.quality import review_source_feedback
    e=plane.read_source('source_fixture')['blocks'][0]
    plane.receipt('tool',{'name':'fetch_public_source','role':'reviewer','result':{'included':True,'source_id':'source_fixture'}})
    report={'claims':[claim()]}
    assert review_source_feedback(plane,{},report)[0]['code']=='review_source_check'
    check={'source_id':'source_fixture','status':'used','reason':'Confirms the reported company fact','claim_ids':['c'],'evidence':[e['id']]}
    review={'source_checks':[check]}
    # Researcher's prior reading is not the reviewer's independent reading.
    assert review_source_feedback(plane,review,report)[0]['code']=='review_source_check'
    plane.role='reviewer';plane.read_source('source_fixture')
    feedback=review_source_feedback(plane,review,report)
    assert len(feedback)==1 and feedback[0]['code']=='review_source_binding'
    assert feedback[0]['value']['evidence']==[e['id']]
    report['claims'][0]['evidence']=[e['id']]
    assert review_source_feedback(plane,review,report)==[]


def test_review_can_reject_irrelevant_source_but_not_call_readable_text_unavailable(plane):
    from pitr.desk.research.quality import review_source_feedback
    plane.receipt('tool',{'name':'fetch_public_source','role':'reviewer','result':{'included':True,'source_id':'source_fixture'}})
    plane.role='reviewer';plane._record_reading('source_fixture',[],error='Page has no text')
    check={'source_id':'source_fixture','status':'unavailable','reason':'Page read failed','claim_ids':[],'evidence':[]}
    assert review_source_feedback(plane,{'source_checks':[check]},{} )
    check.update(status='irrelevant',reason='Wrong reporting period, not relevant to this question')
    assert review_source_feedback(plane,{'source_checks':[check]},{} )==[]


def test_new_review_source_binding_goes_to_researcher_not_reviewer_record_repair(plane):
    from pitr.desk.research.quality import run_quality
    source=plane.desk.ingest(b'Independent policy original for review.', 'text/plain','https://www.whitehouse.gov/second-fixture','PDD')
    plane.frozen['sources'][source.id]=source.digest
    class Researcher(FakeNative):
        def attempt(self,prompt):
            value=super().attempt(prompt)
            if self.calls>1:
                assert 'review_source_binding' in prompt
                value['claims'][0]['evidence'].append(self.p.read_source(source.id)['blocks'][0]['id'])
            return value
    class Reviewer(FakeNative):
        def attempt(self,prompt):
            value=super().attempt(prompt)
            self.p.receipt('tool',{'name':'fetch_public_source','role':'reviewer','result':{'included':True,'source_id':source.id}})
            e=self.p.read_source(source.id)['blocks'][0]
            value['source_checks']=[{'source_id':source.id,'status':'used','reason':'Changes the policy limitation','claim_ids':['changes'],'evidence':[e['id']]}]
            return value
    writer=Researcher(plane,'researcher',0);reviewer=Reviewer(plane,'reviewer',0)
    result=run_quality(plane,writer,reviewer)
    assert writer.calls==2 and reviewer.calls==2
    assert result['verification']['independent_review']=='passed'


def test_quality_gate_does_not_treat_execution_completion_as_delivery(plane):
    from pitr.desk.research.handoff import delivery_gate
    from pitr.desk.storage import Conflict
    report=validate(draft(claim()),plane)
    with pytest.raises(Conflict,match='独立复核'):delivery_gate(report)
    delivery_gate({**report,'delivery':{'status':'partial'},'verification':{'independent_review':'passed_with_gaps'}})
    with pytest.raises(Conflict):delivery_gate({'schema_version':1})


def test_html_does_not_label_unresolved_controller_feedback_as_review_pass(plane):
    from pitr.desk.research.report import html_report
    report=validate(draft(claim()),plane)
    report['reviews']=[{'verdict':'pass','summary':'模型未发现其他推理问题。','findings':[],
                        'feedback':[{'message':'新取得的原件尚未绑定到判断。'}]}]
    html=html_report(report)
    assert '独立复核：仍有待处理项' in html and '新取得的原件尚未绑定到判断。' in html
    report['reviews'][0]['feedback']=[]
    assert '独立复核：通过' in html_report(report)


def test_complete_numeric_literal_not_substring(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    with pytest.raises(ValueError,match='完整数字'):
        plane.register_numbers([{'evidence_id':e['id'],'text':'10','metric':'revenue','unit':'RMB_mn','period':'2025Q2','role':'company_actual','basis':'GAAP','frequency':'quarter'}])


def test_repeated_literal_returns_real_offsets_instead_of_asking_model_to_count(plane):
    upload=Research(plane.desk).upload(b'Current 100; previous 100.','text/plain','repeated.txt','PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest'];e=plane.read_source(upload['source_id'])['blocks'][0]
    item={'evidence_id':e['id'],'text':'100','metric':'revenue','unit':'RMB_mn','period':'2025FY','role':'broker_forecast','basis':'disclosed','frequency':'annual'}
    with pytest.raises(ValueError,match=r'items\[0\].start.*\[8, 22\]'):plane.register_numbers([item])
    with pytest.raises(ValueError,match=r'items\[0\].start=1.*\[8, 22\]'):plane.register_numbers([{**item,'start':1}])
    assert plane.register_numbers([{**item,'start':22}])[0]['source_locator']['start']==22


def test_stalled_revisions_save_diagnostic_after_alternative_attempt(plane):
    from pitr.desk.research.quality import run_quality
    class Stalled(FakeNative):
        def attempt(self,prompt):
            result=super().attempt(prompt)
            if self.role=='researcher':
                for c in result['claims']:c['calculations']=[]
            return result
    investigator=Stalled(plane,'researcher',100);reviewer=Stalled(plane,'reviewer',100)
    report=run_quality(plane,investigator,reviewer)
    assert investigator.calls==3 and report['delivery']['status']=='stalled'
    assert report['handoffs']==[] and report['status']=='needs_review'
    assert len(report['reviews'])==3


def test_reviewer_record_errors_are_not_sent_to_investigator(plane):
    from pitr.desk.research.quality import run_quality
    class BadReviewer(FakeNative):
        def attempt(self,prompt):
            result=super().attempt(prompt);result['check_receipts']=[];return result
    investigator=FakeNative(plane,'researcher',0);reviewer=BadReviewer(plane,'reviewer',0)
    report=run_quality(plane,investigator,reviewer)
    assert investigator.calls==1 and reviewer.calls==2
    assert report['delivery']['status']=='stalled'


def test_calculation_bridge_retains_unreconciled_residual(plane):
    def n(value):return plane._calc('operating_profit',value,'RMB_mn','2025Q2','scenario',[],basis='disclosed',frequency='quarter',assumption=True)['id']
    # Reconstructed consensus OP differs from the published consensus OP; this
    # is a basis question, not proof that the broker made an arithmetic mistake.
    result=plane.calculate_batch([{'operation':'sum_difference','left':n(61602),'right':n(35004),'alias':'gp_less_sales'},
        {'operation':'sum_difference','left':'gp_less_sales','right':n(1913),'alias':'less_admin'},
        {'operation':'sum_difference','left':'less_admin','right':n(3500),'alias':'reconstructed'},
        {'operation':'sum_difference','left':'reconstructed','right':n(21494)}])
    assert result['results'][-1]['value']==-309
    assert result['results'][-1]['assumption']


def test_public_fetch_preserves_historical_cutoff(plane,monkeypatch):
    import pitr.wiki.discovery
    monkeypatch.setattr(pitr.wiki.discovery,'fetch_public',lambda url,timeout:(b'New policy statement without verified publication time','text/plain',url,[]))
    frozen=plane.frozen['snapshot']
    result=plane.fetch_public_source('https://www.sec.gov/example')
    assert result['included'] is False and plane.frozen['snapshot']==frozen


def test_real_pdf_visual_read_returns_image_and_exact_receipt(plane):
    pdf=Path(__file__).parents[1]/'CMBI-PDD-2025-08-26.pdf'
    if not pdf.is_file():pytest.skip('licensed original unavailable')
    upload=Research(plane.desk).upload(pdf.read_bytes(),'application/pdf',pdf.name,'PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    result=plane.call('read_page',{'source_id':upload['source_id'],'page':3,'visual':True})
    assert result['_mcp_images'][0]['mimeType']=='image/png'
    assert '_mcp_images' not in list(plane.receipts('tool').values())[-1]['result']
    assert plane.receipts('reading')[result['reading_receipt']]['mode']=='visual'


def test_restore_checkpoint_resumes_pending_independent_review(plane):
    from pitr.desk.research.quality import run_quality
    from pitr.desk.research.tools import ToolPlane
    from pitr.desk.storage import Conflict
    class InterruptedReviewer(FakeNative):
        def attempt(self,prompt):raise Conflict('执行权已撤销')
    investigator=FakeNative(plane,'researcher',0)
    with pytest.raises(Conflict):run_quality(plane,investigator,InterruptedReviewer(plane,'reviewer',0))
    assert plane.state['quality']['phase']=='review'
    with plane.desk.store.connect() as db:task=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(plane.task['id'],)).fetchone()[0])
    restored=ToolPlane(plane.desk,task,plane.owner,lambda u:plane.queue.checkpoint(task,u));restored.input['workflow_version']=3
    writer=FakeNative(restored,'researcher',0);reviewer=FakeNative(restored,'reviewer',0)
    report=run_quality(restored,writer,reviewer)
    assert writer.calls==0 and reviewer.calls==1
    assert report['verification']['independent_review']=='passed'


def test_withdrawn_original_is_not_counted_as_valid_evidence(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    plane.desk.withdraw('source_fixture')
    report=validate(draft(claim(evidence=[e['id']])),plane)
    assert not report['evidence'] and report['claims'][0]['validation']=='needs_repair'
    assert any(i['code']=='source_invalidated' for i in report['issues'])


def test_withdrawal_changes_current_report_view_without_rewriting_history(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(evidence=[e['id']]));report=validate(raw,plane)
    body=canonical({'raw':raw,'validated':report})
    with plane.desk.store.connect(write=True) as db:
        db.execute('INSERT INTO research_artifacts VALUES(?,?,?)',(plane.task['id'],1,body))
    plane.desk.withdraw('source_fixture')
    view=Research(plane.desk).artifact(plane.request['id'])
    assert not view['evidence'] and view['claims'][0]['invalid_references'][0]['value']==e['id']
    assert view['delivery']['status']=='invalidated' and view['verification']['independent_review']=='invalidated'
    with plane.desk.store.connect() as db:
        assert db.execute('SELECT body FROM research_artifacts WHERE task_id=?',(plane.task['id'],)).fetchone()[0]==body


def test_nonfinancial_report_does_not_inherit_pdd_table_requirements(plane):
    upload=Research(plane.desk).upload('某行业政策调查，无财务预测表。'.encode(),'text/plain','policy-report.txt','PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    plane.input.update(intent='report_review',source_ids=[upload['source_id']])
    plane.state['requirements']={};plane.bootstrap_requirements()
    checks={r['check'] for r in plane.requirements()}
    assert 'public_investigation' in checks
    assert not checks & {'consensus_profit_reconciliation','segment_revenue_reconciliation'}


def test_html_declared_dates_do_not_backdate_availability_or_rewrite_document(plane):
    raw=b'<html><head><meta property="article:published_time" content="2025-07-30T20:00:49+00:00"><meta property="article:modified_time" content="2026-06-22T15:51:21+00:00"></head><body><h1>Policy</h1><p>Effective in August.</p></body></html>'
    doc=plane.desk.ingest(raw,'text/html','https://www.whitehouse.gov/test-policy','PDD')
    plane.frozen['sources'][doc.id]=doc.digest
    e=plane.read_source(doc.id)['blocks'][0]
    assert e['reported_date']=='2025-07-30' and e['published_at'].startswith('2025-07-30')
    assert e['modified_at'].startswith('2026-06-22') and '不等于' in e['publication_note']
    assert e['available_at']==doc.available_at==doc.observed_at
    assert plane.desk.document(doc.id)==doc


def test_table_number_coordinate_error_names_exact_item_and_fields(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    table=plane.receipt('table',{'source_id':'source_fixture','evidence_ids':[e['id']],'cells':[['100']]})
    item={'evidence_id':e['id'],'text':'100','metric':'revenue','unit':'RMB_mn','period':'2025Q2','basis':'GAAP','frequency':'quarter','role':'company_actual','table_id':table['id']}
    with pytest.raises(ValueError,match=r'items\[0\].row/column 缺失'):plane.register_numbers([item])
    with pytest.raises(ValueError,match=r'items\[0\].row/column=2/0'):plane.register_numbers([{**item,'row':2,'column':0}])


@pytest.mark.parametrize('text',['2025-08-25/26 电话会。','2Q S&M；4Q盈利拐点。','2026/27 年度预测。'])
def test_report_date_shorthand_does_not_remove_location(plane,text):
    e=plane.read_source('source_fixture')['blocks'][0]
    report=validate(draft(claim(text=text,evidence=[e['id']])),plane)
    assert not any(i['code']=='unbound_number' for i in report['issues'])


def test_revenue_submetric_does_not_get_mislabelled_as_group_revenue(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    c=plane._calc('transaction_services_growth',.7,'percent','2025Q2','growth',[e['id']],basis='GAAP')
    report=validate(draft(claim(text='交易服务收入同比{{'+c['id']+'}}。',calculations=[c['id']])),plane)
    assert not any(i['code']=='metric' for i in report['issues'])


def test_operating_margin_is_not_misclassified_as_operating_profit(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    c=plane._calc('operating_margin_subtract',2.7,'percentage_points','2025FY','subtract',[e['id']],basis='disclosed')
    report=validate(draft(claim(text='经营利润率上调{{'+c['id']+'}}。',evidence=[e['id']],calculations=[c['id']])),plane)
    assert not any(i['code']=='metric' for i in report['issues'])
    wrong=validate(draft(claim(text='经营利润上调{{'+c['id']+'}}。',evidence=[e['id']],calculations=[c['id']])),plane)
    assert any(i['code']=='metric' for i in wrong['issues'])


def test_per_ads_valuation_is_not_misclassified_as_earnings(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    c=plane._calc('sotp_value_per_ads_subtract',-.1,'USD_per_ADS','2025FY','subtract',[e['id']],basis='disclosed')
    report=validate(draft(claim(text='SOTP每ADS加总残差{{'+c['id']+'}}。',evidence=[e['id']],calculations=[c['id']])),plane)
    assert not any(i['code']=='metric' for i in report['issues'])


def test_report_author_conditions_become_located_requirements(plane):
    pdf=Path(__file__).parents[1]/'CMBI-PDD-2025-08-26.pdf'
    if not pdf.is_file():pytest.skip('local licensed regression original unavailable')
    upload=Research(plane.desk).upload(pdf.read_bytes(),'application/pdf',pdf.name,'PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest']
    plane.input.update(intent='report_review',source_ids=[upload['source_id']]);plane.state['requirements']={};plane.bootstrap_requirements()
    views=[r for r in plane.requirements() if r['id'].startswith('author_view_')]
    assert any('local fulfilment' in r['question'] and 'other countries' in r['question'] and r['pages']==[1] for r in views)


def test_answered_checkbox_cannot_hide_missing_author_conditions(plane):
    plane.register_requirements([{'id':'offsets','question':'核对业务模式抵消条件','required_concepts':[{'name':'半托管','terms':['半托管','semi-entrusted']},{'name':'本地履约','terms':['本地履约','local fulfilment']}]}])
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(text='交易服务影响尚不确定。',evidence=[e['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'offsets','status':'answered','claim_ids':['c'],'explanation':'半托管和本地履约都已核对'}]
    check=next(c for c in validate(raw,plane)['coverage'] if c['key']=='offsets')
    assert check['status']=='invalid' and '半托管' in check['explanation']
    raw['claims'][0]['original_claim']='作者认为半托管和本地履约可抵消影响。'
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='offsets')['status']=='invalid'
    raw['claims'][0]['text']='半托管和本地履约的抵消影响缺少分部数据验证。'
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='offsets')['status']=='answered'


def test_batch_retains_successful_siblings_and_precise_error(plane):
    a=plane._calc('revenue',100,'RMB_mn','2025Q2','observation',[],basis='GAAP',frequency='quarter')
    b=plane._calc('revenue',90,'RMB_mn','2025Q2','observation',[],basis='disclosed',frequency='quarter')
    result=plane.calculate_batch([{'operation':'compare','left':a['id'],'right':b['id'],'alias':'bad'},
        {'operation':'add','left':a['id'],'right':a['id'],'alias':'good'}])
    assert result['results'][0]['value']==200 and result['status']=='partial'
    assert result['errors'][0]['index']==0 and 'basis' in result['errors'][0]['message']
    assert result['aliases']['good'] and 'bad' not in result['aliases']


def test_review_can_attach_calculation_checks_to_own_reading(plane):
    from pitr.desk.research.quality import review_feedback
    plane.role='reviewer';plane.read_source('source_fixture')
    reading=next(r for r in plane.receipts('reading').values() if r['role']=='reviewer')
    calc=plane.financial_observations('revenue')[0]
    review={'checked_requirements':[r['id'] for r in plane.requirements()],'check_receipts':[reading['id'],calc['id']], 'findings':[], 'additional_requirements':[]}
    assert not review_feedback(plane,review,{})


def test_review_checkpoint_is_additional_context_not_independent_reading(plane):
    from pitr.desk.research.quality import review_feedback
    checkpoint=plane.receipt('checkpoint',{'finding':'已保存调查结论'})
    review={'checked_requirements':[r['id'] for r in plane.requirements()],'check_receipts':[checkpoint['id']], 'findings':[], 'additional_requirements':[]}
    assert any(x['code']=='review_reading' for x in review_feedback(plane,review,{}))
    plane.role='reviewer';plane.read_source('source_fixture')
    reading=next(r for r in plane.receipts('reading').values() if r['role']=='reviewer')
    review['check_receipts'].append(reading['id'])
    assert not review_feedback(plane,review,{})
    review['check_receipts'].append('checkpoint_missing')
    errors=review_feedback(plane,review,{})
    assert len(errors)==1 and errors[0]['field']=='check_receipts[2]' and errors[0]['value']=='checkpoint_missing'


def test_report_financial_subheading_retains_coverage_and_original_requirement(plane):
    plane.input['intent']='report_review'
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(section='cash_margin',original_claim='作者的盈利判断',original_evidence=[e['id']],evidence=[e['id']]))
    result=validate(raw,plane)
    assert result['claims'][0]['validation']=='integrity_checked'
    raw['claims'][0]['original_evidence']=[]
    assert any(i['code']=='original_claim' for i in validate(raw,plane)['issues'])


def test_blank_pdf_page_is_visible_and_not_claimed_read(plane):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>']
    data=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(data));data+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(data);data+=b'xref\n0 5\n0000000000 65535 f \n'+b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])+f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()
    uploaded=Research(plane.desk).upload(data,'application/pdf','blank-page.pdf','PDD')
    plane.frozen['sources'][uploaded['source_id']]=uploaded['digest']
    assert plane.source_index(uploaded['source_id'])[0]['page_count']==2
    statuses=[r for r in plane.reading_status() if r['source_id']==uploaded['source_id']]
    assert len(statuses)==2 and statuses[1]['status']=='unread'
    plane.read_page(uploaded['source_id'],2,visual=True)
    assert next(r for r in plane.reading_status() if r['source_id']==uploaded['source_id'] and r['page']==2)['status']=='read'


def test_read_financial_table_without_calculating_is_not_answered(plane):
    upload=Research(plane.desk).upload(b'Figure 2: Earnings revision\n\nNet profit current 104.0 previous 94.9','text/plain','revision.txt','PDD')
    sid=upload['source_id'];plane.frozen['sources'][sid]=upload['digest']
    plane.register_requirements([{'id':'forecast_table','question':'Figure 2: Earnings revision','source_id':sid,'kind':'table'}])
    e=plane.read_source(sid)['blocks'][1]
    raw=draft(claim(original_claim='Author gives 9.6% revision',evidence=[e['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'forecast_table','status':'answered','claim_ids':['c']}]
    first=validate(raw,plane)
    assert next(c for c in first['coverage'] if c['key']=='forecast_table')['status']=='invalid'
    numbers=plane.register_numbers([{'evidence_id':e['id'],'text':v,'metric':'net_income','unit':'RMB_bn','period':'2025FY','basis':'non-GAAP','frequency':'annual','role':'broker_forecast'} for v in ('104.0','94.9')])
    calc=plane.calculate('compare',numbers[0]['id'],numbers[1]['id'])
    raw['claims'][0]['calculations']=[calc['id']]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='forecast_table')['status']=='answered'


def quoted_inputs(plane, values, metric, role, unit='RMB_mn', period='2025Q2'):
    upload=Research(plane.desk).upload(('Values: '+' ; '.join(values)).encode(),'text/plain','reconciliation.txt','PDD')
    plane.frozen['sources'][upload['source_id']]=upload['digest'];e=plane.read_source(upload['source_id'])['blocks'][0]
    items=[{'evidence_id':e['id'],'text':v,'metric':metric,'role':role,'unit':unit,'period':period,'frequency':'quarter' if 'Q' in period else 'annual','basis':'disclosed'} for v in values]
    return upload['source_id'],plane.register_numbers(items)


def test_reconciliation_distinguishes_real_residual_from_original_rounding(plane):
    _,ns=quoted_inputs(plane,['61,602','35,004','1,913','3,500','21,494'],'operating_profit','reported_consensus')
    result=plane.reconcile_totals([x['id'] for x in ns[:4]],ns[-1]['id'],[1,-1,-1,-1])
    assert result['component_total']['value']==21185 and result['residual']['value']==-309
    assert result['rounding_bound']['value']==2.5 and not result['within_original_rounding']
    assert '不一致可能' in result['residual']['limitations'][-1]
    _,ns=quoted_inputs(plane,['94.0','1.9','20.5','29.8','146.3'],'valuation','broker_forecast','USD_per_ADS','2025FY')
    result=plane.reconcile_totals([x['id'] for x in ns[:4]],ns[-1]['id'])
    assert result['residual']['value']==pytest.approx(-.1) and result['within_original_rounding']


def test_segment_forecast_check_requires_original_report_reconciliation(plane):
    sid,ns=quoted_inputs(plane,['274,178','20,692','220,919','426,673'],'revenue','broker_forecast',period='2025FY')
    plane.register_requirements([{'id':'segment_check','question':'原研报分部与合并预测勾稽','source_id':sid,'check':'segment_revenue_reconciliation'}])
    e=plane.read_source(sid)['blocks'][0]
    raw=draft(claim(evidence=[e['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'segment_check','status':'answered','claim_ids':['c']}]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='segment_check')['status']=='invalid'
    result=plane.reconcile_totals([x['id'] for x in ns[:3]],ns[-1]['id'])
    assert result['residual']['value']==89116 and not result['within_original_rounding']
    raw['claims'][0]['calculations']=[result['residual']['id']]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='segment_check')['status']=='answered'


def test_revision_percent_cannot_be_replaced_by_absolute_change(plane):
    sid,ns=quoted_inputs(plane,['104.0','94.9'],'net_income','broker_forecast','RMB_bn','2025FY')
    plane.register_requirements([{'id':'revision_check','question':'重算预测修订百分比','source_id':sid,'check':'forecast_revision_ratios','required_metrics':['net_income'],'required_periods':['2025E']}])
    e=plane.read_source(sid)['blocks'][0]
    raw=draft(claim(evidence=[e['id']],calculations=[plane.calculate('sum_difference',ns[0]['id'],ns[1]['id'])['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'revision_check','status':'answered','claim_ids':['c']}]
    first=next(c for c in validate(raw,plane)['coverage'] if c['key']=='revision_check')
    assert first['status']=='invalid' and 'net_income / 2025E' in first['explanation']
    calc=plane.calculate('compare',ns[0]['id'],ns[1]['id'])
    assert calc['value']==pytest.approx(9.58904109589)
    raw['claims'][0]['calculations'].append(calc['id'])
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='revision_check')['status']=='answered'
    reading=plane.read_source(sid)
    receipt=list(plane.receipts('reading'))[-1]
    raw['requirement_resolutions']=[{'requirement_id':'revision_check','status':'gap','claim_ids':['c'],'explanation':'预测修订计算工具拒绝比较，无法核算。','needed_input':'工具支持不同指标名','check_receipts':[receipt]}]
    result=next(c for c in validate(raw,plane)['coverage'] if c['key']=='revision_check')
    assert result['status']=='invalid' and '不是资料缺口' in result['explanation']
    raw['requirement_resolutions'][0].update(explanation='Figure已读取，全部compare计算未成功。',needed_input='需要重新登记旧预测口径并重跑compare，或取得模型原始表。')
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='revision_check')['status']=='invalid'


def test_actual_consensus_ratios_cannot_be_replaced_by_other_table_math(plane):
    sid,ns=quoted_inputs(plane,['25,793','21,494'],'operating_profit','reported_actual')
    # The same quoted table explicitly distinguishes actual from reported consensus.
    e=plane.read_source(sid)['blocks'][0]
    consensus=plane.register_numbers([{'evidence_id':e['id'],'text':'21,494','metric':'operating_profit','role':'reported_consensus','unit':'RMB_mn','period':'2025Q2','basis':'disclosed','frequency':'quarter'}])[0]
    plane.register_requirements([{'id':'actual_check','question':'Actual versus consensus','source_id':sid,'check':'consensus_comparison_ratios','required_comparisons':[{'metric':'operating_profit','period':'2025Q2'}]}])
    raw=draft(claim(evidence=[e['id']],calculations=[plane.calculate('subtract',ns[0]['id'],consensus['id'])['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'actual_check','status':'answered','claim_ids':['c']}]
    first=next(c for c in validate(raw,plane)['coverage'] if c['key']=='actual_check')
    assert first['status']=='invalid' and 'operating_profit / 2025Q2' in first['explanation']
    compare=plane.calculate('compare',ns[0]['id'],consensus['id'])
    assert compare['value']==pytest.approx(20.000930492)
    raw['claims'][0]['calculations'].append(compare['id'])
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='actual_check')['status']=='answered'


def test_forecast_identity_error_explains_exact_metrics_and_repair(plane):
    left=plane._calc('revenue_current',100,'RMB_mn','2025FY','source_literal',[],basis='disclosed')
    right=plane._calc('revenue_previous',90,'RMB_mn','2025FY','source_literal',[],basis='disclosed')
    with pytest.raises(ValueError) as error:plane.calculate('compare',left['id'],right['id'])
    assert all(text in str(error.value) for text in ('left.metric=revenue_current','right.metric=revenue_previous','role/column_label','重新登记'))


def test_list_separator_does_not_bind_previous_revenue_noun_to_pe(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    pe=plane._calc('pe_multiple',12.5,'multiple','2025FY','source_literal',[e['id']],basis='disclosed')
    raw=draft(claim(evidence=[e['id']],alternative='估值取决于分部收入、主站PE倍数{{'+pe['id']+'}}。',calculations=[pe['id']]))
    assert not any(i['code']=='metric' for i in validate(raw,plane)['issues'])


def test_sotp_price_requires_calculated_total_and_retains_rounding(plane):
    sid,ns=quoted_inputs(plane,['94.0','1.9','20.5','29.8','146.3'],'valuation','broker_forecast','USD_per_ADS','2025FY')
    plane.register_requirements([{'id':'price_check','question':'SOTP每ADS加总','source_id':sid,'check':'valuation_price_reconciliation'}])
    e=plane.read_source(sid)['blocks'][0]
    raw=draft(claim(evidence=[e['id']],calculations=[ns[-1]['id']]))
    raw['requirement_resolutions']=[{'requirement_id':'price_check','status':'answered','claim_ids':['c']}]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='price_check')['status']=='invalid'
    rec=plane.reconcile_totals([x['id'] for x in ns[:4]],ns[-1]['id'])
    raw['claims'][0]['calculations']=[rec['residual']['id']]
    result=validate(raw,plane)
    assert next(c for c in result['coverage'] if c['key']=='price_check')['status']=='answered'
    assert next(c for c in result['calculations'] if c['id']==rec['component_total']['id'])['value']==pytest.approx(146.2)
    assert rec['within_original_rounding']


def test_equivalent_unit_spelling_is_normalized_without_scaling(plane):
    _,ns=quoted_inputs(plane,['94.0','1.9'],'valuation','broker_forecast','USD/ADS','2025FY')
    assert ns[0]['unit']=='USD_per_ADS' and ns[0]['value']==94
    assert ns[0]['source_locator']['original_unit']=='USD/ADS'
    _,ns=quoted_inputs(plane,['103,985'],'revenue','reported_actual','RMB mn')
    assert ns[0]['unit']=='RMB_mn' and ns[0]['value']==103985
    from pitr.desk.research.units import canonical_unit
    assert canonical_unit('USD per order')=='USD per order'
    assert canonical_unit('RMB bn')=='RMB_bn'


def test_public_investigation_needs_actual_acquisition_attempt(plane,monkeypatch):
    plane.register_requirements([{'id':'policy_check','question':'政策原件补查','check':'public_investigation'}])
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(evidence=[e['id']]));raw['requirement_resolutions']=[{'requirement_id':'policy_check','status':'answered','claim_ids':['c']}]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='invalid'
    monkeypatch.setattr(plane,'search_public',lambda query:plane.receipt('discovery',{'candidates':[{'url':'https://www.example.gov/policy'}],'actual_searches':[{'query':query}],'query':query}))
    plane.call('search_public',{'query':'public policy'})
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='invalid'
    doc=plane.desk.ingest(b'Policy original states an effective date and scope.','text/plain','https://www.example.gov/policy','PDD')
    plane.frozen['sources'][doc.id]=doc.digest
    monkeypatch.setattr(plane,'fetch_public_source',lambda url:{'source_id':doc.id,'included':True})
    plane.call('fetch_public_source',{'url':doc.url})
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='invalid'
    ref=plane.read_source(doc.id)['blocks'][0]
    raw['claims'][0]['evidence'].append(ref['id'])
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='answered'


def test_public_no_results_is_gap_but_unread_candidate_is_unfinished(plane,monkeypatch):
    plane.register_requirements([{'id':'policy_check','question':'政策原件补查','check':'public_investigation'}])
    e=plane.read_source('source_fixture')['blocks'][0]
    discovery=plane.receipt('discovery',{'candidates':[],'actual_searches':[{'query':'policy original'}]})
    raw=draft(claim(evidence=[e['id']],verdict='insufficient'))
    raw['requirement_resolutions']=[{'requirement_id':'policy_check','status':'gap','claim_ids':['c'],'explanation':'原件和合理公开搜索均未找到所需政策依据。','needed_input':'政策原件','check_receipts':[discovery['id']]}]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='gap'
    plane.receipt('discovery',{'candidates':[{'url':'https://www.example.gov/policy'}],'actual_searches':[{'query':'alternate policy original'}]})
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='invalid'
    def unavailable(url):raise ValueError('HTTP 404: original unavailable')
    monkeypatch.setattr(plane,'fetch_public_source',unavailable)
    with pytest.raises(ValueError):plane.call('fetch_public_source',{'url':'https://www.example.gov/policy'})
    raw['requirement_resolutions'][0].update(explanation='已找到原件路径但实际获取返回 HTTP 404，未取得原件。',check_receipts=list(plane.receipts('tool'))[-1:])
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='policy_check')['status']=='gap'


def test_access_challenge_is_not_ingested_as_an_official_original(plane,monkeypatch):
    from pitr.wiki import discovery
    monkeypatch.setattr(discovery,'fetch_public',lambda url,timeout:(b'<html><title>Federal Register :: Request Access</title><body>Request access to continue</body></html>','text/html','https://unblock.federalregister.gov',[{'status':200}]))
    before={d.id for d in plane.desk.documents('PDD')}
    with pytest.raises(ValueError,match='访问验证页'):plane.call('fetch_public_source',{'url':'https://www.federalregister.gov/documents/policy'})
    assert {d.id for d in plane.desk.documents('PDD')}==before
    failure=list(plane.receipts('acquisition_failure').values())[-1]
    assert failure['final_url']=='https://unblock.federalregister.gov' and failure['attempts'][0]['status']==200


def test_gap_accepts_real_public_discovery_and_locates_invalid_receipt(plane):
    plane.register_requirements([{'id':'mode_gap','question':'核对未披露的业务模式拆分'}])
    e=plane.read_source('source_fixture')['blocks'][0]
    discovery=plane.receipt('discovery',{'query':'business model official disclosure','actual_searches':[{'query':'business model official disclosure'}],'candidates':[]})
    raw=draft(claim(evidence=[e['id']],verdict='insufficient'))
    raw['requirement_resolutions']=[{'requirement_id':'mode_gap','status':'gap','claim_ids':['c'],'explanation':'已读原文并尝试补查，未取得地区经营数据。','needed_input':'地区收入拆分','check_receipts':[list(plane.receipts('reading'))[-1],discovery['id']]}]
    assert next(c for c in validate(raw,plane)['coverage'] if c['key']=='mode_gap')['status']=='gap'
    raw['requirement_resolutions'][0]['check_receipts'].append('discovery_unknown')
    result=next(c for c in validate(raw,plane)['coverage'] if c['key']=='mode_gap')
    assert result['status']=='invalid' and 'check_receipts[2]=discovery_unknown' in result['explanation']


def test_public_search_requires_actual_browser_events_not_model_claims():
    from pitr.agent_runtime.runtime import verified_searches
    from pitr.agent_runtime.transport import AgentError
    with pytest.raises(AgentError,match='没有实际成功的检索事件'):
        verified_searches([{'type':'item.completed','item':{'type':'agent_message','text':'I searched the public web.'}}])
    event={'type':'item.completed','item':{'type':'web_search','query':'official policy','action':{'type':'search','query':'official policy'}}}
    assert verified_searches([event])[0]['query']=='official policy'


def test_invalid_batch_shape_is_field_feedback_and_keeps_siblings(plane):
    c=plane._calc('revenue',100,'RMB_mn','2025Q2','observation',[],basis='GAAP')
    result=plane.calculate_batch([{'operation':'add','left':[c['id']],'right':c['id']},{'operation':'add','left':c['id'],'right':c['id']}])
    assert 'left' in result['errors'][0]['message'] and result['results'][0]['value']==200


def test_ratio_and_residual_metric_names_do_not_create_false_amount_errors(plane):
    e=plane.read_source('source_fixture')['blocks'][0]
    a=plane._calc('sales_marketing',26,'RMB_mn','2025Q2','observation',[e['id']],basis='GAAP')
    b=plane._calc('revenue',100,'RMB_mn','2025Q2','observation',[e['id']],basis='GAAP')
    c=plane.calculate('divide',a['id'],b['id'])
    raw=draft(claim(text='S&M/收入为{{'+c['id']+'}}。',calculations=[c['id']]))
    assert not any(i['code']=='metric' for i in validate(raw,plane)['issues'])


@pytest.mark.parametrize('date',['26 August 2025','26 Aug 2025','AUG. 26, 2025','2025年8月26日','2025-08-26'])
@pytest.mark.parametrize('url',['https://investor.pddholdings.com/later','upload:later.txt'])
def test_subsequent_source_cannot_hide_under_general_temporal_scope(plane,date,url):
    upload=Research(plane.desk).upload((date+'\n\nOriginal broker claim').encode(),'text/plain','dated.txt','PDD')
    sid=upload['source_id'];plane.frozen['sources'][sid]=upload['digest'];plane.input.update(source_ids=[sid],intent='report_review')
    doc=plane.desk.ingest(b'28 Aug 2025\n\nSubsequent information','text/plain',url,'PDD')
    plane.frozen['sources'][doc.id]=doc.digest
    original=plane.read_source(sid)['blocks'][0];later=plane.read_source(doc.id)['blocks'][-1]
    assert original['reported_date']=='2025-08-26' and later['reported_date']=='2025-08-28'
    assert original['available_at']==plane.desk.document(sid).available_at
    raw=draft(claim(section='claims',original_claim='原报告观点',original_evidence=[original['id']],evidence=[later['id']],temporal_scope='general'))
    assert any(i['code']=='temporal' for i in validate(raw,plane)['issues'])
    raw['claims'][0]['temporal_scope']='subsequent'
    assert not any(i['code']=='temporal' for i in validate(raw,plane)['issues'])


def test_real_pdf_date_is_not_upload_date_or_reporting_period(plane):
    from pitr.desk.research.workspace import reported_date
    path=Path(__file__).parents[1]/'CMBI-PDD-2025-08-26.pdf'
    if not path.is_file():pytest.skip('local licensed regression original unavailable')
    upload=Research(plane.desk).upload(path.read_bytes(),'application/pdf',path.name,'PDD')
    doc=plane.desk.document(upload['source_id'])
    assert reported_date(doc)=='2025-08-26'
    assert doc.available_at==doc.observed_at and doc.available_at[:10]!='2025-08-26'
    assert reported_date(doc.model_copy(update={'blocks':[doc.blocks[0].model_copy(update={'text':'Quarter ended June 30, 2025'})]}))==''


def test_versioned_real_artifact_can_be_read_through_report_api(plane):
    from fastapi.testclient import TestClient
    from pitr.desk.api import create_app
    from pitr.desk.research.quality import persist
    e=plane.read_source('source_fixture')['blocks'][0]
    raw=draft(claim(evidence=[e['id']]))
    saved=persist(plane,raw,validate(raw,plane),'草稿核验')
    with TestClient(create_app(plane.desk.root,worker=False)) as client:
        response=client.get('/api/desk/research/requests/'+plane.request['id']+'/report')
        assert response.status_code==200,response.text
        assert response.json()['artifact_version']==saved['artifact_version']
        assert response.json()['schema_version']==3

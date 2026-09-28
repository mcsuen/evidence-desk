import json
import pytest
from pitr.adapters.identity.rules import security_key
from pitr.adapters.identity.markets import HKEX,SEC,SSE,SZSE,official_json

@pytest.mark.parametrize('raw,expected',[
    ({'exchange':'SEHK','ticker':'00700.HK'},('HKEX','700')),
    ({'exchange':'SZ','ticker':'000001.SZ'},('SZSE','000001')),
    ({'exchange':'BSE','ticker':'920090.BJ'},('BSE','920090')),
    ({'exchange':'NYSE','ticker':'BRK.B'},('NYSE','BRK.B')),
    ({'exchange':'NASDAQ','ticker':'GOOG'},('NASDAQ','GOOG')),
    ({'exchange':'The Stock Exchange of Hong Kong Limited','ticker':'00700'},('HKEX','700')),
    ({'exchange':'The Nasdaq Stock Market LLC','ticker':'MSFT'},('NASDAQ','MSFT')),
    ({'exchange':'上海证券交易所','ticker':'600519'},('SSE','600519')),
])
def test_market_symbols_preserve_meaning(raw,expected):assert security_key(raw)==expected


@pytest.mark.parametrize('quote',[
    'changed on 24th January, 2008','changed on 24 January 2008',
    'changed on January 24, 2008','changed on 24 Jan 2008',
    '于2008年01月24日变更','于2008年1月24日变更','changed on 2008/01/24',
])
def test_official_effective_date_typography_is_not_a_missing_date(quote):
    from pitr.adapters.identity.rules import date_in_quote
    assert date_in_quote('2008-01-24',quote)
    assert not date_in_quote('2008-02-24',quote)


def test_hk_directory_full_width_share_markers_match_without_dropping_business_name():
    from pitr.adapters.identity.rules import directory_name_key
    assert directory_name_key('示例集團－Ｗ','HKEX')==directory_name_key('示例集团','HKEX')
    assert directory_name_key('EXAMPLE－ＳＷ','HKEX')==directory_name_key('EXAMPLE','HKEX')
    assert directory_name_key('示例科技－Ｗ','HKEX')!=directory_name_key('示例集团','HKEX')


def test_hk_directory_uses_actual_internal_id_and_never_labels_catalog_as_original():
    calls=[]
    def get(url):
        calls.append(url)
        if 'prefix.do' in url:return b'callback({"stockInfo":[{"name":"EXAMPLE","code":"01234","stockId":4567}]});'
        return b'<a href="/listedco/listconews/sehk/2026/0825/2026082500556.pdf">INTERIM REPORT 2026</a><a href="/listedco/listconews/sehk/2026/0409/2026040901357.pdf">NOTICE OF AGM</a>'
    adapter=HKEX();candidate=adapter.find_candidates('Example',[{'exchange':'HKEX','ticker':'1234'}],get)[0]
    rows=adapter.list_disclosures(candidate,get)
    assert 'stockId=4567' in calls[-1] and rows[0].document_type=='interim_report'
    assert rows[0].published_at=='2026-08-25' and rows[1].document_type=='identity_notice'
    assert all(r.url!=r.source for r in rows)


def test_sec_directories_use_cik_and_actual_accession_and_cutoff():
    def get(url):
        if 'company_tickers' in url:return json.dumps({'fields':['cik','name','ticker','exchange'],'data':[[123,'Example Corp','EXM','Nasdaq']]}).encode()
        return json.dumps({'filings':{'recent':{'form':['10-K','10-Q'],'filingDate':['2026-02-01','2026-08-01'],
            'reportDate':['2025-12-31','2026-06-30'],'accessionNumber':['0000123-26-000001','0000123-26-000002'],
            'primaryDocument':['actual-annual.htm','actual-quarter.htm']}}}).encode()
    adapter=SEC();candidate=adapter.find_candidates('Example Corp',[],get)[0]
    rows=adapter.list_disclosures(candidate,get,'2026-03-01')
    assert candidate.identifiers['SEC']=='0000000123' and len(rows)==1
    assert rows[0].url.endswith('/123/000012326000001/actual-annual.htm')


def test_official_directory_error_is_not_empty_result():
    with pytest.raises(ValueError,match='繁忙'):official_json('callback({"success":"false","error":"繁忙"});'.encode())


@pytest.mark.parametrize('name',['示例新能源科技股份有限公司','Example Technology Co., Limited','Example Technology Co., Limited · 示例科技'])
def test_szse_full_master_resolves_legal_and_bilingual_names_without_model_codes(name):
    import io,zipfile
    from html import escape
    headers=['公司代码','公司简称','公司全称','英文名称','A股代码']
    values=['000009','示例科技','示例新能源科技股份有限公司','Example Technology Co., Limited','000009']
    xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    for i,row in enumerate([headers,values],1):
        xml+='<row>'+''.join(f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t>{escape(v)}</t></is></c>' for j,v in enumerate(row))+'</row>'
    xml+='</sheetData></worksheet>';buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:z.writestr('xl/worksheets/sheet1.xml',xml)
    calls=[]
    def acquire(url):
        calls.append(url)
        return buffer.getvalue() if 'SHOWTYPE=xlsx' in url else b'[{"data":null}]'
    candidates=SZSE().find_candidates(name,[],acquire)
    assert len(candidates)==1 and candidates[0].code=='000009'
    assert candidates[0].name==values[2] and values[3] in candidates[0].aliases
    assert 'SHOWTYPE=xlsx' in candidates[0].source and len(calls)==2


def test_sse_full_name_lookup_reads_all_pages_and_preserves_row_origin():
    from urllib.parse import parse_qs,urlsplit
    first={'FULL_NAME':'示例科技股份有限公司','SEC_NAME_CN':'示例科技','FULL_NAME_IN_ENGLISH':'Example Technology Co., Ltd.',
           'A_STOCK_CODE':'688001','COMPANY_CODE':'issuer-one'}
    def acquire(url):
        query=parse_qs(urlsplit(url).query,keep_blank_values=True)
        if query['STOCK_CODE'][0]:return b'{"result":null}'
        row=first if query['pageHelp.pageNo']==['1'] else {**first,'FULL_NAME':'其他公司','SEC_NAME_CN':'其他公司','FULL_NAME_IN_ENGLISH':None,'A_STOCK_CODE':'688002'}
        return json.dumps({'result':[row],'pageHelp':{'pageCount':2}}).encode()
    rows=SSE().find_candidates('示例科技股份有限公司',[],acquire)
    assert len(rows)==1 and rows[0].code=='688001' and 'pageHelp.pageNo=1' in rows[0].source


@pytest.mark.parametrize('item',[
    {'type':'web_search','status':'completed','action':{'type':'openPage','url':'https://example.com'}},
    {'type':'web_search','status':'cancelled','action':{'type':'search','query':'company'}},
    {'type':'web_search','status':'failed','action':{'type':'search','query':'company'}},
])
def test_non_search_success_cannot_be_search_receipt(item):
    from pitr.agent_runtime.runtime import verified_searches
    with pytest.raises(RuntimeError):verified_searches([{'type':'item.completed','item':item}])


def test_claude_nested_search_error_is_not_success():
    from pitr.agent_runtime.runtime import verified_searches
    with pytest.raises(RuntimeError):verified_searches([
        {'type':'item.started','item':{'id':'x','name':'WebSearch'}},
        {'type':'item.completed','item':{'id':'x','result':[{'type':'web_search_tool_result_error','error_code':'rate_limited'}]}}])


def test_report_discovery_does_not_confuse_summary_or_meeting_with_financial_original():
    from pitr.adapters.identity.markets import document_type
    assert document_type('Example：2026年半年度报告')=='interim_report'
    assert document_type('Example：关于召开半年度报告业绩说明会的公告')=='other'
    assert document_type('Example：2025年年度报告摘要')=='other'
    assert document_type('Example：2025年年度报告')=='annual_report'
    assert document_type('POLL RESULTS OF THE ANNUAL GENERAL MEETING')=='other'


@pytest.mark.parametrize('title',[
    'INSIDE INFORMATION DELAY IN PUBLICATION OF 2025 ANNUAL RESULTS AND DELAY IN DESPATCH OF THE 2025 ANNUAL REPORT',
    'FURTHER DELAY IN PUBLICATION OF INTERIM RESULTS',
    'POSTPONEMENT OF RELEASE OF ANNUAL RESULTS',
    '延遲刊發二零二五年年度業績及寄發年報',
    '关于延期披露2025年年度报告的公告',
    'BOARD MEETING TO APPROVE ANNUAL RESULTS',
])
def test_disclosure_administration_is_not_an_actual_financial_report(title):
    from pitr.adapters.identity.markets import document_type
    assert document_type(title)=='other'


@pytest.mark.parametrize('title',[
    'Letter to Registered Shareholders - Notice of Publication of (1) 2026 Annual Report, (2) Circular dated 7 September 2026, and (3) Proxy Form',
    'Letter to Non-registered shareholders - Notice of Publication of 2026 Annual Report',
    'Notification Letter to Non-registered Shareholders - Notice of Publication of 2025/26 Interim Report',
    '(1) UPDATES ON DISCLAIMER OF OPINION SET OUT IN THE ANNUAL REPORT FOR THE YEARS 2024 AND 2025; AND (2) BUSINESS UPDATES',
    'Electronic Dissemination of Corporate Communications - Annual Report 2026',
    '致股東之函件：2026年中期報告',
    '寄發2026年年報及股東通函之通知',
])
def test_report_publication_letters_and_cross_references_are_not_report_originals(title):
    from pitr.adapters.identity.markets import document_type
    assert document_type(title)=='other'


def test_report_supplement_is_not_the_financial_statement_it_refers_to():
    from pitr.adapters.identity.markets import document_type
    assert document_type('SUPPLEMENTAL ANNOUNCEMENT IN RELATION TO THE INTERIM REPORT FOR THE SIX MONTHS ENDED 30 JUNE 2024')=='other'
    assert document_type('2024年半年度报告补充说明公告')=='other'
    assert document_type('2024 Interim Report (Revised)')=='interim_report'


@pytest.mark.parametrize('title',[
    'ESTIMATED RESULTS FOR THE NINE MONTHS ENDING\n30 SEPTEMBER 2026',
    'EXPECTED ANNUAL RESULTS FOR THE YEAR ENDING 2026',
    'PROFIT WARNING IN RESPECT OF INTERIM RESULTS',
    'POSITIVE PROFIT ALERT',
    '2026年半年度业绩预告',
    '二零二六年全年盈利預測',
    'ANNOUNCEMENT OF FINAL OFFER PRICE AND\nALLOTMENT RESULTS',
    '2026年半年度业绩快报',
])
def test_forecasts_and_offering_outcomes_are_not_published_financials(title):
    from pitr.adapters.identity.markets import document_type
    assert document_type(title) not in ('annual_report','interim_report','quarterly_report','results')


def test_sec_former_names_and_results_exhibits_are_official_located_data():
    from pitr.adapters.identity.markets import Candidate
    candidate=Candidate('New Issuer','NASDAQ','NEW',{'SEC':'0000000123'})
    def acquire(url):
        if 'submissions/' in url:
            return json.dumps({'formerNames':[{'name':'Old Issuer','from':'2010-01-01','to':'2020-01-01'}],
                'filings':{'recent':{'form':['6-K'],'filingDate':['2026-08-01'],'reportDate':['2026-06-30'],
                    'accessionNumber':['0000123-26-000003'],'primaryDocument':['cover.htm']}}}).encode()
        return b'<p>Financial results for the quarter</p><a href="actual-ex99.htm">Exhibit 99.1</a><a href="https://other.example.com/ex99.htm">External</a>'
    rows=SEC().list_disclosures(candidate,acquire)
    assert candidate.historical_names[0]['pointer']=='/formerNames/0'
    assert candidate.historical_names[0]['digest']
    assert [r.url for r in rows if r.document_type=='results']==['https://www.sec.gov/Archives/edgar/data/123/000012326000003/actual-ex99.htm']
    assert rows[-1].period=='2026-06-30'


def test_szse_disclosure_paginates_until_financial_originals():
    from pitr.adapters.identity.markets import Candidate
    pages=[]
    def acquire(url,query):
        pages.append(query['pageNum'])
        title='公司临时公告' if query['pageNum']==1 else '2025年年度报告'
        return json.dumps({'announceCount':2,'data':[{'title':title,'publishTime':'2026-04-01','attachPath':'actual'+str(query['pageNum'])+'.pdf'}]}).encode()
    rows=SZSE().list_disclosures(Candidate('Example','SZSE','000001'),acquire)
    assert pages==[1,2] and rows[-1].document_type=='annual_report'


def test_bse_catalog_filters_other_issuers_and_cutoff():
    from pitr.adapters.identity.markets import BSE,Candidate
    def acquire(url,query):
        assert query['companyCd']=='920090' and query['page']=='0'
        return json.dumps([{'listInfo':{'totalPages':1,'content':[
            {'companyCd':'920090','disclosureTitle':'2025年年度报告','destFilePath':'/actual.pdf','publishDate':'2026-04-01'},
            {'companyCd':'920001','disclosureTitle':'2025年年度报告','destFilePath':'/wrong.pdf','publishDate':'2026-04-01'},
            {'companyCd':'920090','disclosureTitle':'2026年半年度报告','destFilePath':'/future.pdf','publishDate':'2026-08-01'}]}}]).encode()
    rows=BSE().list_disclosures(Candidate('Example','BSE','920090'),acquire,'2026-06-01')
    assert len(rows)==1 and rows[0].url=='https://www.bse.cn/actual.pdf'

"""Acquisition faults must retain evidence and leave honest coverage gaps."""
from datetime import datetime, timezone, timedelta
import socket
import httpx
import pytest

from test_wiki_jobs import lab
from pitr.wiki.discovery import fetch_public, FetchError, retry_after
from pitr.wiki.acquisition import alternative_candidates, check_payload, validate_original, provenance
from pitr.wiki.contracts import WikiJobRequest
from pitr.desk.sources import parse_document


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])


def test_default_identity_sec_configuration_and_redirect_scope(public_dns, monkeypatch):
    seen = []
    def serve(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': 'https://issuer.example.com/report'}) if request.url.host == 'www.sec.gov' else httpx.Response(200, content=b'original')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    with pytest.raises(FetchError) as error:fetch_public('https://www.sec.gov/report', client=client)
    assert error.value.kind == 'configuration_required' and not seen
    assert error.value.receipts[0]['phase'] == 'configuration'
    fetch_public('https://www.sec.gov/report', client=client, contact='PITR test@example.com')
    assert seen[0].headers['User-Agent'] == 'PITR test@example.com'
    assert seen[1].headers['User-Agent'].startswith('python-httpx/')
    assert 'test@example.com' not in str(seen[1].headers)


def test_connection_retry_is_bounded_and_attempts_preserved(public_dns, monkeypatch):
    monkeypatch.setattr('pitr.wiki.discovery.time.sleep', lambda _: None)
    calls = []
    def serve(request):
        calls.append(request)
        raise httpx.ConnectError('SSL handshake terminated')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    with pytest.raises(httpx.ConnectError) as error:fetch_public('https://example.com/report', client=client)
    assert len(calls) == 3
    assert len(error.value.receipts) == 3
    assert all(r['status'] is None and r['error_type'] == 'tls_error' and 'elapsed_seconds' in r for r in error.value.receipts)


def test_dns_failures_obey_the_same_retry_limit(monkeypatch):
    monkeypatch.setattr('pitr.wiki.discovery.time.sleep', lambda _: None)
    def fail_dns(*args, **kwargs):raise socket.gaierror('DNS unavailable')
    monkeypatch.setattr(socket, 'getaddrinfo', fail_dns)
    with pytest.raises(socket.gaierror) as error:
        fetch_public('https://example.com/report', client=httpx.Client(transport=httpx.MockTransport(lambda _:pytest.fail('no HTTP before DNS'))))
    assert len(error.value.receipts) == 3
    assert all(r['phase'] == 'connect' and r['status'] is None for r in error.value.receipts)


def test_job_downloads_use_existing_sec_contact_settings(lab, monkeypatch):
    import json
    settings=lab.desk.root/'private/settings.json'
    settings.parent.mkdir(parents=True,exist_ok=True)
    settings.write_text(json.dumps({'sec_user_agent':'PITR researcher@example.com'}))
    contacts=[]
    def fetch(url, timeout, contact):
        contacts.append(contact)
        return lab.fetch(url,timeout)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public', fetch)
    job=lab.jobs.create(WikiJobRequest(operation_id='configured-contact',company='TEST',years=1,quarters=1))
    lab.queue.run_one()
    assert contacts and set(contacts)=={'PITR researcher@example.com'}
    assert lab.jobs.get(job['id'])['proposal_id']


@pytest.mark.parametrize('status', [401, 403, 404])
def test_denial_is_not_retried(public_dns, status):
    calls = []
    def serve(request):calls.append(request);return httpx.Response(status)
    with pytest.raises(FetchError) as error:fetch_public('https://example.com/report', client=httpx.Client(transport=httpx.MockTransport(serve)))
    assert len(calls) == 1 and not error.value.retryable


def test_rate_limit_wait_or_defer_respects_remaining_budget(public_dns, monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr('pitr.wiki.discovery.time.sleep', lambda wait: sleeps.append(wait))
    def serve(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '3'}) if len(calls) == 1 else httpx.Response(200, content=b'original')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    assert fetch_public('https://example.com/report', client=client)[0] == b'original'
    assert sleeps == [3] and len(calls) == 2
    calls.clear();sleeps.clear()
    with pytest.raises(FetchError) as error:fetch_public('https://example.com/report', timeout=2, client=client)
    assert error.value.kind == 'rate_limited' and len(calls) == 1 and not sleeps
    date = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime('%a, %d %b %Y %H:%M:%S GMT')
    assert 28 <= retry_after(date) <= 30


def test_adapters_use_publisher_routes_and_validate_actual_body():
    c = {'url': 'https://ec.europa.eu/commission/presscorner/detail/en/ip_26_1178', 'title': 'Commission fines Temu for breaching the Digital Services Act', 'period': '2026Q2'}
    alt = alternative_candidates(c)[0]
    assert alt['url'].endswith('/en/ip_26_1178/IP_26_1178_EN.pdf')
    shell = parse_document(b'<html><title>Press corner</title><body><app-root></app-root></body></html>', 'text/html', c['url'], 'Temu')
    with pytest.raises(FetchError) as error:validate_original(shell, c, False)
    assert error.value.kind == 'body_unavailable'
    text = b'Commission fines Temu for breaching the Digital Services Act. Brussels, 28 May 2026. The company did not assess risks of illegal products on its platform.'
    doc = parse_document(text, 'text/plain', alt['url'], 'Temu')
    assert validate_original(doc, alt, False)[1]
    wrong = parse_document(b'A different publication about agricultural support and competition. '*5, 'text/plain', alt['url'], 'Temu')
    with pytest.raises(FetchError) as error:validate_original(wrong, alt, False)
    assert error.value.kind == 'title_conflict'
    pdd = {'url':'https://investor.pddholdings.com/static-files/id','period':'2026Q2'}
    news = alternative_candidates(pdd)[0]
    assert 'second-quarter-2026' in news['url']
    linked = alternative_candidates(news, b'<a href="/node/9631/pdf">PDF</a>')[0]
    assert linked['url'] == 'https://investor.pddholdings.com/node/9631/pdf'


def test_invalid_pdf_and_login_page_never_become_evidence():
    with pytest.raises(FetchError):check_payload(b'<html><title>Login</title></html>', 'application/pdf')
    with pytest.raises(FetchError) as error:check_payload(b'<html><h1>Access Denied</h1><p>' + b'x'*400 + b'</p></html>', 'text/html')
    assert error.value.kind == 'access_denied'


def test_chinese_html_encoding_preserves_original_quotes():
    text='国家统计局发布行业零售统计，期间与口径需按原文核对。'*8
    raw=('<html><head><meta charset="gb18030"></head><body><p>'+text+'</p></body></html>').encode('gb18030')
    doc=parse_document(raw,'text/html; charset=gb18030','https://example.com/report','INDUSTRY')
    assert doc.blocks[0].text==text
    validate_original(doc,{},False)


def test_publication_versions_and_reprints_do_not_add_independent_evidence():
    c = {'url':'https://investor.pddholdings.com/node/9631/pdf'}
    a = provenance(c, c['url'], b'%PDF', 'one', 'PDD', '2026Q2', 'Financial Results for the second quarter')
    u = 'https://investor.pddholdings.com/news-releases/q2'
    b = provenance({'url':u}, u, b'<p>Financial Results</p>', 'two', 'PDD', '2026Q2', 'Financial Results for the second quarter')
    assert a['origin_group'] == b['origin_group'] and a['content_group'] != b['content_group']
    original = 'https://news.example.com/original'
    a = provenance({'url':original}, original, b'article', 'one', 'PDD', '', 'Article')
    b = provenance({'url':'https://reprint.example.com/article','original_url':original}, 'https://reprint.example.com/article', b'<a href="https://news.example.com/original">Source</a>', 'two', 'PDD', '', 'Article')
    assert a['origin_group'] == b['origin_group'] and b['origin_relation'] == 'linked_original'
    self_link=provenance({'url':original}, original, ('<a href="'+original+'">Permalink</a>').encode(), 'one', 'PDD', '', 'Article')
    assert self_link['origin_relation'] == 'original'
    annual={'url':'https://investor.pddholdings.com/static-files/annual','original_url':'https://investor.pddholdings.com/financial-information/annual-reports'}
    a=provenance(annual,annual['url'],b'%PDF','one','PDD','2025FY','Year ended December 31, 2025')
    b=provenance(annual,annual['url'],b'%PDF','two','PDD','2024FY','Year ended December 31, 2024')
    assert a['origin_group'] != b['origin_group']


def test_gap_search_uses_failure_context_caps_new_candidates_and_resume_reuses_proposal(lab, monkeypatch):
    searches, fetches = [], []
    def discover(wiki, task, context, timeout, checkpoint):
        searches.append(context)
        if not context.get('supplemental'):return lab.discover(wiki, task, context, timeout, checkpoint)
        return {'search_log':['Public replacement search'], 'excluded':[], 'gaps':[], 'candidates':[
            {'url':f'https://replacement.example.com/article-{i}','title':'Public article','category':'media','subject':'TEST','publisher':'News','rationale':'gap','needs':['media']} for i in range(5)]}
    def fetch(url, timeout):
        fetches.append(url)
        if 'news.example' in url:raise FetchError('HTTP 401', kind='access_denied')
        return lab.fetch(url,timeout)
    monkeypatch.setattr('pitr.wiki.jobs.discover', discover)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public', fetch)
    first = lab.jobs.create(WikiJobRequest(operation_id='replace-first',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result = lab.jobs.get(first['id'])
    assert len(searches) == 2 and searches[1]['failures'][0]['error_type'] == 'access_denied'
    assert len([u for u in fetches if 'replacement.' in u]) == 2
    assert next(n for n in result['coverage'] if n['id']=='media')['status'] == 'materials_found'
    assert result['proposal_id']
    prior_sources = {m['url'] for m in result['materials'] if m.get('source_id')}
    fetches.clear()
    resumed = lab.jobs.create(WikiJobRequest(operation_id='replace-resume',company='TEST',years=1,quarters=1,resume_job_id=first['id']));lab.queue.run_one()
    after = lab.jobs.get(resumed['id'])
    assert not prior_sources.intersection(fetches)
    assert after['proposal_id'] == result['proposal_id']
    assert after['previous_failures'][0]['job_id'] == first['id']


def test_official_period_must_be_present_not_only_claimed_in_candidate(lab, monkeypatch):
    def empty_period(url, timeout):
        return (b'A long business discussion about competition, risk and investment without any filing period. '*4, 'text/plain', url, [])
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public', empty_period)
    first = lab.jobs.create(WikiJobRequest(operation_id='unverified-period',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result = lab.jobs.get(first['id'])
    assert all(n['status']=='gap' for n in result['coverage'] if n.get('period'))


def test_catalog_rejects_old_or_unknown_period_and_does_not_consume_budget(lab, monkeypatch):
    from pitr.wiki.contracts import CompanyRegistration
    lab.jobs.register(CompanyRegistration(operation_id='catalog-register',company='TEST',name='Test Issuer',official_domains=['issuer.example.com'],catalog_urls=['https://issuer.example.com/catalog']))
    calls=[]
    def fetch(url,timeout):
        calls.append(url)
        if url.endswith('/catalog'):
            return b'<a href="/old">2022Q1 Earnings Release</a><a href="/unknown">Annual Reports</a>', 'text/html', url, []
        return lab.fetch(url,timeout)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public', fetch)
    job=lab.jobs.create(WikiJobRequest(operation_id='catalog-filter',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result=lab.jobs.get(job['id'])
    assert not any(u.endswith(('/old','/unknown')) for u in calls)
    assert len(result['catalog_excluded'])==2


def test_host_network_failures_defer_following_urls(lab, monkeypatch):
    calls=[]
    def discovery(wiki,task,context,timeout,checkpoint):
        return {'search_log':[], 'gaps':[], 'excluded':[], 'candidates':[
            {'url':f'https://issuer.example.com/report-{i}','title':'Report','category':'official','subject':'TEST','publisher':'Test','needs':['business']} for i in range(4)]}
    def fetch(url,timeout):calls.append(url);raise httpx.ConnectError('SSL connection failed')
    monkeypatch.setattr('pitr.wiki.jobs.discover', discovery)
    monkeypatch.setattr('pitr.wiki.jobs.fetch_public', fetch)
    job=lab.jobs.create(WikiJobRequest(operation_id='host-defer',company='TEST',years=1,quarters=1));lab.queue.run_one()
    result=lab.jobs.get(job['id'])
    assert len(calls)==2
    assert [m['error_type'] for m in result['materials']]==['tls_error','tls_error','host_deferred','host_deferred']


def test_number_direction_stays_with_its_cell_and_inherits_headers():
    from pitr.wiki.validation import numeric_context
    table='| 指标 | 前季方向 | 本季金额 |\n| --- | --- | --- |\n| 收入 | 增加 | 100 |'
    start=table.index('100')
    assert '增加' not in numeric_context(table,start,start+3)
    growth=table.replace('本季金额','同比增长')
    start=growth.index('100')
    assert '同比增长' in numeric_context(growth,start,start+3)
    row=table.replace('收入 | 增加','收入同比增加 | 本季')
    start=row.index('100')
    assert '同比增加' in numeric_context(row,start,start+3)
    prose='收入为100，增长率尚需比较。'
    start=prose.index('100')
    assert '增长' not in numeric_context(prose,start,start+3)
    prose='收入同比增长100。'
    start=prose.index('100')
    assert '同比增长' in numeric_context(prose,start,start+3)
    table='| 判断 | 支持证据 |\n| --- | --- |\n| 净利润波动 | 投资收益为100，经营利润同比增加。 |'
    start=table.index('100')
    assert '同比增加' not in numeric_context(table,start,start+3)
    table='指标 | 同比增长\n--- | ---\n收入 | 100'
    start=table.index('100')
    assert '同比增长' in numeric_context(table,start,start+3)

    table='| 指标 | 本季 |\n| --- | --- |\n| 收入同比 | 增长；金额 [100](#evidence-a) 元 |'
    start=table.index('100')
    assert '同比' not in numeric_context(table,start,start+3)
    growth=table.replace('本季','同比增长')
    start=growth.index('100')
    assert '同比增长' in numeric_context(growth,start,start+3)
    ambiguous=table.replace('增长；金额','同比增长金额')
    start=ambiguous.index('100')
    assert '同比增长' in numeric_context(ambiguous,start,start+3)


def test_repaired_validation_reuses_frozen_draft_but_rechecks_current_state(lab, monkeypatch):
    import json
    original=lab.wiki._validate
    monkeypatch.setattr(lab.wiki,'_validate',lambda *a,**kw: (_ for _ in ()).throw(ValueError('fixture validation failure')))
    job=lab.jobs.create(WikiJobRequest(operation_id='failed-validation',company='TEST',years=1,quarters=1));lab.queue.run_one()
    before=lab.jobs.get(job['id'])
    assert before['execution_status']=='failed' and not before.get('proposal_id')
    monkeypatch.setattr(lab.wiki,'_validate',original)
    monkeypatch.setattr('pitr.wiki.worker.compile_sources',lambda *a,**kw:pytest.fail('frozen draft should be reused'))
    after=lab.jobs.create(WikiJobRequest(operation_id='revalidate-frozen',company='TEST',years=1,quarters=1,resume_job_id=job['id']));lab.queue.run_one()
    result=lab.jobs.get(after['id'])
    assert result['proposal_id'] and result['publication_status']=='waiting_review'
    with lab.desk.store.connect() as c:
        task=json.loads(c.execute('SELECT body FROM tasks WHERE id=?',(after['task_id'],)).fetchone()[0])
    assert task['result']['reused_compilation']

import json
import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pitr.adapters.api import create_app
from pitr.domain.common import utcnow
from pitr.application.service import Workstation
from pitr.domain.common import canonical, Conflict
from pitr.lab.news.acquire import feed_items, canonical_url, html_text
from pitr.lab.news.contracts import *
from pitr.lab.news.service import News
from pitr.lab.news.worker import NewsWorker
from pitr.lab.news.evaluation import evaluate


class Judge:
    ready = True
    last = {}
    process = None
    def __init__(self): self.calls = []; self.failure = False
    def encode(self, texts):
        # Explicit offline test double; never used by application code.
        return [[1, float('unrelated' in text.lower() and 'tariff' not in text.lower())*10] for text in texts]
    def predict(self, context, text):
        if self.failure: raise RuntimeError('offline fixture failure')
        self.calls.append((context, text))
        return {'result': {'answers': {k: {'noul': .9, 'confidence': .9} for k in ('relevance','materiality','research_impact')}},
                'state': context+'\n'+text, 'input_tokens': 100, 'state_budget': 768, 'model': 'offline-test', 'sdk': 'fixture', 'device': 'fixture'}
    def close(self): pass


@pytest.fixture
def news(tmp_path):
    station=Workstation(tmp_path,runtime=False)
    for name in ('PDD','BABA'):station.register_subject('register-'+name,identity=name,name=name)
    return News(station, Judge())


def profile(company='PDD', version='1'):
    return NewsProfile(id='profile-'+company+version, company=company, name=company, aliases=[company,'Temu'], identity_version=version,
        items=[{'ref': 'assumption-'+version, 'kind': 'assumption', 'title': 'Cross-border costs', 'text': 'Tariffs affect Temu fulfillment costs', 'href': '/companies/'+company+'/theses'}])


def article(news, n=0, url=None, text=None, original=True):
    text = text or ('PDD Temu tariffs affect cross-border fulfillment costs and merchant demand. '*4)+str(n)
    return news.add_article(NewsSource(id='fixture',name='Offline fixture',url='https://example.org/feed'),
        {'url':url or 'https://example.org/news/'+str(n),'title':'Tariff news '+str(n),'published_at':utcnow()[:10]+'T00:00:00+00:00'},
        text.encode() if original else b'', 'text/plain', text)


def score(news, a, p=None):
    p = p or profile()
    with news.store.connect(write=True) as db:
        db.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)', (p.id,p.company,canonical(p)))
    news.score_article(a,[p])
    return news.detail(a.event_id).selected


def test_rss_atom_dates_and_unsafe_xml():
    rss=b'<rss><channel><item><title>A &amp; B</title><link>https://example.org/a?utm_source=x</link><description>&lt;p&gt;Body&lt;/p&gt;</description><pubDate>Wed, 23 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'
    item=feed_items(rss,'https://example.org/feed')[0]
    assert item['url']=='https://example.org/a' and item['excerpt']=='Body'
    assert item['published_at']=='2026-09-23T12:00:00+00:00'
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Report</title><link href="/entry"/><updated>2026-09-23T10:00:00Z</updated></entry></feed>'
    assert feed_items(atom,'https://example.org/feed')[0]['url']=='https://example.org/entry'
    with pytest.raises(ValueError): feed_items(b'<!DOCTYPE rss><rss/>','https://example.org')
    with pytest.raises(ValueError): canonical_url('javascript:alert(1)')
    assert canonical_url('https://Example.org/a?b=2&a=1&utm_campaign=x#frag')=='https://example.org/a?a=1&b=2'


def test_article_body_excludes_recommendations_that_mention_companies():
    html='<html><body><div class="left_zw"><p>Local rail freight service expands.</p></div><div><h2>Recommended</h2><li><a>PDD reports new growth</a></li></div></body></html>'
    assert html_text(html)=='Local rail freight service expands.'
    generic='<html><body><main><p>A complete report with its own evidence.</p><ul><li><a>Temu news elsewhere</a></li></ul></main></body></html>'
    assert 'Temu' not in html_text(generic)


def test_dedup_versions_and_originals_do_not_publish(news):
    a, added=article(news)
    duplicate, added2=article(news,url='https://example.org/news/0?utm_source=test')
    revised, added3=article(news,1,url=a.url)
    assert added and not added2 and added3
    assert a.id==duplicate.id and revised.event_id==a.event_id and revised.id!=a.id
    assert len(news.detail(a.event_id).articles)==2
    assert news.station.store.list('source')==[]


def test_page_decoration_changes_deduplicate_but_publication_corrections_remain(news):
    source=NewsSource(id='publisher',name='Fixture',url='https://example.org/rss')
    item={'url':'https://example.org/story','title':'Story','published_at':None}
    text='PDD has reported new developments. '*4
    first,added=news.add_article(source,item,b'<html>first decoration</html>','text/html',text)
    again,added2=news.add_article(source,item,b'<html>different ad decoration</html>','text/html',text)
    corrected,added3=news.add_article(source,{**item,'published_at':utcnow()},b'<html>first decoration</html>','text/html',text)
    assert added and not added2 and added3
    assert again.id==first.id and corrected.id!=first.id and corrected.event_id==first.event_id


def test_immutable_score_profile_refresh_and_idempotent_rescore(news):
    a,_=article(news)
    first=score(news,a)
    assert first.priority>80 and first.queue=='selected' and first.confidence['relevance']==.9
    score(news,a)
    assert len(news.detail(a.event_id).scores)==1
    second=score(news,a,profile(version='2'))
    detail=news.detail(a.event_id,first.id)
    assert second.id!=first.id and detail.selected.id==first.id and detail.profile.id=='profile-PDD1'
    assert detail.latest_score_id==second.id
    assert len(news.events().items)==1


def test_missing_body_or_model_error_remain_unknown(news):
    a,_=article(news,original=False)
    result=score(news,a)
    assert result.priority is None and result.queue=='uncertain' and not news.judge.calls
    b,_=article(news,1);news.judge.failure=True
    result=score(news,b)
    assert result.priority is None and '本地推理失败' in result.reasons[-1]
    news.judge.failure=False
    assert score(news,b).priority is not None


def test_semantic_failure_can_recover_and_manual_rescore_appends_a_version(news,monkeypatch):
    a,_=article(news);encode=news.judge.encode
    monkeypatch.setattr(news.judge,'encode',lambda texts:(_ for _ in ()).throw(ValueError('temporary encoder failure')))
    pending=score(news,a)
    assert pending.priority is not None and pending.queue=='uncertain'
    monkeypatch.setattr(news.judge,'encode',encode)
    recovered=score(news,a)
    assert recovered.id!=pending.id and recovered.queue=='selected'
    news.score_article(a,[profile()],force=True)
    assert news.detail(a.event_id).selected.id!=recovered.id


def test_long_article_tail_and_indirect_context_remain_inspectable(news):
    a,_=article(news,text=('unrelated preamble. '*100)+' A new tariff alters cross-border logistics costs for merchants.')
    result=score(news,a)
    assert result.inputs and result.references[0]['ref']=='assumption-1'
    assert any('A new tariff' in item['passage']['text'] for item in result.inputs)
    assert all(i['passage']['end']>=i['passage']['start'] for i in result.inputs)


def test_queue_top_twenty_per_scope_and_date(news):
    # Avoid semantic clustering so this tests event-level ranking and pagination.
    news._cluster=lambda a:'event-'+a['id']
    for i in range(25):
        a,_=article(news,i);score(news,a,profile('PDD' if i<23 else 'BABA'))
    assert news.events().total==20
    assert news.events(queue='all').total==25
    assert news.events(company='BABA').total==2
    assert news.events(queue='all',offset=20,limit=2).items[0].id!=news.events(queue='all',limit=2).items[0].id
    assert news.events(date='2000-01-01').total==0


def test_feedback_draft_identity_and_source_transfer(news):
    a,_=article(news);s=score(news,a)
    req=NewsFeedbackInput(operation_id='feedback-1',score_id=s.id,verdict='useful')
    assert news.feedback(a.event_id,req)==news.feedback(a.event_id,req)
    assert len(news.detail(a.event_id).feedback)==1
    draft_req=NewsDraftInput(operation_id='draft-op-1',score_id=s.id)
    draft=news.draft(a.event_id,draft_req)
    assert draft==news.draft(a.event_id,draft_req)
    assert news.get_draft(draft['id']).profile_id==s.profile_id
    assert len(news.station.store.list('source'))==1
    doc=news.station.store.get(draft['materials'][0]['source'],'source')
    assert doc.url==a.url and doc.source_role!='official'
    with pytest.raises(ValueError):news.draft(a.event_id,NewsDraftInput(operation_id='bad-draft',score_id=s.id,article_ids=['missing']))
    with pytest.raises(KeyError):news.detail(a.event_id,'unrelated-score')


def test_settings_runs_lease_and_recovery(news, monkeypatch):
    settings=NewsSettings(enabled=True,sources=[])
    req=NewsSettingsInput(operation_id='settings-1',settings=settings)
    news.configure(req)
    assert news.settings().enabled
    with pytest.raises(Conflict):news.configure(req.model_copy(update={'settings':NewsSettings()}))
    a=news.enqueue(NewsRunInput(operation_id='run-once-1',kind='rescore'))
    b=news.enqueue(NewsRunInput(operation_id='run-once-2',kind='rescore'))
    assert a['id']==b['id']
    with news.store.connect(write=True) as db:db.execute("UPDATE runs SET status='running',owner='dead',lease=?",(time.time()-1,))
    monkeypatch.setattr(news,'rescore',lambda *args,**kwargs:{'scored':3})
    worker=NewsWorker(news)
    assert worker.run_one() and not worker.run_one()
    run=news.status().runs[0]
    assert run['status']=='completed' and run['recovered'] and run['progress']['scored']==3


def test_collect_logs_partial_failure_and_retries(news,monkeypatch):
    p=profile()
    with news.store.connect(write=True) as db:db.execute('INSERT INTO profiles VALUES(?,?,?)',(p.id,p.company,canonical(p)))
    monkeypatch.setattr(news,'freeze_profiles',lambda:[p])
    news.configure(NewsSettingsInput(operation_id='settings-feed',settings=NewsSettings(sources=[NewsSource(id='test',name='Offline',url='https://example.org/rss')])))
    body=('PDD Temu has new tariff exposure and materially higher fulfillment costs. '*4).encode()
    feed=b'<rss><channel><item><title>Tariffs</title><link>https://example.org/news</link></item><item><title>Missing</title><link>https://example.org/fail</link></item></channel></rss>'
    def fetch(url,**kw):
        if url.endswith('fail'):raise ValueError('offline missing')
        return (feed if url.endswith('rss') else body),'text/plain',url,{}
    result=news.collect(fetch=fetch)
    assert result['acquired']==2 and result['errors']==1
    assert news.status().sources[0]['errors']
    assert news.collect(fetch=fetch)['acquired']==0


def test_api_contracts_and_human_boundary(tmp_path):
    app=create_app(tmp_path,workers=False);app.state.news.judge=Judge()
    news=app.state.news;news.station.register_subject('register-pdd',identity='PDD',name='PDD');a,_=article(news);s=score(news,a)
    with TestClient(app) as client:
        assert client.get('/api/v1/lab/news/status').status_code==200
        data=client.get('/api/v1/lab/news/events').json()
        assert data['items'][0]['score']['id']==s.id
        assert client.get('/api/v1/lab/news/events/'+a.event_id+'?score_id=bad').status_code==404
        assert client.get('/api/v1/lab/news/articles/'+a.id+'/original').content
        assert client.post('/api/v1/lab/news/runs',json={'operation_id':'api-run-test'},headers={'x-pitr-actor':'agent'}).status_code==403
        assert client.post('/api/v1/lab/news/runs',json={'operation_id':'api-run-test'}).status_code==200
        assert client.post('/api/v1/lab/news/events/'+a.event_id+'/research-draft',json={'operation_id':'api-draft-test','score_id':s.id}).status_code==200


def test_effectiveness_requires_human_labels_and_sample_size(news):
    a,_=article(news);s=score(news,a)
    with pytest.raises(ValueError):evaluate(news,[{'score_id':s.id}])
    label={'event_id':a.event_id,'company':s.company,'score_id':s.id,'useful':True,'important':True,'annotator':'offline test fixture'}
    report=evaluate(news,[label])
    assert report['status']=='unvalidated' and report['precision_at_20']==1 and report['important_recall']==1
    with pytest.raises(ValueError):evaluate(news,[label,label])


def test_clustering_retains_conflicting_reports_and_separates_known_entities(news):
    a,_=article(news,text='PDD reports rising costs and weaker demand. '*5)
    b,_=article(news,1,text='PDD denies reports of rising costs; demand remains strong. '*5)
    c,_=article(news,2,text='BABA reports rising costs and weaker demand. '*5)
    assert a.event_id==b.event_id and c.event_id!=a.event_id
    assert {x.text for x in news.detail(a.event_id).articles}=={a.text,b.text}


def test_shared_alias_requires_identity_confirmation(news):
    a,_=article(news,text='Temu reports new tariff pressure and costs. '*6)
    news.score_article(a,[profile('PDD'),profile('BABA')])
    scores=news.detail(a.event_id).scores
    assert len(scores)==2 and all(s.queue=='uncertain' for s in scores)
    assert all(any('同名' in reason for reason in s.reasons) for s in scores)


def test_rescoring_an_old_report_does_not_hide_the_follow_up(news):
    a,_=article(news);old=score(news,a)
    b,_=article(news,1,url=a.url);current=score(news,b)
    score(news,a,profile(version='2'))
    detail=news.detail(a.event_id,old.id)
    assert detail.event.score.id==current.id and detail.latest_score_id==current.id
    assert detail.selected.id==old.id


def test_revised_extraction_cannot_keep_old_company_matches_visible(news):
    a,_=article(news);old=score(news,a)
    b,_=article(news,1,url=a.url,text='A local community event, with no company research context. '*5)
    news.score_article(b,[])
    assert news.events(company='PDD',queue='all').total==0
    detail=news.detail(a.event_id,old.id)
    assert detail.selected.id==old.id and detail.latest_score_id!=old.id


def test_download_failure_recovers_after_feed_rotation(news,monkeypatch):
    monkeypatch.setattr(news,'freeze_profiles',lambda:[])
    news.configure(NewsSettingsInput(operation_id='rotating-feed',settings=NewsSettings(sources=[NewsSource(id='rotate',name='Offline',url='https://example.org/rss')])))
    feed=b'<rss><channel><item><title>Report</title><link>https://example.org/report</link><description>Summary only</description></item></channel></rss>'
    def offline(url,**kw):
        if not url.endswith('rss'):raise ValueError('Temporary outage')
        return feed,'text/xml',url,{}
    assert news.collect(fetch=offline)['errors']==1
    before=news.events(queue='all').items[0]
    def recovered(url,**kw):
        raw=b'<rss><channel/></rss>' if url.endswith('rss') else b'Recovered full article about global tariff changes. '*5
        return raw,'text/plain',url,{}
    assert news.collect(fetch=recovered)['acquired']==1
    after=news.detail(before.id)
    assert len(after.articles)==2 and any(a.original_file for a in after.articles)
    assert not news.status().sources[0]['errors']


def test_draft_retry_and_conflict_do_not_reimport_material(news,monkeypatch):
    a,_=article(news);s=score(news,a)
    original=news.station.import_source;calls=[]
    def ingest(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(news.station,'import_source',ingest)
    req=NewsDraftInput(operation_id='draft-import-once',score_id=s.id)
    news.draft(a.event_id,req);news.draft(a.event_id,req)
    with pytest.raises(Conflict):news.draft(a.event_id,req.model_copy(update={'article_ids':[a.id]}))
    assert len(calls)==1


def test_news_handoff_keeps_validation_and_server_provenance(news):
    from pitr.domain.contracts import CreateCase,Scope
    from pitr.domain.common import Forbidden
    a,_=article(news);s=score(news,a)
    draft=news.draft(a.event_id,NewsDraftInput(operation_id='handoff-test-draft',score_id=s.id))
    req=CreateCase(operation_id='handoff-submit-test',question=draft['question'],scope=Scope(subjects=['PDD']),
                   news_draft_id=draft['id'],sources=[m['source'] for m in draft['materials']])
    saved=news.station.create_case(req)
    assert saved['input']['context']['news_origin']['score_id']==s.id
    assert saved['input']['context']['news_origin']['experimental'] is True
    assert news.station.create_case(req)['id']==saved['id']
    with pytest.raises(Forbidden):
        news.station.create_case(req.model_copy(update={'operation_id':'old-news-cutoff','scope':Scope(subjects=['PDD'],mode='historical',as_of='2000-01-01T00:00:00+00:00',allow_public_search=False)}))
    assert not news.station.create_case(req.model_copy(update={'operation_id':'remove-news-material','sources':[]}))['input']['sources']
    assert not news.station.knowledge()

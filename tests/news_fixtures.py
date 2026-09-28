"""Explicit offline layout fixtures. No model or public network is used."""
from pitr.domain.common import utcnow
from pitr.domain.common import canonical
from pitr.lab.news.contracts import NewsSource, NewsProfile, NewsScore


def seed_news(news):
    class DisplayJudge:
        ready=True
        process=None
        last={'device':'离线界面夹具','model':'fixture-only'}
        def close(self):pass
        def encode(self,texts):return [[1,0] for text in texts]
        def predict(self,*args):raise ValueError('Offline UI fixture never runs inference')
    news.judge=DisplayJudge()
    source=NewsSource(id='offline-news',name='离线界面测试资料',url='https://example.org/offline-feed')
    now=utcnow()
    article,_=news.add_article(source,{'url':'https://example.org/offline-tariffs','title':'离线示例：跨境履约规则调整，需要重新核对成本假设','published_at':now},
        ('This is an offline UI fixture, not a real news report.\n\nTemu merchants face a change in parcel fulfillment rules. '+
         'The research question is whether higher delivery costs alter the cross-border business margin assumption.').encode(),
        'text/plain','Temu merchants face a change in parcel fulfillment rules. Higher delivery costs may affect the cross-border business margin assumption. Offline UI fixture only.')
    for company,priority in [('PDD',84),('BABA',68)]:
        profile=NewsProfile(id='offline-profile-'+company,company=company,name=company,aliases=[company,'Temu'],identity_version='offline-fixture',
            items=[{'kind':'assumption','ref':'offline-cost-hypothesis','title':'跨境履约成本与利润率假设','text':'需要核对跨境物流成本变化是否影响经营利润率。','href':'/companies/'+company+'/theses'}])
        score=NewsScore(id='offline-score-'+company,event_id=article.event_id,article_id=article.id,company=company,profile_id=profile.id,created_at=now,
            signature='offline-'+company,priority=priority,dimensions={'relevance':.92,'materiality':.85,'research_impact':.8,'novelty':.9,'freshness':.99},
            confidence={'relevance':.92,'materiality':.85,'research_impact':.8},queue='selected',references=profile.items,
            inputs=[{'passage':{'text':article.text,'start':0,'end':len(article.text)}}],raw=[{'fixture':True}],model={'model':'offline-ui-fixture','device':'fixture'})
        with news.store.connect(write=True) as db:
            db.execute('INSERT INTO profiles VALUES(?,?,?)',(profile.id,company,canonical(profile)))
            db.execute('INSERT INTO scores VALUES(?,?,?,?,?,?)',(score.id,article.event_id,company,now,score.signature,canonical(score)))
    return article

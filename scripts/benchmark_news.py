"""Capacity replay with synthetic news and REAL local inference; not a quality evaluation."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pitr.application.service import Workstation
from pitr.domain.common import utcnow
from pitr.domain.common import canonical
from pitr.lab.news.service import News
from pitr.lab.news.contracts import NewsProfile, NewsSource, NewsSettings, NewsSettingsInput


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--count',type=int,default=1000)
    parser.add_argument('--output',default='.pitr/news-benchmark')
    parser.add_argument('--profiles-from',help='Optional existing workstation whose current company contexts are frozen for this local replay')
    args=parser.parse_args()
    root=Path(args.output).resolve()
    if (root/'lab/news/news.sqlite').exists():raise ValueError('Use a fresh output directory to avoid reusing a previous replay')
    news=News(Workstation(root));stop=threading.Event();read_times=[];peak=[0];research_checks=[]
    profile=NewsProfile(id='benchmark-profile',company='PDD',name='PDD Holdings',aliases=['PDD','Temu','拼多多'],identity_version='capacity-fixture',
        items=[{'ref':'benchmark-assumption','kind':'assumption','title':'Cross-border trade and fulfillment',
                'text':'Temu cross-border trade policy, tariffs, demand and fulfillment costs affect operating margins. 跨境贸易政策与履约成本影响经营利润率。',
                'href':'/companies/PDD/theses'}])
    current_profiles=News(Workstation(args.profiles_from)).freeze_profiles() if args.profiles_from else [profile]
    def freeze():
        with news.store.connect(write=True) as db:
            for item in current_profiles:db.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)',(item.id,item.company,canonical(item)))
        return current_profiles
    news.freeze_profiles=freeze
    stamp=utcnow()
    feed=('<rss><channel>'+''.join(f'<item><title>Capacity fixture {i}: Temu trade policy</title><link>https://capacity.example/{i}</link><pubDate>{stamp}</pubDate></item>' for i in range(args.count))+'</channel></rss>').encode()
    def fetch(url,**kwargs):
        if url.endswith('/feed'):return feed,'application/rss+xml',url,{}
        number=int(url.rsplit('/',1)[-1])
        text=(f'Synthetic capacity replay item {number}. Temu merchants reported higher fulfillment costs after new tariff rules. The change affects cross-border parcel deliveries and may reduce demand. This is a capacity fixture, not a real news report.' if number%2 else
              f'容量回放样本 {number}。Temu 跨境商家报告物流成本随着新关税规定上升，包裹交付和消费者需求可能受到影响，需要核对履约成本假设。本条仅用于容量测试，不是真实新闻报道。')
        return text.encode(),'text/plain',url,{}
    news.configure(NewsSettingsInput(operation_id='capacity-settings',settings=NewsSettings(daily_limit=args.count,
        sources=[NewsSource(id='capacity',name='Synthetic capacity fixture',url='https://capacity.example/feed')])))
    from pitr.domain.contracts import CreateCase,Scope
    news.station.register_subject('benchmark-subject',identity='PDD',name='PDD Holdings')
    def monitor():
        while not stop.wait(1):
            ids=[str(os.getpid())]
            if news.judge.process:ids.append(str(news.judge.process.pid))
            raw=subprocess.check_output(['ps','-o','rss=','-p',','.join(ids)],text=True)
            peak[0]=max(peak[0],sum(int(x) for x in raw.split())*1024)
            started=time.monotonic();news.station.store.list('subject');read_times.append(time.monotonic()-started)
            if not research_checks:
                started=time.monotonic()
                saved=news.station.create_case(CreateCase(operation_id='capacity-research',question='Offline capacity fixture: inspect PDD costs',scope=Scope(subjects=['PDD'])))
                research_checks.append({'seconds':time.monotonic()-started,'input_revision':saved['input']['revision'],
                    'interpretation':'explicit offline intake fixture; no external Agent call'})
    thread=threading.Thread(target=monitor,daemon=True);thread.start();started=time.monotonic()
    previous=[0]
    def progress(value):
        count=value.get('scored',0)
        if count>=previous[0]+50:previous[0]=count;print(json.dumps({'scored':count,'elapsed_seconds':round(time.monotonic()-started,1)}),flush=True)
    try:
        result=news.collect(progress=progress,fetch=fetch)
        with news.store.connect() as db:
            pending=db.execute("SELECT count(*) FROM scores WHERE json_extract(body,'$.priority') IS NULL").fetchone()[0]
            unprocessed=db.execute("SELECT count(*) FROM articles a WHERE NOT EXISTS(SELECT 1 FROM scores s WHERE json_extract(s.body,'$.article_id')=a.id)").fetchone()[0]
        elapsed=time.monotonic()-started
        ordered=sorted(read_times)
        report={'kind':'synthetic-capacity-real-inference','input_articles':args.count,**result,'pending_review_pairs':pending,'unprocessed_articles':unprocessed,
                'seconds':elapsed,'articles_per_hour':args.count/elapsed*3600,'peak_process_rss_bytes':peak[0],
                'concurrent_company_read_p95_seconds':ordered[min(len(ordered)-1,int(len(ordered)*.95))] if ordered else None,
                'concurrent_research_intake':research_checks,'company_profiles':len(current_profiles),
                'context_items':sum(len(p.items) for p in current_profiles),
                'runtime':news.judge.last,'quality_labels':0,
                'note':'Synthetic replay, real MPS/CPU inference. Network latency excluded. Human usefulness is not evaluated.'}
        (root/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
        print(json.dumps(report,indent=2,ensure_ascii=False),flush=True)
    finally:
        stop.set();thread.join(5);news.judge.close()


if __name__=='__main__':main()

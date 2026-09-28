"""Source watching records changes; research continuation remains an explicit command."""
import json
import threading
import time

from pitr.domain.common import Conflict, canonical, uid, utcnow


def save_subscription(station,request):
    from pitr.adapters.public_fetch import public_url
    public_url(request.url,resolve=False)
    def save(db):
        station.store.get(request.subject,'subject',db=db)
        sid=request.id or uid('subscription')
        row=db.execute('SELECT body FROM subscriptions WHERE id=?',(sid,)).fetchone()
        prior=json.loads(row[0]) if row else None
        if (prior['revision'] if prior else 0)!=request.expected_revision:raise Conflict('订阅版本已变化')
        body={**request.model_dump(exclude={'operation_id','expected_revision'}),'id':sid,
              'revision':request.expected_revision+1,'next_check':0,'last_result':prior.get('last_result') if prior else None}
        db.execute('INSERT INTO subscriptions VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(sid,canonical(body)))
        return body
    return station.store.once(request.operation_id,{'command':'subscription.save','request':request},save)


def refresh(station,subscription_id,operation_id):
    with station.store.connect() as db:
        row=db.execute('SELECT body FROM subscriptions WHERE id=?',(subscription_id,)).fetchone()
        if not row:raise KeyError('订阅不存在')
        body=json.loads(row[0])
    source=station.fetch_source(body['url'],subjects=[body['subject']],operation_id=operation_id)
    with station.store.connect(write=True) as db:
        current=json.loads(db.execute('SELECT body FROM subscriptions WHERE id=?',(subscription_id,)).fetchone()[0])
        if current['revision']!=body['revision']:raise Conflict('订阅已经变化，取得的原件已保存')
        changed=bool(body.get('last_result') and body['last_result']!=source.ref.model_dump())
        current.update(next_check=time.time()+body['interval_hours']*3600,last_result=source.ref.model_dump(),checked_at=utcnow(),error='')
        db.execute('UPDATE subscriptions SET body=? WHERE id=?',(canonical(current),subscription_id))
        station.store.event(db,'','source.watch',{'subscription':subscription_id,'source':source.ref,'changed':changed})
        return current


class WatchWorker:
    def __init__(self,station):
        self.station=station;self.stopping=threading.Event()
        self.thread=threading.Thread(target=self.loop,daemon=True,name='source-watch');self.thread.start()

    def loop(self):
        while not self.stopping.wait(5):
            with self.station.store.connect() as db:items=[json.loads(r[0]) for r in db.execute('SELECT body FROM subscriptions')]
            for item in items:
                if self.stopping.is_set():return
                if not item['enabled'] or item['next_check']>time.time():continue
                try:refresh(self.station,item['id'],'watch:'+item['id']+':'+str(item['revision'])+':'+str(int(item['next_check'])))
                except Exception as error:
                    with self.station.store.connect(write=True) as db:
                        current=json.loads(db.execute('SELECT body FROM subscriptions WHERE id=?',(item['id'],)).fetchone()[0])
                        if current['revision']==item['revision']:
                            current.update(error=str(error)[:1500],next_check=time.time()+300)
                            db.execute('UPDATE subscriptions SET body=? WHERE id=?',(canonical(current),item['id']))

    def close(self):
        self.stopping.set();self.thread.join(2)

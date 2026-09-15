import time
from types import SimpleNamespace
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from test_desk import desk
from pitr.desk.contracts import TaskInput,utcnow
from pitr.desk.storage import canonical
from pitr.desk.tasks import Queue
from pitr.desk.slack import Slack
from pitr.integrations.slack import InboundEvent,ReplyTarget
from pitr.integrations.slack.runtime import WorkflowContext
from pitr.desk.integrations import Monitor
from pitr.desk.tools import SnapshotTools
from pitr.desk.api import create_app


def test_queue_duplicate_cancel_and_expired_lease(desk):
 q=Queue(desk);req=TaskInput(operation_id='duplicate-task',workflow='disclosures',company='PDD')
 a=q.enqueue(req);assert q.enqueue(req)['id']==a['id'];first=q.claim();assert first['attempts']==1
 with desk.store.connect(write=True) as db:db.execute('UPDATE tasks SET lease_until=? WHERE id=?',(time.time()-10,a['id']))
 q2=Queue(desk);second=q2.claim();assert second['id']==a['id'] and second['attempts']==2
 with pytest.raises(RuntimeError):q.checkpoint(first,{'stage':'late-completion'})
 q2.cancel(a['id'])
 with pytest.raises(RuntimeError):q2.checkpoint(second,{'stage':'after-cancellation'})


def test_monitor_coalesces_sleep_and_no_duplicate_heavy_task(desk):
 m=Monitor(desk,Queue(desk))
 assert not m.tick(1000)
 assert m.tick(10000)
 assert not m.tick(10001)
 with desk.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1


def test_slack_allowlist_dedup_and_restart(desk):
 cfg=lambda:{'slack_team_id':'TEAM','slack_user_id':'OWNER'}
 s=Slack(desk,Queue(desk),cfg)
 target=ReplyTarget(team_id='TEAM',user_id='OWNER',channel_id='DM',thread_ts='100.1')
 event=InboundEvent(id='event',kind='message',target=target,text='进度')
 assert not s.receive(event.model_copy(update={'target':target.model_copy(update={'user_id':'STRANGER'})}))
 assert s.receive(event)
 assert not s.receive(event)
 Slack(desk,Queue(desk),cfg).pump()
 with s.journal.connect() as db:assert db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1
 s.pump()
 with s.journal.connect() as db:assert db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1


def test_cross_origin_writes_and_secret_output(desk):
 app=TestClient(create_app(desk.root,worker=False))
 r=app.post('/api/desk/settings',json={'slack_bot_token':'xoxb-private-token'},headers={'Origin':'https://outside.test'})
 assert r.status_code==403
 assert app.post('/api/desk/settings',json={'slack_bot_token':'xoxb-private-token'}).status_code==200
 assert 'private-token' not in app.get('/api/desk/settings').text
 assert (desk.root/'private/settings.json').stat().st_mode & 0o777==0o600


def test_only_one_heavy_task_across_worker_processes(desk):
 a,b=Queue(desk),Queue(desk)
 a.enqueue(TaskInput(operation_id='first-heavy',workflow='disclosures'))
 a.enqueue(TaskInput(operation_id='second-heavy',workflow='disclosures'))
 assert a.claim()
 assert b.claim() is None

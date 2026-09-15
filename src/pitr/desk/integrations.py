"""Provider cache, conservative EOD audit and persistent monitoring schedule."""
import threading
import time
from .contracts import TaskInput


class Monitor:
 def __init__(self,desk,queue):
  self.desk=desk;self.queue=queue;self.stop_event=threading.Event()
  with desk.store.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS schedule(name TEXT PRIMARY KEY,next_due REAL,last_status TEXT)')
 def tick(self,clock=None):
  now=time.time() if clock is None else clock
  with self.desk.store.connect(write=True) as db:
   row=db.execute("SELECT * FROM schedule WHERE name='official_sources'").fetchone()
   if not row:db.execute('INSERT INTO schedule VALUES(?,?,?)',('official_sources',now+900,'scheduled'));return False
   if row['next_due']>now:return False
   running=db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running') AND body LIKE '%disclosures%'").fetchone()[0]
   if running:return False
   # Claim this interval once. A wake-up produces one catch-up, not missed-interval spam.
   db.execute('UPDATE schedule SET next_due=?,last_status=? WHERE name=?',(now+900,'queued','official_sources'))
  self.queue.enqueue(TaskInput(operation_id='monitor:'+str(int(now//900)),workflow='disclosures',company='PDD',budget_seconds=600))
  return True
 def start(self):
  def loop():
   while not self.stop_event.wait(15):
    try:self.tick()
    except Exception:
     with self.desk.store.connect(write=True) as db:db.execute("UPDATE schedule SET last_status='failed' WHERE name='official_sources'")
  threading.Thread(target=loop,daemon=True,name='desk-monitor').start()
 def stop(self):self.stop_event.set()

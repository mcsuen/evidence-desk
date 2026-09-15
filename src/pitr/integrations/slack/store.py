"""Private SQLite journal. No workflow objects or credentials are stored here."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import uuid


def encode(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stable(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Journal:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.files = self.root / 'attachments'
        self.files.mkdir(exist_ok=True, mode=0o700)
        self.path = self.root / 'slack.sqlite'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS inbox(
                    id TEXT PRIMARY KEY, adapter TEXT NOT NULL, event TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', owner TEXT, lease REAL DEFAULT 0,
                    attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0, error TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox(
                    id TEXT PRIMARY KEY, event_id TEXT, target TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', owner TEXT, lease REAL DEFAULT 0,
                    attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0, error TEXT,
                    message_ts TEXT, created REAL NOT NULL, sent_at REAL);
                CREATE TABLE IF NOT EXISTS bindings(
                    adapter TEXT, task_id TEXT, event_id TEXT, PRIMARY KEY(adapter,task_id));
                CREATE TABLE IF NOT EXISTS prepared(
                    event_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions(
                    id TEXT PRIMARY KEY, adapter TEXT, event_id TEXT, action_id TEXT,
                    target TEXT, metadata TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS attachments(
                    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, subject TEXT, detail TEXT, created REAL);
                CREATE INDEX IF NOT EXISTS inbox_pending ON inbox(status,next_at,created);
                CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(status,next_at,created);
                PRAGMA user_version=1;
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self, write=False, timeout=2):
        db = sqlite3.connect(self.path, timeout=timeout)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def state(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def set_state(self, key, value):
        with self.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', (key, encode(value)))

    def audit(self, kind, subject='', detail=None):
        with self.connect(write=True) as db:
            db.execute('INSERT INTO audit(kind,subject,detail,created) VALUES(?,?,?,?)',
                       (kind, subject, encode(detail or {}), time.time()))

    def claim(self, table, *, include_actions=False):
        assert table in ('inbox', 'outbox')
        now = time.time()
        with self.connect(write=True) as db:
            if table == 'outbox':
                # A crashed network send may have succeeded. Never blindly replay it.
                db.execute("UPDATE outbox SET status='delivery_unknown',error='interrupted_send' WHERE status='sending' AND lease<?", (now,))
                condition = "status='pending' AND next_at<=?"
            else:
                condition = "((status='pending' AND next_at<=?) OR (status='processing' AND lease<?))"
                if not include_actions:
                    condition += " AND json_extract(event,'$.kind')!='action'"
            params = (now,) if table == 'outbox' else (now, now)
            row = db.execute(f'SELECT * FROM {table} WHERE {condition} ORDER BY created LIMIT 1', params).fetchone()
            if not row:
                return None
            owner = uuid.uuid4().hex
            status = 'sending' if table == 'outbox' else 'processing'
            increment = 1 if table == 'inbox' else 0
            db.execute(f'UPDATE {table} SET status=?,owner=?,lease=?,attempts=attempts+? WHERE id=?',
                       (status, owner, now + 120, increment, row['id']))
            return {**dict(row), 'owner': owner, 'attempts': row['attempts'] + increment}

    def finish(self, table, row, status, *, error=None, delay=0, message_ts=None):
        assert table in ('inbox', 'outbox')
        with self.connect(write=True) as db:
            db.execute(f'UPDATE {table} SET status=?,error=?,next_at=?,lease=0 WHERE id=? AND owner=?',
                       (status, error, time.time() + delay, row['id'], row['owner']))
            if table == 'outbox' and status == 'sent':
                db.execute('UPDATE outbox SET message_ts=?,sent_at=? WHERE id=? AND owner=?',
                           (message_ts, time.time(), row['id'], row['owner']))

    def deliveries(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,event_id,target,payload,status,attempts,error,message_ts,created,sent_at FROM outbox ORDER BY created DESC LIMIT 100').fetchall()
        return [{**{k: row[k] for k in ('id', 'event_id', 'status', 'attempts', 'error', 'message_ts', 'created', 'sent_at')},
                 'channel_id': json.loads(row['target'])['channel_id'], 'kind': json.loads(row['payload'])['kind']}
                for row in rows]

    def retry(self, key):
        with self.connect(write=True) as db:
            row = db.execute('SELECT status FROM outbox WHERE id=?', (key,)).fetchone()
            if not row:
                raise KeyError('投递记录不存在')
            if row['status'] not in ('failed', 'delivery_unknown'):
                raise ValueError('只有失败或结果不确定的投递可以重发')
            db.execute("UPDATE outbox SET status='pending',attempts=0,next_at=0,error=NULL WHERE id=?", (key,))
        self.audit('delivery.manual_retry', key)

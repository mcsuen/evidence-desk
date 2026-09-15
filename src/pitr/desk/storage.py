"""Small append-only object store; canonical commands are transactionally idempotent."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
from .contracts import utcnow


def canonical(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=lambda v: v.model_dump(mode='json'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex[:20]


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / 'originals'
        self.files.mkdir(exist_ok=True)
        self.snapshots = self.root / 'snapshots'
        self.snapshots.mkdir(exist_ok=True)
        self.path = self.root / 'desk.sqlite'
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, company TEXT, available_at TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, company TEXT, source_id TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, company TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS objects(id TEXT, version INTEGER, kind TEXT, company TEXT, title TEXT, body TEXT, citations TEXT, created_at TEXT, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, digest TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS checks(observation_id TEXT, snapshot TEXT, note TEXT, created_at TEXT, PRIMARY KEY(observation_id,snapshot));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, kind TEXT, body TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, status TEXT, owner TEXT, lease_until REAL, attempts INTEGER DEFAULT 0, body TEXT);
            CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, kind TEXT, company TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS source_state(id TEXT PRIMARY KEY, withdrawn_at TEXT);
            CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, body TEXT);
            ''')

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=30)
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

    def cached(self, db, key, payload):
        row = db.execute('SELECT * FROM commands WHERE id=?', (key,)).fetchone()
        if row:
            if row['digest'] != digest(payload):
                raise Conflict('相同操作标识不能用于不同请求')
            return json.loads(row['result'])

    def remember(self, db, key, payload, result):
        db.execute('INSERT INTO commands VALUES(?,?,?)', (key, digest(payload), canonical(result)))

    def event(self, db, company, kind, body):
        db.execute('INSERT INTO events(company,kind,body,created_at) VALUES(?,?,?,?)', (company, kind, canonical(body), utcnow()))

"""Lab-only originals and durable work. No Wiki or graph writes on collection."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from pitr.domain.common import canonical, digest, Conflict


class NewsStore:
    def __init__(self, root):
        self.root = Path(root) / 'lab' / 'news'
        self.originals = self.root / 'originals'
        self.originals.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'news.sqlite'
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, title TEXT, first_seen TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, event_id TEXT NOT NULL, url TEXT, digest TEXT, observed_at TEXT, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS article_event ON articles(event_id);
            CREATE INDEX IF NOT EXISTS article_digest ON articles(digest);
            CREATE INDEX IF NOT EXISTS article_content ON articles(json_extract(body,'$.content_digest'));
            CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, company TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scores(id TEXT PRIMARY KEY, event_id TEXT, company TEXT, created_at TEXT, signature TEXT, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS score_event ON scores(event_id, company, created_at);
            CREATE INDEX IF NOT EXISTS score_signature ON scores(signature);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, status TEXT, lease REAL, owner TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, event_id TEXT, score_id TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, digest TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_log(id INTEGER PRIMARY KEY, source_id TEXT, at TEXT, body TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)', (key, canonical(value)))

    def once(self, request, fn):
        payload = request.model_dump()
        with self.connect(write=True) as db:
            row = db.execute('SELECT * FROM commands WHERE id=?', (request.operation_id,)).fetchone()
            if row:
                if row['digest'] != digest(payload): raise Conflict('该操作标识已经用于其他请求')
                return json.loads(row['body'])
            result = fn(db)
            db.execute('INSERT INTO commands VALUES(?,?,?)', (request.operation_id, digest(payload), canonical(result)))
            return result

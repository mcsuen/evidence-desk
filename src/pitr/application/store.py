"""Immutable revisions, transactional heads and mutable execution state."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import copy

from pitr.adapters.files import atomic_file
from pitr.domain.common import Conflict, canonical, digest, utcnow
from pitr.domain.contracts import REVISION_MODELS, Ref

SCHEMA = '''
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revisions(id TEXT,revision INTEGER,kind TEXT NOT NULL,body TEXT NOT NULL,
 digest TEXT NOT NULL,PRIMARY KEY(id,revision));
CREATE INDEX IF NOT EXISTS revision_kind ON revisions(kind,id,revision);
CREATE TRIGGER IF NOT EXISTS immutable_revisions BEFORE UPDATE ON revisions
 BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
CREATE TRIGGER IF NOT EXISTS retain_revisions BEFORE DELETE ON revisions
 BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
CREATE TABLE IF NOT EXISTS heads(id TEXT PRIMARY KEY,kind TEXT NOT NULL,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dependencies(id TEXT,revision INTEGER,target TEXT,target_revision INTEGER,
 PRIMARY KEY(id,revision,target,target_revision));
CREATE INDEX IF NOT EXISTS dependency_target ON dependencies(target,target_revision);
CREATE TABLE IF NOT EXISTS validity(id TEXT,revision INTEGER,status TEXT NOT NULL,reason TEXT NOT NULL,
 updated_at TEXT NOT NULL,PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS accepted(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,decision_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,status TEXT NOT NULL,lane TEXT NOT NULL,
 owner TEXT,lease_until REAL,generation INTEGER NOT NULL,body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS run_queue ON runs(status,lane,lease_until);
CREATE TABLE IF NOT EXISTS run_objects(run_id TEXT,id TEXT,revision INTEGER,PRIMARY KEY(run_id,id,revision));
CREATE TABLE IF NOT EXISTS grants(token_hash TEXT PRIMARY KEY,run_id TEXT NOT NULL,generation INTEGER NOT NULL,
 input_revision INTEGER NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,digest TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trace(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,at TEXT NOT NULL,
 kind TEXT NOT NULL,body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS trace_run ON trace(run_id,seq);
CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,signature TEXT UNIQUE NOT NULL,status TEXT NOT NULL,
 owner TEXT,lease_until REAL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_state(id TEXT PRIMARY KEY,status TEXT NOT NULL,decision_id TEXT);
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job_leases(id TEXT PRIMARY KEY,owner TEXT NOT NULL,lease_until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,revision UNINDEXED,kind UNINDEXED,title,text,
 tokenize='unicode61');
'''


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'research.sqlite'
        self.objects = self.root / 'objects'
        self.objects.mkdir(exist_ok=True)
        self._cache = {}
        self._cache_lock = threading.RLock()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            row = db.execute("SELECT body FROM metadata WHERE key='schema'").fetchone()
            if row and json.loads(row[0]) != 'research.1':
                raise ValueError('此目录使用另一数据格式，请使用新的研究数据目录')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('schema',?)", (canonical('research.1'),))

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def blob(self, raw: bytes) -> str:
        sha = digest(raw)
        path = self.blob_path(sha)
        if path.exists():
            if digest(path.read_bytes()) != sha:
                raise ValueError('已有内容对象摘要损坏')
        else:
            atomic_file(path, raw)
        return sha

    def blob_path(self, sha: str) -> Path:
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('无效内容摘要')
        return self.objects / sha[:2] / sha

    def read_blob(self, sha: str) -> bytes:
        raw = self.blob_path(sha).read_bytes()
        if digest(raw) != sha:
            raise ValueError('内容对象摘要损坏')
        return raw

    def put(self, db, kind: str, value, *, dependencies=(), expected=None):
        model = REVISION_MODELS[kind].model_validate(value)
        body = model.model_dump(mode='json')
        encoded = canonical(body)
        previous = db.execute('SELECT body FROM revisions WHERE id=? AND revision=?',
                              (model.id, model.revision)).fetchone()
        if previous:
            if previous[0] != encoded:
                raise Conflict('不可覆盖已经保存的修订')
            return model
        head = db.execute('SELECT kind,revision FROM heads WHERE id=?', (model.id,)).fetchone()
        current = head['revision'] if head else 0
        if head and head['kind'] != kind:
            raise Conflict('对象类型不可改变')
        if (expected is not None and current != expected) or model.revision != current + 1:
            raise Conflict('对象版本已变化，请刷新后重试')
        refs = [Ref.model_validate(r) for r in dependencies]
        for ref in refs:
            self.get(ref, db=db)
            if ref.id == model.id:
                if ref.revision >= model.revision:
                    raise ValueError('依赖不能指向当前或未来修订')
        db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',
                   (model.id, model.revision, kind, encoded, digest(body)))
        db.execute('INSERT INTO heads VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision',
                   (model.id, kind, model.revision))
        for ref in refs:
            db.execute('INSERT OR IGNORE INTO dependencies VALUES(?,?,?,?)',
                       (model.id, model.revision, ref.id, ref.revision))
        if kind in ('source', 'assertion', 'model', 'subject'):
            import jieba
            title = body.get('title', body.get('name', ''))
            text = body.get('statement', '') or '\n'.join(b['text'] for b in body.get('blocks', []))
            db.execute('INSERT INTO search VALUES(?,?,?,?,?)',
                       (model.id, model.revision, kind, title, ' '.join(jieba.cut(title + ' ' + text))))
        # Cache only committed revisions on reads; rolled-back writes cannot leak through a cache.
        return model

    def get(self, ref, kind=None, *, db=None):
        if db is None:
            with self.connect() as conn:
                return self.get(ref, kind, db=conn)
        if isinstance(ref, str):
            row = db.execute('SELECT revision FROM heads WHERE id=?', (ref,)).fetchone()
            if not row:
                raise KeyError('对象不存在：' + ref)
            ref = Ref(id=ref, revision=row[0])
        else:
            ref = Ref.model_validate(ref)
        row = db.execute('SELECT kind,body,digest FROM revisions WHERE id=? AND revision=?',
                         (ref.id, ref.revision)).fetchone()
        if not row or (kind and row['kind'] != kind):
            raise KeyError('指定修订不存在：' + ref.key)
        with self._cache_lock:
            cached = self._cache.get((ref.key, row['digest']))
        if cached is None:
            cached = json.loads(row['body'])
            if digest(cached) != row['digest']:
                raise ValueError('修订摘要损坏')
            with self._cache_lock:
                if len(self._cache) > 4096:
                    self._cache.clear()
                self._cache[(ref.key, row['digest'])] = cached
        # Models are fresh on each read; callers cannot mutate cached immutable data.
        return REVISION_MODELS[row['kind']].model_validate(copy.deepcopy(cached))

    def list(self, kind, *, db=None, all_revisions=False):
        if db is None:
            with self.connect() as conn:
                return self.list(kind, db=conn, all_revisions=all_revisions)
        query = 'SELECT id,revision FROM revisions WHERE kind=? ORDER BY rowid DESC' if all_revisions else \
                'SELECT id,revision FROM heads WHERE kind=? ORDER BY rowid DESC'
        return [self.get(Ref(id=r[0], revision=r[1]), kind, db=db) for r in db.execute(query, (kind,))]

    def closure(self, ref, *, db=None):
        if db is None:
            with self.connect() as conn:
                return self.closure(ref, db=conn)
        pending, seen, result = [Ref.model_validate(ref)], set(), []
        while pending:
            item = pending.pop()
            if item.key in seen:
                continue
            seen.add(item.key)
            result.append(self.get(item, db=db))
            pending += [Ref(id=r[0], revision=r[1]) for r in db.execute(
                'SELECT target,target_revision FROM dependencies WHERE id=? AND revision=?',
                (item.id, item.revision))]
        return result

    def invalidate(self, db, ref, reason, status='needs_review'):
        ref = Ref.model_validate(ref)
        pending, seen = [ref], set()
        while pending:
            item = pending.pop()
            if item.key in seen:
                continue
            seen.add(item.key)
            db.execute('INSERT INTO validity VALUES(?,?,?,?,?) ON CONFLICT(id,revision) DO UPDATE SET '
                       'status=excluded.status,reason=excluded.reason,updated_at=excluded.updated_at',
                       (item.id, item.revision, status if item.key == ref.key else 'needs_review', reason, utcnow()))
            pending += [Ref(id=r[0], revision=r[1]) for r in db.execute(
                'SELECT id,revision FROM dependencies WHERE target=? AND target_revision=?',
                (item.id, item.revision))]
        return sorted(seen)

    def validity(self, ref, *, db=None):
        if db is None:
            with self.connect() as conn:
                return self.validity(ref, db=conn)
        ref = Ref.model_validate(ref)
        row = db.execute('SELECT status,reason,updated_at FROM validity WHERE id=? AND revision=?',
                         (ref.id, ref.revision)).fetchone()
        return dict(row) if row else {'status': 'available', 'reason': '', 'updated_at': None}

    def once(self, operation_id, payload, fn, *, db=None):
        if db is None:
            with self.connect(write=True) as conn:
                return self.once(operation_id, payload, fn, db=conn)
        signature = digest(payload)
        row = db.execute('SELECT digest,body FROM commands WHERE id=?', (operation_id,)).fetchone()
        if row:
            if row['digest'] != signature:
                raise Conflict('此操作标识已用于不同请求')
            return json.loads(row['body'])
        value = fn(db)
        encoded = canonical(value)
        db.execute('INSERT INTO commands VALUES(?,?,?)', (operation_id, signature, encoded))
        return json.loads(encoded)

    def event(self, db, run_id, kind, value):
        encoded = canonical(value)
        if len(encoded) > 64000:
            encoded = canonical({'content_digest': self.blob(encoded.encode()), 'preview': encoded[:4000]})
        db.execute('INSERT INTO trace(run_id,at,kind,body) VALUES(?,?,?,?)',
                   (run_id, utcnow(), kind, encoded))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM metadata WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect(write=True) as db:
            db.execute('INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',
                       (key, canonical(value)))

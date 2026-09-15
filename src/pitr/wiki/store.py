"""Frozen event payloads are the authority. SQL state and Markdown are projections."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from pitr.desk.storage import canonical

BUCKETS = ('sources', 'revisions', 'status', 'proposals', 'issues', 'uses', 'inspections', 'settings', 'jobs', 'update_schedules', 'companies', 'source_checks')


def reduce_event(state: dict, event: dict) -> dict:
    """Pure replacement reducer: no I/O, clocks, inference, or external effects."""
    result = copy.deepcopy(state)
    for change in event['changes']:
        bucket, key, value = change['bucket'], change['key'], change['value']
        if bucket not in BUCKETS:
            raise ValueError('Unknown projection bucket: ' + bucket)
        if bucket == 'revisions' and key in result.get(bucket, {}) and result[bucket][key] != value:
            raise ValueError('Immutable revision cannot be replaced')
        result.setdefault(bucket, {})[key] = copy.deepcopy(value)
    return result


class Objects:
    def __init__(self, root):
        self.root = Path(root) / 'objects' / 'sha256'
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, sha):
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid SHA-256 object identity')
        return self.root / sha[:2] / sha[2:]

    def put(self, raw: bytes) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        path = self.path(sha)
        path.parent.mkdir(exist_ok=True)
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if path.exists():
            self.get(sha)
            return sha
        fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return sha

    def get(self, sha):
        raw = self.path(sha).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('对象摘要校验失败：' + sha)
        return raw

    def json(self, value):
        return self.put(canonical(value).encode())


def initialize(store):
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS wiki_events(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
          company TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
          payload_object TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS wiki_events_no_update BEFORE UPDATE ON wiki_events
          BEGIN SELECT RAISE(ABORT,'Wiki events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS wiki_events_no_delete BEFORE DELETE ON wiki_events
          BEGIN SELECT RAISE(ABORT,'Wiki events are append-only'); END;
        CREATE TABLE IF NOT EXISTS wiki_state(bucket TEXT, key TEXT, body TEXT NOT NULL, PRIMARY KEY(bucket,key));
        CREATE TABLE IF NOT EXISTS wiki_commands(id TEXT PRIMARY KEY, digest TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS wiki_outbox(id TEXT PRIMARY KEY, kind TEXT, body TEXT,
          status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0,
          owner TEXT, lease_until REAL, error TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS wiki_schedule(name TEXT PRIMARY KEY, next_at REAL);
        CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(ref UNINDEXED, company UNINDEXED, text, tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS wiki_vectors(ref TEXT, model TEXT, body_sha TEXT, vector BLOB, PRIMARY KEY(ref,model));
        CREATE TABLE IF NOT EXISTS wiki_projection_meta(key TEXT PRIMARY KEY, value TEXT);
        ''')


def state(db, bucket=None):
    if bucket:
        return {r['key']: json.loads(r['body']) for r in db.execute('SELECT key,body FROM wiki_state WHERE bucket=?', (bucket,))}
    result = {b: {} for b in BUCKETS}
    for row in db.execute('SELECT * FROM wiki_state'):
        result[row['bucket']][row['key']] = json.loads(row['body'])
    return result


def get(db, bucket, key):
    row = db.execute('SELECT body FROM wiki_state WHERE bucket=? AND key=?', (bucket, key)).fetchone()
    return json.loads(row['body']) if row else None


def write_projection(db, payload):
    # Use the same reducer as rebuild, including the immutable-revision guard.
    previous = {b: {} for b in BUCKETS}
    for c in payload['changes']:
        value = get(db, c['bucket'], c['key'])
        if value is not None:
            previous[c['bucket']][c['key']] = value
    reduced = reduce_event(previous, payload)
    for c in payload['changes']:
        db.execute('INSERT OR REPLACE INTO wiki_state VALUES(?,?,?)',
                   (c['bucket'], c['key'], canonical(reduced[c['bucket']][c['key']])))


def change(bucket, key, value):
    return {'bucket': bucket, 'key': key, 'value': value}

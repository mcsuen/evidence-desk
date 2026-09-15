"""Chinese BM25 with optional pinned ONNX vectors. Rank only eligible revisions."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import numpy as np
from pitr.desk.storage import canonical, digest
from .store import state

TOKENIZER_VERSION = 'jieba-0.42.1-search-finance.1'
MODEL = 'intfloat/multilingual-e5-small'
MODEL_REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
MODEL_KEY = MODEL + '@' + MODEL_REVISION + ':mean:l2:query-passage:512:chunks.1'
FINANCE = ('经营现金流', '股东可得现金', '营业利润率', '经营利润', '交易服务', '拼多多', '自由现金流', '非公认会计准则', '利润率', '期间口径', '资本开支', '履约成本', '销售费用', '研发费用')
_tokenizer = None


def tokens(text):
    global _tokenizer
    if _tokenizer is None:
        import jieba
        _tokenizer = jieba.Tokenizer()
        for word in FINANCE:
            _tokenizer.add_word(word, freq=100000)
    return ' '.join(t.lower() for t in _tokenizer.cut_for_search(text) if t.strip() and any(c.isalnum() for c in t))


def searchable(rev):
    return '\n'.join([rev['title'], rev.get('summary', ''), rev['content'], rev.get('scope', '')])


def rebuild_index(wiki, db):
    db.execute('DELETE FROM wiki_fts')
    for key, rev in state(db, 'revisions').items():
        if rev['kind'] == 'policy':
            continue
        db.execute('INSERT INTO wiki_fts VALUES(?,?,?)', (key, rev['company'], tokens(searchable(rev))))
    sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM wiki_events').fetchone()[0]
    db.execute('INSERT OR REPLACE INTO wiki_projection_meta VALUES(?,?)', ('fts_sequence', str(sequence)))
    db.execute('INSERT OR REPLACE INTO wiki_projection_meta VALUES(?,?)', ('tokenizer', TOKENIZER_VERSION))


def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda key: (-scores[key], key)), scores


def _model_dir(wiki):
    return wiki.store.root / 'models' / 'multilingual-e5-small' / MODEL_REVISION


def install_model(wiki):
    """Explicit CLI action; hooks and queries never download model assets."""
    from huggingface_hub import snapshot_download
    root = _model_dir(wiki)
    snapshot_download(MODEL, revision=MODEL_REVISION, local_dir=root,
                      allow_patterns=['onnx/model.onnx', '*token*', 'config.json', 'special_tokens_map.json', 'sentencepiece*'])
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob('*') if p.is_file() and '.cache' not in p.parts}
    (root / 'pitr-model-lock.json').write_text(canonical({'model': MODEL_KEY, 'files': files}))
    return {'model': MODEL_KEY, 'path': str(root)}


def encoder(wiki):
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    root = _model_dir(wiki)
    lock = json.loads((root / 'pitr-model-lock.json').read_text())
    if lock['model'] != MODEL_KEY:
        raise ValueError('本地模型版本不匹配')
    for name, sha in lock['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != sha:
            raise ValueError('本地模型或 tokenizer 摘要不匹配')
    if not any(m['model'] == MODEL for m in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(model=MODEL, pooling=PoolingType.MEAN, normalization=True,
            sources=ModelSource(hf=MODEL), dim=384, model_file='onnx/model.onnx')
    return TextEmbedding(model_name=MODEL, specific_model_path=str(root), providers=['CPUExecutionProvider'], threads=2)


def _encode(model, text, query=False):
    # Token windows prevent long pages silently losing their ending. Each document
    # vector averages normalized overlapping passage vectors then normalizes again.
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation()
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    chunks = [tokenizer.decode(ids[i:i+440]) for i in range(0, max(1, len(ids)), 400)]
    values = np.asarray(list(model.embed([('query: ' if query else 'passage: ') + c for c in chunks])), dtype=np.float32)
    result = values.mean(axis=0)
    if result.shape != (384,) or not np.isfinite(result).all() or not np.linalg.norm(result):
        raise ValueError('向量维度或数值不符合模型契约')
    return result / np.linalg.norm(result)


def build_vectors(wiki):
    model = encoder(wiki)
    with wiki.store.connect() as db:
        revisions = state(db, 'revisions')
    count = 0
    for key, rev in revisions.items():
        if rev['kind'] == 'policy':
            continue
        vector = _encode(model, searchable(rev))
        with wiki.store.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO wiki_vectors VALUES(?,?,?,?)', (key, MODEL_KEY, digest(searchable(rev)), vector.astype('<f4').tobytes()))
        count += 1
    return {'model': MODEL_KEY, 'indexed': count}


def search(wiki, company, query, *, as_of=None, hybrid=False, limit=10):
    started = time.monotonic()
    if not query.strip():
        return {'items': [], 'mode': 'bm25', 'warnings': [], 'elapsed_ms': 0}
    warnings = []
    with wiki.store.connect() as db:
        st = wiki._view_state(db, as_of)
        eligible = {r['ref']: r for r in wiki._visible(st, company, as_of) if r['kind'] != 'policy'}
        # Filter before computing corpus statistics/ranks, including historical
        # queries. No future or other-company page contributes document frequency.
        memory = sqlite3.connect(':memory:')
        try:
            memory.execute('CREATE VIRTUAL TABLE documents USING fts5(ref UNINDEXED, text)')
            memory.executemany('INSERT INTO documents VALUES(?,?)', [(key, tokens(searchable(rev))) for key, rev in eligible.items()])
            terms = list(dict.fromkeys(tokens(query).split()))[:80]
            match = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
            lexical = [row[0] for row in memory.execute('SELECT ref FROM documents WHERE documents MATCH ? ORDER BY bm25(documents), ref LIMIT 50', (match,))] if match else []
        finally:
            memory.close()
        rankings = [lexical]
        if hybrid:
            try:
                model = encoder(wiki)
                vector = _encode(model, query, query=True)
                scores = []
                for row in db.execute('SELECT * FROM wiki_vectors WHERE model=?', (MODEL_KEY,)):
                    rev = eligible.get(row['ref'])
                    if rev and row['body_sha'] == digest(searchable(rev)):
                        value = np.frombuffer(row['vector'], dtype='<f4')
                        if value.shape == (384,) and np.isfinite(value).all():
                            scores.append((float(value @ vector), row['ref']))
                if not scores:
                    raise ValueError('当前范围尚无有效语义索引')
                rankings.append([key for score, key in sorted(scores, key=lambda v: (-v[0], v[1]))[:50]])
            except (ImportError, OSError, ValueError, KeyError, RuntimeError) as error:
                warnings.append('语义索引不可用，使用 BM25：' + str(error))
        order, scores = rrf(*rankings)
    # Second availability check after retrieval prevents a concurrently withdrawn
    # result leaking through a previously built lexical/vector candidate list.
    live = {r['ref']: r for r in wiki.list(company, as_of, include_blocked=False)}
    items = []
    from .validation import hard_failures
    from .contracts import IssueInput, Reference
    from .store import get
    for key in order:
        if key not in live:continue
        with wiki.store.connect() as db:
            frozen = get(db, 'revisions', key)
            failures = hard_failures(wiki, db, frozen)
        if failures:
            if not as_of:
                for failure in failures:
                    wiki.report(IssueInput(operation_id='use-check:'+digest([key,failure]),
                        target=Reference(id=frozen['id'],version=frozen['version']),issue_type=failure['type'],
                        description=failure['detail'],discovered_by='rule'))
            warnings.append('版本无法通过对象或证据校验：'+key)
            continue
        items.append({**eligible[key], 'score': scores[key]})
        if len(items)>=max(1,min(limit,50)):break
    for item in items:
        item['availability'] = live[item['ref']]['availability']
    return {'items': items, 'mode': 'rrf' if len(rankings) == 2 else 'bm25', 'warnings': warnings,
            'elapsed_ms': round((time.monotonic()-started)*1000, 2), 'tokenizer': TOKENIZER_VERSION}

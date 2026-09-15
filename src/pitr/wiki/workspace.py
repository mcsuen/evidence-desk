"""Light reading models. Exact-version content and originals load on demand."""
import json
from .service import refkey
from .contracts import timestamp


def brief(revision):
    keys = ('id', 'version', 'ref', 'kind', 'page_type', 'title', 'summary', 'availability', 'review_status',
            'published_at', 'policy', 'publication_sequence', 'reason', 'business_period')
    return {key: revision.get(key) for key in keys}


def workspace(wiki, company, as_of=None):
    as_of = timestamp(as_of) if as_of else None
    from .jobs import WikiJobs
    with wiki.store.connect() as db:
        st = wiki._view_state(db, as_of)
        pages = wiki._visible(st, company, as_of, include_blocked=True)
        sources = [s for s in st.get('sources', {}).values() if s['company'] in (company, '')]
        proposals = [p for p in st.get('proposals', {}).values() if p['company'] in (company, '*')]
        policies = [r for r in pages if r['kind'] == 'policy']
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM wiki_events WHERE (? IS NULL OR occurred_at<=?)', (as_of, as_of)).fetchone()[0]
        return {'company': company, 'as_of': as_of, 'sequence': sequence,
            'companies': list(WikiJobs(wiki).companies(db).values()) if not as_of else [],
            'pages': [brief(p) for p in pages if p['kind'] != 'policy'],
            'policy': brief(max(policies, key=lambda p: p['version'])) if policies else None,
            'sources': [{**{k: s.get(k) for k in ('id', 'title', 'provider', 'category', 'subject_company', 'url', 'available_at', 'observed_at', 'state', 'policy', 'job_id', 'issues')},
                         'contributes_to': [brief(p) for p in pages if any(c['source_id'] == s['id'] for c in p.get('citations', []))]} for s in sources],
            'proposals': [{k: p.get(k) for k in ('id', 'company', 'status', 'created_at', 'digest')} |
                          {'reason': p['request']['reason'], 'pages': [c['title'] for c in p['request']['changes']]} for p in proposals],
            'issues': [i for i in st.get('issues', {}).values() if i['company'] == company],
            'jobs': [{**{k: j.get(k) for k in ('id', 'company', 'task_id', 'stage', 'execution_status', 'publication_status', 'created_at', 'proposal_id', 'policy')}, 'publication_status': 'published' if st.get('proposals', {}).get(j.get('proposal_id'), {}).get('status') == 'adopted' else j.get('publication_status')}
                     for j in sorted(st.get('jobs', {}).values(), key=lambda j: j['created_at'], reverse=True) if j['company'] == company][:20],
            'schedule': st.get('update_schedules', {}).get(company)}


def page(wiki, object_id, version=None, as_of=None):
    as_of = timestamp(as_of) if as_of else None
    with wiki.store.connect() as db:
        st = wiki._view_state(db, as_of)
        versions = [r for r in st.get('revisions', {}).values() if r['id'] == object_id and (not as_of or r['published_at'] <= as_of)]
        revision = next((r for r in versions if r['version'] == version), None) if version else max(versions, key=lambda r: r['version'], default=None)
        if not revision:
            raise KeyError('该时点没有这个页面版本')
        key = refkey(revision)
        current = {**revision, **st.get('status', {}).get(key, {}), 'ref': key}
        visible = wiki._visible(st, revision['company'], as_of, include_blocked=True)
        # Backlinks retain exact versions. Related links do not imply invalidation.
        backlinks = [{**brief(r), 'relation': rel['relation']} for r in visible for rel in r.get('relations', []) if refkey(rel['target']) == key]
        ids = {c['source_id'] for c in revision.get('citations', [])}
        sources = [s for sid, s in st.get('sources', {}).items() if sid in ids]
        policy = st.get('revisions', {}).get(refkey(revision['policy'])) if revision.get('policy') else None
        uses = [{k: use.get(k) for k in ('id', 'title', 'created_at', 'status')} for use in st.get('uses', {}).values() if any(refkey(r) == key for r in use.get('used', []))]
        return {'revision': current, 'sources': sources, 'backlinks': backlinks, 'uses': uses,
                'policy': policy, 'versions': [brief(r) for r in sorted(versions, key=lambda r: r['version'], reverse=True)]}


def source(wiki, sid, as_of=None):
    as_of = timestamp(as_of) if as_of else None
    with wiki.store.connect() as db:
        st = wiki._view_state(db, as_of)
        original = st.get('sources', {}).get(sid)
        if not original or (as_of and original['available_at'] > as_of):
            raise KeyError('该时点没有这份资料')
        pages = wiki._visible(st, original['company'], as_of, include_blocked=True)
        return {**original, 'contributes_to': [brief(p) for p in pages if any(c['source_id'] == sid for c in p.get('citations', []))]}


def log(wiki, company, as_of=None):
    as_of = timestamp(as_of) if as_of else None
    with wiki.store.connect() as db:
        events = db.execute("SELECT * FROM wiki_events WHERE company IN (?, '*') AND (? IS NULL OR occurred_at<=?) ORDER BY sequence DESC LIMIT 120", (company, as_of, as_of)).fetchall()
        return [{k: e[k] for k in ('sequence', 'kind', 'occurred_at')} | {'details': json.loads(wiki.objects.get(e['payload_object']))['details']} for e in events]

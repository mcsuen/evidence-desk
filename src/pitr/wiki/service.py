from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext

from pitr.desk.contracts import Citation, utcnow
from pitr.desk.storage import Conflict, canonical, digest, uid
from .contracts import (CaptureEnvelope, ProposalInput, DecisionRecord, IssueInput,
                        IssueDecision, Reference, timestamp)
from .store import Objects, initialize, state, get, change, write_projection, reduce_event

POLICY_ID = 'policy:company-research'
POLICY_TEXT = '''# 公司研究维护规范

资料保留原件、出处、业务期间、可用时间与修订关系。讨论和 Agent 回答是线索或解释，不能替代公司披露。

页面分为来源解读、公司、概念与方法、研究专题和综合分析；事实、解释和方法单独标识。目录提供一句话摘要，正文保存跨资料综合。

事实和解释必须引用原文段落；每个数值必须绑定指标、值、单位、期间和口径。方法必须说明适用条件、公式、失败情形和案例。相同原件的转述不增加独立证据。

每次收录先阅读相关 Wiki，形成完整的跨页面提案；人审核并采纳后原子发布。问答记录实际引用的版本，有价值的新认识回到提案。

确定性证据错误隔离；语义疑点保留证据并人工复核。修正发布新版本，沿支撑和使用关系登记下游复核。误报追加关闭决定。普通相关链接不传播失效。

每日检查原件、引文、数值、链接与投影；每周有预算地检查语义和组织缺口。历史事实不因年代久失效。严格时点查询不得使用后来发布的总结或纠错信息。
'''
HARD = {'citation', 'object', 'numeric', 'calculation'}
BLOCKED = {'quarantined', 'withdrawn', 'superseded'}
CAUSAL = {'supports', 'derived_from', 'used_in'}


def refkey(ref):
    return ref.key if isinstance(ref, Reference) else f"{ref['id']}@v{ref['version']}"


def causal_edges(revisions):
    """Normalize typed relations into exact-version upstream → dependent edges."""
    edges = set()
    for revision in revisions.values():
        owner = refkey(revision)
        for relation in revision.get('relations', []):
            target = refkey(relation['target'])
            if relation['relation'] == 'derived_from':
                edges.add((target, owner))
            elif relation['relation'] in ('supports', 'used_in'):
                edges.add((owner, target))
    return edges


def source_key(provider, external_id):
    return provider + ':' + external_id


class Wiki:
    def __init__(self, desk):
        self.desk = desk
        self.store = desk.store
        self.objects = Objects(desk.root)
        self.markdown = desk.root / 'wiki'
        initialize(self.store)
        self.bootstrap()

    def _cached(self, db, operation, payload):
        row = db.execute('SELECT * FROM wiki_commands WHERE id=?', (operation,)).fetchone()
        if row:
            if row['digest'] != digest(payload):
                raise Conflict('相同操作标识不能用于不同请求')
            return json.loads(row['result'])

    def _remember(self, db, operation, payload, result):
        db.execute('INSERT INTO wiki_commands VALUES(?,?,?)', (operation, digest(payload), canonical(result)))
        return result

    def _emit(self, db, company, kind, changes, *, jobs=(), details=None, at=None):
        payload = {'format': 'wiki-event.1', 'changes': changes, 'details': details or {}}
        sha = self.objects.json(payload)
        eid, now = uid('we'), at or utcnow()
        cursor = db.execute('INSERT INTO wiki_events(id,company,kind,occurred_at,payload_object) VALUES(?,?,?,?,?)',
                            (eid, company, kind, now, sha))
        write_projection(db, payload)
        for n, (job_kind, body) in enumerate(jobs):
            db.execute('INSERT INTO wiki_outbox(id,kind,body) VALUES(?,?,?)',
                       (f'{eid}:{n}', job_kind, canonical(body)))
        # Rendering is an idempotent delivery intent, never an event-replay effect.
        db.execute('INSERT INTO wiki_outbox(id,kind,body) VALUES(?,?,?)',
                   (eid + ':render', 'render', canonical({'sequence': cursor.lastrowid})))
        return cursor.lastrowid

    def bootstrap(self):
        with self.store.connect(write=True) as db:
            if not get(db, 'settings', 'baseline') and db.execute('SELECT 1 FROM wiki_events LIMIT 1').fetchone():
                rebuilt={}
                for event in db.execute('SELECT * FROM wiki_events ORDER BY sequence'):
                    rebuilt=reduce_event(rebuilt,json.loads(self.objects.get(event['payload_object'])))
                for bucket, values in rebuilt.items():
                    for key, value in values.items():
                        db.execute('INSERT OR REPLACE INTO wiki_state VALUES(?,?,?)',(bucket,key,canonical(value)))
            if not get(db, 'settings', 'baseline'):
                now = utcnow()
                policy = dict(id=POLICY_ID, version=1, kind='policy', company='*', title='公司研究维护规范',
                              content=POLICY_TEXT, summary='资料、知识、审核、纠错和巡检的工作约定。',
                              published_at=now, policy=None, citations=[], relations=[], origin='installation_default',
                              review_status='candidate', publication_sequence=1, reason='安装默认维护规范')
                policy['body_object'] = self.objects.json(policy)
                self._emit(db, '*', 'policy.initialized', [change('revisions', refkey(policy), policy),
                    change('status', refkey(policy), {'availability': 'available', 'review_status': 'candidate'}),
                    change('settings', 'baseline', {'migrated_at': now, 'format': 'wiki.1'})])

    def register_document(self, db, doc, enqueue=True):
        if get(db, 'sources', doc['id']):
            return
        path = self.desk.files / doc['file_name']
        if not path.exists():
            return  # Missing originals remain visible in the source inventory.
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc['digest']:
            raise ValueError('原始资料摘要不一致')
        sha = self.objects.put(raw)
        provider='manual' if doc['url'].startswith('upload:') else 'official'
        if doc['url'].startswith('upload:research/'):enqueue=False
        source = {**doc, 'provider': provider, 'external_id': doc['url'], 'payload_object': sha,
                  'state': 'available', 'revision_of': doc.get('supersedes'), 'review_status': 'unreviewed',
                  'capture_key': source_key(provider, doc['url']), 'policy': self._policy(db)}
        source['record_object'] = self.objects.json({k:source[k] for k in ('id','provider','digest','payload_object','blocks')})
        changes = [change('sources', doc['id'], source)]
        previous = get(db, 'sources', doc.get('supersedes', ''))
        if previous:
            changes.append(change('sources', previous['id'], {**previous, 'state': 'superseded', 'changed_at': utcnow()}))
        self._emit(db, doc['company'], 'source.ingested', changes,
                   jobs=[('compile', {'source_ids': [doc['id']], 'company': doc['company']})] if enqueue else [])
        if previous:
            self._source_impacts(db, previous['id'], '来源已有修订版本')

    def _policy(self, db):
        revisions = [r for r in state(db, 'revisions').values() if r['kind'] == 'policy']
        latest = max(revisions, key=lambda r: r['version'])
        return {'id': latest['id'], 'version': latest['version']}

    def policy(self):
        with self.store.connect() as db:
            return get(db, 'revisions', refkey(self._policy(db)))

    def capture(self, request: CaptureEnvelope, db=None, *, enqueue=True):
        from .capture import sanitize
        with self.store.connect(write=True) if db is None else nullcontext(db) as conn:
            payload = request.model_dump(mode='json')
            cached = self._cached(conn, request.operation_id, payload)
            if cached:
                return cached
            if request.origin in ('pitr-wiki', 'pitr-bot'):
                return self._remember(conn, request.operation_id, payload, {'status': 'ignored_echo'})
            if request.provider == 'official':
                raise ValueError('官方原件请通过资料导入入口收录')
            identity = source_key(request.provider, request.external_id)
            sources = state(conn, 'sources')
            prior = next((s for s in reversed(list(sources.values())) if s.get('capture_key') == identity and s['state'] == 'available'), None)
            if request.revision_of:
                prior = sources.get(request.revision_of)
                if not prior or prior.get('capture_key') != identity:
                    raise ValueError('来源修订身份不一致')
            if request.action in ('revise', 'withdraw') and not prior:
                return self._remember(conn, request.operation_id, payload, {'status': 'not_captured'})
            now = utcnow()
            if request.action == 'withdraw':
                self._emit(conn, prior['company'], 'source.withdrawn', [change('sources', prior['id'],
                           {**prior, 'state': 'withdrawn', 'changed_at': now})])
                self._source_impacts(conn, prior['id'], '原始消息已删除或撤回')
                return self._remember(conn, request.operation_id, payload, {'id': prior['id'], 'status': 'withdrawn'})
            text = sanitize(request.text)
            sha = self.objects.put(text.encode())
            # No client-selected digest may smuggle an unverified original into evidence.
            attachments = []
            for attachment in request.attachments:
                self.objects.get(attachment)
                attachments.append(attachment)
            if prior and prior['digest'] == sha and prior['title'] == request.title and sorted(prior.get('attachments', [])) == sorted(attachments):
                return self._remember(conn, request.operation_id, payload, {'id': prior['id'], 'status': 'duplicate'})
            sid = 'capture_' + digest([identity, sha, request.operation_id])[:32]
            source = dict(id=sid, company=request.company.upper(), provider=request.provider,
                external_id=request.external_id, capture_key=identity, title=request.title, url=request.url,
                session_id=request.session_id, thread_id=request.thread_id, digest=sha, payload_object=sha,
                attachments=attachments, available_at=now, declared_available_at=request.available_at,
                observed_at=request.observed_at or now, published_at=now, origin_group=identity,
                state='available', revision_of=prior['id'] if prior else None, policy=self._policy(conn),
                classification='classified' if request.company else 'pending',
                blocks=[{'id': 'text', 'text': text}])
            source['record_object'] = self.objects.json({k:source[k] for k in ('id','provider','digest','payload_object','blocks','attachments')})
            changes = [change('sources', sid, source)]
            if prior:
                changes.append(change('sources', prior['id'], {**prior, 'state': 'superseded', 'changed_at': now}))
            self._emit(conn, request.company, 'source.captured', changes,
                jobs=[('compile', {'company': request.company.upper(), 'source_ids': [sid],
                                   'session_id': request.session_id})] if request.company and enqueue else [])
            if prior:
                self._source_impacts(conn, prior['id'], '已采集消息发生编辑')
            return self._remember(conn, request.operation_id, payload, {'id': sid, 'status': 'captured'})

    def classify(self, sid, company, operation_id):
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,15}', company):
            raise ValueError('请选择公司代码')
        with self.store.connect(write=True) as db:
            payload = [sid, company]
            old = self._cached(db, operation_id, payload)
            if old:
                return old
            source = get(db, 'sources', sid)
            if not source:
                raise KeyError('资料不存在')
            if source['company'] and source['company'] != company:
                raise ValueError('已归类来源不能改写公司身份')
            self._emit(db, company, 'source.classified', [change('sources', sid,
                {**source, 'company': company, 'classification': 'classified'})],
                jobs=[('compile', {'source_ids': [sid], 'company': company})])
            return self._remember(db, operation_id, payload, {'id': sid, 'company': company})

    def _view_state(self, db, as_of=None):
        if not as_of:
            return state(db)
        cutoff = timestamp(as_of)
        result = {}
        for event in db.execute('SELECT * FROM wiki_events ORDER BY sequence'):
            # Baselines contain actual saved history, never invented old decisions.
            if event['occurred_at'] <= cutoff:
                result = reduce_event(result, json.loads(self.objects.get(event['payload_object'])))
        # Official source availability is independent of the later ingestion clock.
        result.setdefault('sources', {})
        for sid, source in state(db, 'sources').items():
            if source['provider'] == 'official' and source['available_at'] <= cutoff:
                if sid in result['sources']:
                    continue
                copied = dict(source)
                # Original publication may predate ingestion; later processing and
                # review metadata must not travel backwards with those bytes.
                for key in ('policy', 'job_id', 'checks', 'review_status', 'revision_of'):
                    copied.pop(key, None)
                if copied.get('changed_at', '') > cutoff:
                    copied['state'] = 'available'
                    copied.pop('changed_at', None)
                result['sources'][sid] = copied
        return result

    def _visible(self, st, company, as_of=None, include_blocked=False):
        cutoff = timestamp(as_of) if as_of else None
        heads = {}
        for key, rev in st.get('revisions', {}).items():
            if rev['company'] not in (company, '*') or (cutoff and rev['published_at'] > cutoff):
                continue
            if rev['id'] not in heads or rev['version'] > heads[rev['id']]['version']:
                status = st.get('status', {}).get(key, {'availability': 'needs_review'})
                heads[rev['id']] = {**rev, **status, 'ref': key}
        # Never fall back to a superseded version when the newest is quarantined.
        return [r for r in heads.values() if include_blocked or r['availability'] not in BLOCKED]

    def list(self, company='PDD', as_of=None, include_blocked=True):
        with self.store.connect() as db:
            st = self._view_state(db, as_of)
            rows = self._visible(st, company, as_of, include_blocked)
            return sorted(rows, key=lambda r: (r['kind'], r.get('page_type') or '', r['title']))

    def overview(self, company):
        with self.store.connect() as db:
            st = state(db)
            return {'revisions': self._visible(st, company, include_blocked=True),
                'sources': [s for s in st['sources'].values() if s['company'] in (company, '')],
                'proposals': list(reversed([p for p in st['proposals'].values() if p['company'] in (company, '*')])),
                'issues': [i for i in st['issues'].values() if i['company'] == company],
                'inspections': list(reversed([i for i in st['inspections'].values() if i['company'] == company]))[:40],
                'policy': get(db, 'revisions', refkey(self._policy(db))),
                'outbox': [dict(r) for r in db.execute("SELECT id,kind,status,attempts,error FROM wiki_outbox WHERE status!='delivered' ORDER BY rowid LIMIT 50")],
                'markdown_path': str(self.markdown.absolute()),
                'sequence': db.execute('SELECT COALESCE(MAX(sequence),0) FROM wiki_events').fetchone()[0]}

    def _validate(self, db, request, check_context=True):
        st = state(db)
        now = utcnow()
        cutoff = request.as_of or now
        if cutoff > now:
            raise ValueError('研究时点不能位于未来')
        if request.policy.model_dump() != self._policy(db):
            raise Conflict('维护规范已有新版本，请重新校验提案')
        targets = {c.id: c.expected_version + 1 for c in request.changes}
        if len(targets) != len(request.changes):
            raise ValueError('同一批次不能重复修改一个身份')
        sources = {}
        inputs = {}
        for reference in request.inputs:
            key = reference.key
            rev = st['revisions'].get(key)
            if not rev or rev['company'] not in (request.company, '*') or rev['published_at'] > cutoff:
                raise ValueError('输入版本不属于当前公司与研究时点')
            status = st['status'].get(key, {})
            if status.get('availability') in BLOCKED:
                raise Conflict('所用知识已停止有效引用')
            inputs[key] = digest(status)
        for draft in request.changes:
            prevs = [r for r in st['revisions'].values() if r['id'] == draft.id]
            prev = max(prevs, key=lambda r: r['version']) if prevs else None
            if (prev['version'] if prev else 0) != draft.expected_version:
                raise Conflict('目标已有新版本，请重新生成审核包')
            if prev and (prev['kind'] != draft.kind or prev['company'] not in (request.company, '*')):
                raise ValueError('知识或页面身份不能改变')
            if draft.kind == 'policy':
                if draft.id != POLICY_ID or len(request.changes) != 1:
                    raise ValueError('规范独立审核发布')
                continue
            if draft.kind == 'page' and not draft.page_type:
                raise ValueError('需要选择页面类型')
            if draft.kind == 'knowledge' and (not draft.nature or not draft.scope):
                raise ValueError('知识需要内容性质和适用范围')
            if draft.nature == 'method' and not all((draft.applicability, draft.formula, draft.failure_cases, draft.example)):
                raise ValueError('方法需要适用条件、公式、失败情形和案例')
            if not draft.citations:
                raise ValueError('研究内容必须关联原始依据')
            for citation in draft.citations:
                source = self._check_citation(st, citation, request.company, cutoff)
                if draft.nature == 'fact' and (source['provider'] != 'official' or source.get('subject_company', request.company) != request.company):
                    raise ValueError('讨论和 Agent 输出不能直接升级为公司披露事实')
                sources[source['id']] = digest(source)
            from .validation import validate_numbers
            validate_numbers(db, draft.model_dump(), st['sources'])
            for relation in draft.relations:
                ref = relation.target
                key = ref.key
                rev = st['revisions'].get(key)
                if targets.get(ref.id) == ref.version:
                    if ref.id == draft.id:
                        raise ValueError('不能依赖自身')
                    continue
                if not rev or rev['company'] != request.company or rev['published_at'] > cutoff:
                    raise ValueError('关联版本不属于公司或研究时点')
                status = st['status'].get(key, {})
                if relation.relation in CAUSAL and status.get('availability') in BLOCKED:
                    raise Conflict('支撑知识版本已不可用')
                inputs[key] = digest(status)
            if draft.corrects:
                corrected = st['revisions'].get(draft.corrects.key)
                if not corrected or draft.corrects.id != draft.id or draft.corrects.version != draft.expected_version:
                    raise ValueError('纠错必须指向当前身份的上一个版本')
        # A causal cycle would make provenance and impact processing ambiguous.
        revisions = dict(st['revisions'])
        for draft in request.changes:
            revision = {**draft.model_dump(), 'version': draft.expected_version + 1}
            revisions[refkey(revision)] = revision
        edges = {}
        for upstream, dependent in causal_edges(revisions):
            edges.setdefault(upstream, set()).add(dependent)
        def visit(key, ancestors):
            if key in ancestors:
                raise ValueError('支撑关系不能构成循环')
            for dep in edges.get(key, ()):
                visit(dep, ancestors | {key})
        for key in edges:
            visit(key, set())
        observations={r['id']:digest(json.loads(r['body'])) for r in db.execute('SELECT id,source_id,body FROM observations') if r['source_id'] in sources}
        evidence_groups={st['sources'][sid]['origin_group'] for sid in sources if st['sources'][sid]['provider']=='official'}
        return {'sources': sources, 'inputs': inputs, 'observations':observations, 'independent_official_sources':len(evidence_groups), 'policy': request.policy.model_dump(),
                'checks': ['引用定位', '对象摘要', '数值绑定', '版本与时点', '依赖无环'],
                'semantic': 'human_review_required'}

    def _check_citation(self, st, citation, company, cutoff, live=True):
        c = citation.model_dump() if isinstance(citation, Citation) else citation
        source = st.get('sources', {}).get(c['source_id'])
        if not source or source['company'] != company or source['available_at'] > cutoff:
            raise ValueError('引用不属于公司或研究时点')
        if live and source['state'] != 'available':
            raise Conflict('依据已修订或撤回')
        self.objects.get(source['payload_object'])
        for attachment in source.get('attachments', []):
            self.objects.get(attachment)
        if source.get('record_object'):
            record=json.loads(self.objects.get(source['record_object']))
            if record!={k:source.get(k) for k in record}:
                raise ValueError('来源定位与冻结记录不一致')
        if not any(b['id'] == c['block_id'] and c['quote'] and c['quote'] in b['text'] for b in source['blocks']):
            raise ValueError('原文没有支持引用定位')
        return source

    def propose(self, request: ProposalInput, db=None, proposal_id=None):
        with self.store.connect(write=True) if db is None else nullcontext(db) as conn:
            payload = request.model_dump(mode='json')
            cached = self._cached(conn, request.operation_id, payload)
            if cached:
                return cached
            verification = self._validate(conn, request)
            if request.model_output:
                self.objects.get(request.model_output)
            if request.replaces:
                previous = get(conn, 'proposals', request.replaces)
                if not previous or previous['status'] != 'pending' or previous['company'] != request.company:
                    raise Conflict('只能重新编辑同公司待审核的提案')
            pid = proposal_id or uid('wp')
            before = {c.id: get(conn, 'revisions', f'{c.id}@v{c.expected_version}') for c in request.changes}
            proposal = dict(id=pid, company=request.company, request=payload, before=before,
                verification=verification, status='pending', created_at=utcnow())
            proposal['digest'] = digest(proposal)
            changes = [change('proposals', pid, proposal)]
            if request.replaces:
                changes.append(change('proposals', previous['id'], {**previous, 'status': 'replaced', 'replaced_by': pid}))
            self._emit(conn, request.company, 'proposal.created', changes)
            return self._remember(conn, request.operation_id, payload, proposal)

    def review(self, pid, decision: DecisionRecord, *, actor='human', db=None):
        if actor != 'human':
            raise PermissionError('Agent 可以收录、查询和提案；发布需要工作台人工审核')
        with self.store.connect(write=True) if db is None else nullcontext(db) as conn:
            payload = [pid, decision.model_dump(mode='json')]
            cached = self._cached(conn, decision.operation_id, payload)
            if cached:
                return cached
            proposal = get(conn, 'proposals', pid)
            if not proposal:
                raise KeyError('提案不存在')
            if proposal['digest'] != decision.digest or proposal['status'] != 'pending':
                raise Conflict('提案已经变化或处理，请重新查看')
            request = ProposalInput.model_validate(proposal['request'])
            now = utcnow()
            changes = []
            if decision.action == 'adopt':
                verification = self._validate(conn, request)
                if verification != proposal['verification']:
                    raise Conflict('输入依据或知识状态已变化，请重新校验完整提案')
                sequence = conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM wiki_events').fetchone()[0]
                for draft in request.changes:
                    rev = {**draft.model_dump(mode='json'), 'version': draft.expected_version + 1,
                        'company': '*' if draft.kind == 'policy' else request.company,
                        'published_at': now, 'publication_sequence': sequence,
                        'policy': request.policy.model_dump(), 'proposal_id': pid,
                        'review_status': 'adopted', 'decision': decision.model_dump(mode='json')}
                    cited={c.source_id for c in draft.citations}
                    rev['evidence_observations']=[json.loads(r['body']) for r in conn.execute('SELECT source_id,body FROM observations') if r['source_id'] in cited]
                    rev['body_object'] = self.objects.json(rev)
                    key = refkey(rev)
                    changes.extend([change('revisions', key, rev), change('status', key,
                        {'availability': 'available', 'review_status': 'adopted'})])
                    if draft.expected_version:
                        oldkey = f'{draft.id}@v{draft.expected_version}'
                        status = get(conn, 'status', oldkey) or {}
                        changes.append(change('status', oldkey, {**status, 'availability': 'superseded', 'replaced_by': key}))
                for issue_id in request.issue_ids:
                    issue = get(conn, 'issues', issue_id)
                    if not issue or issue['company'] != request.company:
                        raise ValueError('纠错问题不存在或公司不一致')
                    repaired = next((c for c in request.changes if c.corrects and c.corrects.key == refkey(issue['target'])), None)
                    if not repaired:
                        raise ValueError('修订未明确更正该问题版本')
                    changes.append(change('issues', issue_id, {**issue,
                        'content_resolution': f'{repaired.id}@v{repaired.expected_version + 1}', 'updated_at': now}))
            final = {**proposal, 'status': 'adopted' if decision.action == 'adopt' else 'rejected',
                     'decision': decision.model_dump(mode='json'), 'reviewed_at': now}
            changes.append(change('proposals', pid, final))

            self._emit(conn, request.company, 'proposal.' + final['status'], changes,
                       details={'proposal_id': pid, 'reason': decision.reason}, at=now)
            if decision.action == 'adopt':
                revised = {f'{c.id}@v{c.expected_version}' for c in request.changes if c.expected_version}
                published = {f'{c.id}@v{c.expected_version+1}' for c in request.changes}
                for oldkey in revised:
                    self._propagate(conn, oldkey, '上游知识发布了新版本', exclude=published)
                if any(c.kind == 'policy' for c in request.changes):
                    st = state(conn)
                    updates = [change('status', key, {**status, 'availability': 'needs_review', 'reason': '维护规范已更新'})
                        for key, status in st['status'].items() if status['availability'] not in BLOCKED
                        and st['revisions'][key]['kind'] != 'policy']
                    if updates:
                        self._emit(conn, '*', 'policy.review_required', updates)
            if decision.action=='adopt':
                for issue in state(conn,'issues').values():
                    if issue['state']!='open':continue
                    fresh=self._downstream(conn,refkey(issue['target']))
                    added={k:v for k,v in fresh.items() if k not in issue['impacts']}
                    if added:
                        issue['impacts'].update(added)
                        self._emit(conn,issue['company'],'issue.impact_extended',[change('issues',issue['id'],issue)])
                        self._propagate(conn,refkey(issue['target']),'支撑问题仍待处理')
            return self._remember(conn, decision.operation_id, payload, final)


    def _downstream(self, db, key):
        st = state(db)
        dependencies = {}
        for upstream, dependent in causal_edges(st['revisions']):
            dependencies.setdefault(dependent, set()).add(upstream)
        affected, seen = {}, {key}
        while True:
            added = set()
            for ref, rev in st['revisions'].items():
                if ref in seen:
                    continue
                if dependencies.get(ref, set()) & seen:
                    affected[ref] = {'kind': rev['kind'], 'title': rev['title'], 'decision': None,
                                     'previous_status': st['status'].get(ref, {})}
                    added.add(ref)
            for use in st['uses'].values():
                if any(refkey(r) in seen for r in use.get('used', [])):
                    affected['use:' + use['id']] = {'kind': 'research_result', 'title': use.get('title', use.get('question', '研究结果')), 'decision': None}
            if not added:
                break
            seen |= added
        return affected

    def _propagate(self, db, key, reason, exclude=()):
        impacts = self._downstream(db, key)
        changes = []
        for ref in impacts:
            if ref in exclude:
                continue
            status = get(db, 'status', ref)
            if status and status['availability'] not in BLOCKED:
                changes.append(change('status', ref, {**status, 'availability': 'needs_review', 'reason': reason}))
        if changes:
            self._emit(db, '*', 'dependency.review_required', changes, details={'upstream': key, 'reason': reason})
        return impacts

    def _source_impacts(self, db, sid, reason):
        for ref, rev in state(db, 'revisions').items():
            if any(c['source_id'] == sid for c in rev.get('citations', [])):
                issue = IssueInput(operation_id='source-change:' + digest([sid, ref, reason]),
                    target=Reference(id=rev['id'], version=rev['version']), issue_type='scope',
                    description=reason, discovered_by='rule')
                self.report(issue, db=db)

    def report(self, request: IssueInput, db=None):
        with self.store.connect(write=True) if db is None else nullcontext(db) as conn:
            payload = request.model_dump(mode='json')
            cached = self._cached(conn, request.operation_id, payload)
            if cached:
                return cached
            rev = get(conn, 'revisions', request.target.key)
            if not rev:
                raise KeyError('问题必须关联存在的版本')
            fingerprint = digest([request.target.key, request.issue_type, ' '.join((request.paragraph or request.description).split())])
            iid = 'issue_' + fingerprint[:32]
            existing = get(conn, 'issues', iid)
            if existing and existing['state'] == 'open':
                existing.setdefault('reports',[]).append(payload)
                self._emit(conn,existing['company'],'issue.reobserved',[change('issues',iid,existing)])
                return self._remember(conn, request.operation_id, payload, existing)
            # User/LLM labels cannot cause quarantine; reproduce a hard failure ourselves.
            from .validation import hard_failures
            failures = hard_failures(self, conn, rev)
            hard = request.issue_type in HARD and any(f['type'] == request.issue_type for f in failures)
            current = get(conn, 'status', request.target.key) or {}
            availability = 'quarantined' if hard else ('needs_review' if request.issue_type in ('scope', 'gap', 'structure') else 'disputed')
            if current.get('availability') in BLOCKED:
                availability = current['availability']
            issue = {**payload, 'id': iid, 'company': rev['company'], 'state': 'open',
                'created_at': utcnow(), 'policy': self._policy(conn), 'confirmed_hard_error': hard,
                'reproduced_failures': failures, 'previous_status': current, 'content_resolution': '',
                'impacts': self._downstream(conn, request.target.key)}
            self._emit(conn, rev['company'], 'issue.opened', [change('issues', iid, issue),
                change('status', request.target.key, {**current, 'availability': availability,
                                                     'reason': request.description})])
            self._propagate(conn, request.target.key, '上游知识存在待处理问题')
            return self._remember(conn, request.operation_id, payload, issue)

    def issue_decision(self, iid, request: IssueDecision, actor='human'):
        if actor != 'human':
            raise PermissionError('问题处理决定需要人工确认')
        with self.store.connect(write=True) as db:
            payload = [iid, request.model_dump(mode='json')]
            cached = self._cached(db, request.operation_id, payload)
            if cached:
                return cached
            issue = get(db, 'issues', iid)
            if not issue or issue['state'] != 'open':
                raise Conflict('问题不存在或已经关闭')
            key = refkey(issue['target'])
            status = get(db, 'status', key)
            updates = []
            if request.action == 'impact':
                if request.target not in issue['impacts'] or not request.disposition:
                    raise ValueError('请选择影响对象与处理决定')
                if request.disposition in ('revised', 'withdrawn'):
                    affected = get(db, 'status', request.target)
                    if affected:
                        expected = ('superseded',) if request.disposition == 'revised' else ('withdrawn',)
                        if affected['availability'] not in expected:
                            raise Conflict('请先完成该下游版本的审核修订或撤回')
                    else:
                        raise Conflict('历史研究产物保留原件，请记录复核结论或不适用理由')
                issue['impacts'][request.target]['decision'] = {'disposition': request.disposition, 'reason': request.reason}
                if request.disposition in ('reviewed_unchanged', 'not_applicable'):
                    target_status = get(db, 'status', request.target)
                    other_causes = [i for i in state(db, 'issues').values() if i['id'] != iid and i['state'] == 'open' and (refkey(i['target']) == request.target or request.target in i['impacts'])]
                    if target_status and target_status['availability'] == 'needs_review' and not other_causes:
                        updates.append(change('status', request.target, {**target_status, 'availability': 'available', 'reason': request.reason}))
            elif request.action == 'dismiss':
                target_revision=get(db,'revisions',key)
                current_sources=state(db,'sources')
                if any(current_sources.get(c['source_id'],{}).get('state')!='available' for c in target_revision.get('citations',[])):
                    raise Conflict('依据仍已修订或撤回；需要新版本或保留待复核状态')
                from .validation import hard_failures
                if hard_failures(self, db, get(db, 'revisions', key)):
                    raise Conflict('确定性校验仍失败，不能关闭为误报')
                others = [i for i in state(db, 'issues').values() if i['id'] != iid and i['state'] == 'open' and refkey(i['target']) == key]
                if not others and status['availability'] not in ('superseded', 'withdrawn'):
                    updates.append(change('status', key, issue['previous_status']))
                issue.update(state='closed', content_resolution='false_alarm')
                # False-alarm disposition is explicit for every downstream item.
                for impact_ref, impact in issue['impacts'].items():
                    impact_status = get(db, 'status', impact_ref)
                    other_causes = [i for i in state(db, 'issues').values() if i['id'] != iid and i['state'] == 'open' and (refkey(i['target']) == impact_ref or impact_ref in i['impacts'])]
                    if impact_status and impact_status['availability'] == 'needs_review' and not other_causes and impact.get('previous_status'):
                        updates.append(change('status', impact_ref, impact['previous_status']))
                    impact['decision'] = {'disposition': 'not_applicable', 'reason': request.reason}
            elif request.action == 'withdraw':
                updates.append(change('status', key, {**status, 'availability': 'withdrawn', 'reason': request.reason}))
                issue['content_resolution'] = 'withdrawn_without_replacement'
            elif request.action == 'resolve':
                if status['availability'] not in BLOCKED or not issue['content_resolution']:
                    raise Conflict('旧版必须退出正常引用，且内容问题已有处理决定')
                if any(not v['decision'] for v in issue['impacts'].values()):
                    raise Conflict('仍有下游影响缺少处理决定')
                issue['state'] = 'closed'
            issue['updated_at'] = utcnow()
            issue.setdefault('decisions', []).append(request.model_dump(mode='json'))
            updates.append(change('issues', iid, issue))
            self._emit(db, issue['company'], 'issue.' + request.action, updates)
            return self._remember(db, request.operation_id, payload, issue)

    def history(self, object_id, as_of=None):
        with self.store.connect() as db:
            st = self._view_state(db, as_of)
            versions = [{**r, **st.get('status', {}).get(k, {})} for k, r in st.get('revisions', {}).items()
                        if r['id'] == object_id and (not as_of or r['published_at'] <= timestamp(as_of))]
            source_ids={c['source_id'] for r in versions for c in r.get('citations',[])}
            for proposal in st.get('proposals',{}).values():
                for draft in proposal['request']['changes']:
                    if draft['id']==object_id:source_ids.update(c['source_id'] for c in draft.get('citations',[]))
            events = []
            for event in db.execute('SELECT * FROM wiki_events ORDER BY sequence'):
                if as_of and event['occurred_at'] > timestamp(as_of):
                    continue
                payload = json.loads(self.objects.get(event['payload_object']))
                if any(c['key'].startswith(object_id + '@v') or c['value'].get('target', {}).get('id') == object_id
                       or (c['bucket']=='sources' and c['key'] in source_ids)
                       or any(d['id']==object_id for d in c['value'].get('request',{}).get('changes',[]))
                       or any(r['id']==object_id for r in c['value'].get('used',[])) for c in payload['changes']):
                    events.append({**dict(event), 'details': payload['details']})
            return {'versions': sorted(versions, key=lambda r: -r['version']), 'events': events}


    def validate_use(self, company, references, as_of=None):
        from .validation import hard_failures
        failures, checked, suspected = [], [], []
        with self.store.connect() as db:
            st=self._view_state(db,as_of)
            for reference in references:
                ref=Reference.model_validate(reference)
                rev=st.get('revisions',{}).get(ref.key)
                status=st.get('status',{}).get(ref.key,{})
                if not rev or rev['company']!=company or status.get('availability') in BLOCKED or (as_of and rev['published_at']>timestamp(as_of)):
                    failures.append({'ref':ref.key,'reason':'版本不可用、公司不匹配或超出时点'})
                    continue
                hard=hard_failures(self,db,rev)
                for error in hard:
                    failures.append({'ref':ref.key,'reason':error['detail']})
                    suspected.append((ref,error))
                if not hard:checked.append({'ref':ref.key,'availability':status.get('availability','needs_review'),'body_object':rev['body_object']})
        if not as_of:
            for ref,error in suspected:
                self.report(IssueInput(operation_id='validate:'+digest([ref.key,error]),target=ref,
                    issue_type=error['type'],description=error['detail'],discovered_by='rule'))
        return {'valid':not failures,'references':checked,'failures':failures,'as_of':as_of}

    def rebuild(self):
        with self.store.connect(write=True) as db:
            rebuilt = {}
            for event in db.execute('SELECT * FROM wiki_events ORDER BY sequence'):
                rebuilt = reduce_event(rebuilt, json.loads(self.objects.get(event['payload_object'])))
            db.execute('DELETE FROM wiki_state')
            for bucket, values in rebuilt.items():
                for key, value in values.items():
                    db.execute('INSERT INTO wiki_state VALUES(?,?,?)', (bucket, key, canonical(value)))
            db.execute('DELETE FROM wiki_vectors')
            from .search import rebuild_index
            rebuild_index(self, db)
        self.render()
        return {'revisions': len(rebuilt.get('revisions', {})), 'issues': len(rebuilt.get('issues', {})),
                'external_effects': 0, 'markdown': str(self.markdown)}

    def render(self):
        from .markdown import render
        return render(self)

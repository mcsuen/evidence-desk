"""One application service owns research commands for Web, CLI and channels."""
from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from pitr.domain.common import Conflict, Forbidden, canonical, digest, uid, utcnow, instant
from pitr.domain.contracts import (
    Subject, Ref, Scope, SourceVersion, Snapshot, CreateCase, ResearchInput,
    ResearchCase, Run, Budget, UpdateInput, StartRun, ContinueRun,
)
from pitr.domain.policy import source_allowed
from .store import Store


class Workstation:
    def __init__(self, root, *, runtime=True):
        self.root = Path(root).expanduser().resolve()
        self.store = Store(self.root)
        from pitr.integrations.slack.settings import SettingsFile
        self.settings = SettingsFile(self.root / 'private/settings.json')
        self.agents = None
        if runtime:
            from pitr.agent_runtime.runtime import AgentRuntime
            from pitr.adapters.runtime_context import RuntimeContext
            self.agents = AgentRuntime(RuntimeContext(self.root, self.store), self.settings)
        from .reports import Reports
        self.reports = Reports(self)
        self.tool_url = ''
        self.queue = None

    def import_source(self, raw, media, *, title='', url='', subjects=(), published_at=None,
                      operation_id=None, availability_basis='acquired', availability_evidence='',
                      trusted_availability=False, extend_subjects=False, db=None, _parsed=None):
        from pitr.adapters.originals import parse
        if published_at:
            instant(published_at)
        if availability_basis in ('archive', 'authoritative') and not trusted_availability:
            raise Forbidden('可得时间证明必须由受控获取适配器提供')
        if availability_basis != 'acquired' and (not published_at or not availability_evidence):
            raise ValueError('提供可得时间及证明依据')
        parsed = _parsed if _parsed is not None else parse(raw, media)
        sha = self.store.blob(raw)
        url = url or 'upload:' + sha
        sid = 'source_' + digest(url)[:24]
        observed = utcnow()

        def save(conn):
            row = conn.execute('SELECT revision FROM heads WHERE id=?', (sid,)).fetchone()
            previous = self.store.get(sid, 'source', db=conn) if row else None
            if previous and previous.digest == sha:
                if subjects and set(subjects) != set(previous.subjects):
                    if not extend_subjects:raise Conflict('同一原件的主体已登记；更改主体需明确修订')
                    if set(subjects).issubset(previous.subjects):return previous.model_dump(mode='json')
                else:return previous.model_dump(mode='json')
            bound_subjects=sorted(set(subjects)|set(previous.subjects)) if previous and extend_subjects else list(subjects)
            for subject in subjects:
                self.store.get(subject, 'subject', db=conn)
            hosts = {host for subject in subjects
                     for host in self.store.get(subject, 'subject', db=conn).official_domains}
            host = urlsplit(url).hostname or ''
            role = 'upload' if url.startswith('upload:') else 'official' if host in hosts else 'third_party'
            available = published_at if availability_basis != 'acquired' else observed
            source = SourceVersion(id=sid, revision=previous.revision+1 if previous else 1,
                created_at=observed, title=title or parsed['title'], url=url,
                media_type=parsed['media_type'], digest=sha, byte_count=len(raw), subjects=bound_subjects,
                blocks=parsed['blocks'], page_count=parsed['page_count'], published_at=published_at,
                observed_at=observed, available_at=available, availability_basis=availability_basis,
                availability_evidence=availability_evidence, origin_group=parsed['origin_group'],
                source_role=role, issues=parsed['issues'])
            self.store.put(conn, 'source', source)
            if previous:
                self.store.invalidate(conn, previous.ref, '同一来源已取得新版本', 'superseded')
            self.store.event(conn, '', 'source.imported', {'source': source.ref, 'digest': sha})
            return source.model_dump(mode='json')

        payload = {'command': 'source.import', 'sha': sha, 'url': url, 'subjects': list(subjects),
                   'title': title, 'published_at': published_at, 'basis': availability_basis,
                   'proof': availability_evidence,'extend_subjects':extend_subjects}
        return SourceVersion.model_validate(self.store.once(operation_id or uid('import'), payload, save, db=db))

    def fetch_source(self, url, *, subjects=(), title='', operation_id=None):
        from pitr.adapters.public_fetch import fetch_public
        from pitr.adapters.originals import parse
        operation_id=operation_id or uid('fetch')
        payload={'command':'source.fetch','url':url,'subjects':list(subjects),'title':title}
        with self.store.connect() as db:
            row=db.execute('SELECT digest,body FROM commands WHERE id=?',(operation_id,)).fetchone()
            if row:
                if row['digest']!=digest(payload):raise Conflict('此操作标识已用于不同请求')
                return SourceVersion.model_validate_json(row['body'])
        raw, media, final, receipts = fetch_public(url, contact=self.settings.read().get('sec_user_agent', ''))
        parsed=parse(raw,media)
        def save(db):
            source = self.import_source(raw, media, url=final, subjects=subjects, title=title, operation_id=uid('acquire'),db=db,_parsed=parsed)
            self.store.event(db, '', 'source.acquired', {'source': source.ref, 'receipts': receipts})
            return source.model_dump(mode='json')
        return SourceVersion.model_validate(self.store.once(operation_id,payload,save))

    def register_subject(self, operation_id, *, identity, name, aliases=(), official_domains=(),
                         identifiers=None, expected_revision=0, evidence=()):
        if not identity.strip() or len(identity) > 100:
            raise ValueError('主体标识须非空且不超过 100 个字符')
        identity = identity.upper().strip()
        for host in official_domains:
            from pitr.adapters.public_fetch import public_url
            public_url('https://' + host, resolve=False)
        payload = dict(identity=identity, name=name, aliases=list(aliases), official_domains=list(official_domains),
                       identifiers=identifiers, expected_revision=expected_revision, evidence=list(evidence))
        def save(db):
            refs = [Ref.model_validate(r) for r in evidence]
            for ref in refs:
                self.store.get(ref, 'evidence', db=db)
            # Human registration is explicit, and never represented as regulator verification.
            subject = Subject(id=identity, revision=expected_revision+1, created_at=utcnow(),
                name=name, aliases=list(aliases), official_domains=list(official_domains),
                identifiers=identifiers or {}, status='manual', evidence=refs)
            return self.store.put(db, 'subject', subject, expected=expected_revision,
                                  dependencies=refs).model_dump(mode='json')
        return self.store.once(operation_id, {'command': 'subject.register', **payload}, save)

    def source_list(self, scope=None,all_revisions=False):
        scope = scope or Scope()
        result = []
        with self.store.connect() as db:
            for source in self.store.list('source', db=db, all_revisions=all_revisions or scope.mode == 'historical'):
                try:
                    source_allowed(source, scope)
                except Forbidden:
                    continue
                current = self.store.validity(source.ref, db=db)
                if current['status'] == 'withdrawn' and not all_revisions and scope.mode!='historical':
                    continue
                result.append({**source.model_dump(mode='json'), 'current_validity': current})
        return result

    def withdraw_source(self, ref, operation_id, reason):
        ref = Ref.model_validate(ref)
        if not reason.strip():
            raise ValueError('说明撤回原因')
        def save(db):
            self.store.get(ref, 'source', db=db)
            affected = self.store.invalidate(db, ref, reason, 'withdrawn')
            self.store.event(db, '', 'source.withdrawn', {'source': ref, 'reason': reason, 'affected': affected})
            return {'affected': affected}
        return self.store.once(operation_id, {'command': 'source.withdraw', 'source': ref, 'reason': reason}, save)

    def _validate_input(self, db, request):
        for subject in request.scope.subjects:
            self.store.get(subject, 'subject', db=db)
        for ref in request.sources:
            source = self.store.get(ref, 'source', db=db)
            source_allowed(source, request.scope)
            if request.scope.mode!='historical' and self.store.validity(ref, db=db)['status'] != 'available':
                raise ValueError('输入来源已更新或撤回，请选择有效版本')
        for ref in request.knowledge:
            self.require_knowledge(ref, request.scope, db=db)

    def create_case(self, request: CreateCase):
        request = CreateCase.model_validate(request)
        def save(db):
            self._validate_input(db, request)
            context = {}
            if request.parent_case_id:
                self.get_case(request.parent_case_id, db=db)
            if request.news_draft_id:
                from pitr.lab.news.service import News
                draft = News(self).get_draft(request.news_draft_id)
                context['news_origin'] = draft.context['news_origin']
                context['news_origin']['experimental'] = True
            now, cid = utcnow(), uid('case')
            input = ResearchInput(id=uid('input'), created_at=now,
                **request.model_dump(exclude={'operation_id', 'parent_case_id', 'news_draft_id'}), context=context)
            self.store.put(db, 'input', input, dependencies=[*input.sources, *input.knowledge])
            case = ResearchCase(id=cid, title=request.question[:120], input=input,
                                parent_case_id=request.parent_case_id, created_at=now, updated_at=now)
            db.execute('INSERT INTO cases VALUES(?,?)', (cid, canonical(case)))
            return case.model_dump(mode='json')
        return self.store.once(request.operation_id, {'command': 'case.create', 'request': request}, save)

    def get_case(self, case_id, *, db=None):
        if db is None:
            with self.store.connect() as conn:
                return self.get_case(case_id, db=conn)
        row = db.execute('SELECT body FROM cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise KeyError('研究问题不存在')
        return ResearchCase.model_validate_json(row[0])

    def cases(self):
        with self.store.connect() as db:
            return [ResearchCase.model_validate_json(r[0]) for r in db.execute('SELECT body FROM cases ORDER BY rowid DESC')]

    def update_input(self, case_id, request: UpdateInput):
        request = UpdateInput.model_validate(request)
        cancelled = []
        def save(db):
            case = self.get_case(case_id, db=db)
            if request.expected_revision != case.input.revision:
                raise Conflict('研究输入已变化，请刷新后补充')
            self._validate_input(db, request)
            changed_scope = request.scope.model_dump() != case.input.scope.model_dump()
            input = ResearchInput(id=case.input.id, revision=case.input.revision+1, created_at=utcnow(),
                **request.model_dump(exclude={'operation_id', 'expected_revision', 'parent_case_id', 'news_draft_id'}),
                context={**case.input.context, 'scope_changed': changed_scope})
            self.store.put(db, 'input', input, dependencies=[*input.sources, *input.knowledge], expected=case.input.revision)
            case = case.model_copy(update={'input': input, 'title': request.question[:120], 'updated_at': utcnow()})
            db.execute('UPDATE cases SET body=? WHERE id=?', (canonical(case), case_id))
            for row in db.execute("SELECT body FROM runs WHERE case_id=? AND status IN ('queued','running')", (case_id,)):
                run = Run.model_validate_json(row[0])
                run.status, run.stage, run.updated_at = 'cancelled', 'input_revised', utcnow()
                self.save_run(db, run)
                db.execute('UPDATE grants SET active=0 WHERE run_id=?', (run.id,))
                cancelled.append(run.id)
            return case.model_dump(mode='json')
        result = self.store.once(request.operation_id, {'command': 'case.update', 'case_id': case_id, 'request': request}, save)
        if self.agents:
            for rid in cancelled:
                self.agents.cancel(rid)
        return result

    def budget(self, depth):
        # Standard starts from the public PDD demo's explicit 30 minute / 180 call limit.
        # Evaluation can replace these provisional values using successful-sample P90 * 1.5.
        defaults = {'interactive': (300, 30), 'standard': (1800, 180), 'deep': (5400, 600)}
        calibrated = self.store.setting('budgets', {}).get(depth)
        if calibrated:
            return Budget.model_validate(calibrated)
        seconds, calls = defaults[depth]
        return Budget(active_seconds=seconds, tool_calls=calls)

    def start_run(self, case_id, request: StartRun, *, binding=None):
        request = StartRun.model_validate(request)
        payload = {'command': 'run.start', 'case_id': case_id, 'request': request}
        with self.store.connect() as db:
            cached=db.execute('SELECT digest,body FROM commands WHERE id=?',(request.operation_id,)).fetchone()
            if cached:
                if cached['digest'] != digest(payload):raise Conflict('此操作标识已用于不同请求')
                return json.loads(cached['body'])
        case = self.get_case(case_id)
        if binding is None:
            if not self.agents:
                raise ValueError('Agent 尚未启用；研究问题已保存')
            binding = self.agents.selection(case.input.agent_provider, case.input.model, case.input.reasoning)
        def save(db):
            case = self.get_case(case_id, db=db)
            if request.expected_revision != case.input.revision:
                raise Conflict('研究输入已变化')
            self._validate_input(db, case.input)
            if db.execute("SELECT 1 FROM runs WHERE case_id=? AND status IN ('queued','running')", (case_id,)).fetchone():
                raise Conflict('这个研究已有正在执行的任务')
            reused=[]
            available={r.key for r in case.input.sources}
            previous=db.execute('SELECT id FROM runs WHERE case_id=? ORDER BY rowid DESC LIMIT 1',(case_id,)).fetchone()
            if previous:
                for row in db.execute('SELECT id,revision FROM run_objects WHERE run_id=?',(previous['id'],)):
                    candidate=Ref(id=row[0],revision=row[1]);obj=self.store.get(candidate,db=db)
                    if type(obj).__name__ not in ('Value','EvidenceAnchor','Observation','Calculation','Assertion','ModelRevision'):continue
                    if self.store.validity(candidate,db=db)['status']!='available':continue
                    if any(isinstance(o,SourceVersion) and o.ref.key not in available for o in self.store.closure(candidate,db=db)):continue
                    reused.append(candidate)
            snapshot = Snapshot(id=uid('snapshot'), created_at=utcnow(), scope=case.input.scope,
                                sources=case.input.sources, knowledge=case.input.knowledge,reused=reused,
                                subject_versions=[self.store.get(s,'subject',db=db).ref for s in case.input.scope.subjects])
            self.store.put(db, 'snapshot', snapshot, dependencies=[*snapshot.sources, *snapshot.knowledge,*snapshot.reused,*snapshot.subject_versions])
            checkpoint={'reuse':{'objects':len(reused),'previous_run':previous['id'] if previous else None}}
            run = Run(id=uid('run'), case_id=case_id, input_revision=case.input.revision,
                snapshot=snapshot.ref, status='queued', stage='queued', agent=binding,
                lane=binding['provider'], budget=self.budget(case.input.depth),checkpoint=checkpoint,created_at=utcnow(), updated_at=utcnow())
            db.execute('INSERT INTO runs(id,case_id,status,lane,generation,body) VALUES(?,?,?,?,?,?)',
                       (run.id, case_id, run.status, run.lane, 0, canonical(run)))
            self.store.event(db, run.id, 'run.queued', {'input': case.input.ref, 'snapshot': snapshot.ref})
            return run.model_dump(mode='json')
        return self.store.once(request.operation_id, payload, save)

    def get_run(self, run_id, *, db=None):
        if db is None:
            with self.store.connect() as conn:
                return self.get_run(run_id, db=conn)
        row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise KeyError('执行不存在')
        return Run.model_validate_json(row[0])

    def runs(self, case_id=None):
        with self.store.connect() as db:
            return [Run.model_validate_json(r[0]) for r in db.execute(
                'SELECT body FROM runs WHERE (? IS NULL OR case_id=?) ORDER BY rowid DESC', (case_id, case_id))]

    def save_run(self, db, run):
        db.execute('UPDATE runs SET status=?,lane=?,generation=?,body=? WHERE id=?',
                   (run.status, run.lane, run.generation, canonical(run), run.id))

    def fence(self, db, run_id, generation, *, owner=None):
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row or row['status'] != 'running' or row['generation'] != generation or (row['lease_until'] or 0) < time.time() or (owner and row['owner'] != owner):
            raise Forbidden('执行已取消、租约已转移或执行代次过期')
        run = Run.model_validate_json(row['body'])
        if self.get_case(run.case_id, db=db).input.revision != run.input_revision:
            raise Forbidden('执行输入已过期')
        return run

    def cancel(self, run_id, operation_id):
        def save(db):
            run = self.get_run(run_id, db=db)
            if run.status not in ('completed', 'cancelled'):
                run.status, run.updated_at = 'cancelled', utcnow()
                self.save_run(db, run)
                db.execute('UPDATE grants SET active=0 WHERE run_id=?', (run_id,))
                self.store.event(db, run_id, 'run.cancelled', {})
            return run.model_dump(mode='json')
        result = self.store.once(operation_id, {'command': 'run.cancel', 'run_id': run_id}, save)
        if self.agents:
            self.agents.cancel(run_id)
        return result

    def continue_run(self, run_id, request: ContinueRun):
        request=ContinueRun.model_validate(request)
        def save(db):
            run = self.get_run(run_id, db=db)
            if run.generation != request.expected_generation:
                raise Conflict('执行代次已变化')
            partial_completed = run.status=='completed' and run.report and self.reports.view(run.report).delivery!='ready'
            if run.status not in ('budget_exhausted', 'failed', 'waiting_user', 'cancelled') and not partial_completed:
                raise Conflict('此执行不能继续')
            if self.get_case(run.case_id, db=db).input.revision != run.input_revision:
                raise Conflict('输入已修改，请从新输入发起执行')
            if db.execute("SELECT 1 FROM runs WHERE case_id=? AND id!=? AND status IN ('queued','running')", (run.case_id,run.id)).fetchone():
                raise Conflict('这个研究已有正在执行的任务')
            run.budget.active_seconds += request.additional_seconds
            run.budget.tool_calls += request.additional_calls
            run.checkpoint={**run.checkpoint,'continuation_instruction':request.instruction}
            run.status, run.stage, run.error, run.updated_at = 'queued', 'resuming', '', utcnow()
            self.save_run(db, run)
            self.store.event(db, run.id, 'run.continued', request.model_dump())
            return run.model_dump(mode='json')
        return self.store.once(request.operation_id, {'command': 'run.continue', 'run_id': run_id, 'request': request}, save)

    def require_knowledge(self, ref, scope, *, db):
        value = self.store.get(ref, db=db)
        accepted = self._accepted(scope,db)
        if accepted.get(value.id) != value.revision:
            raise Forbidden('只可引用已采纳的准确知识版本')
        if scope.mode != 'historical' and self.store.validity(value.ref, db=db)['status'] != 'available':
            raise Forbidden('此判断已有待复核事项')
        for item in self.store.closure(value.ref, db=db):
            if isinstance(item, SourceVersion):
                source_allowed(item, scope)
        return value

    def _accepted(self, scope, db):
        if scope.mode != 'historical':
            return {r[0]:r[1] for r in db.execute('SELECT id,revision FROM accepted')}
        accepted={}
        for (body,) in db.execute("SELECT body FROM revisions WHERE kind='decision' ORDER BY rowid"):
            decision=json.loads(body)
            if decision['action']=='adopt' and instant(decision['created_at'])<=instant(scope.as_of):
                for ref in decision['targets']:accepted[ref['id']]=ref['revision']
        return accepted

    def knowledge(self, scope=None):
        scope = scope or Scope()
        result = []
        with self.store.connect() as db:
            for identity,revision in self._accepted(scope,db).items():
                ref = Ref(id=identity, revision=revision)
                value = self.store.get(ref, db=db)
                if scope.subjects and not set(scope.subjects).intersection(getattr(value, 'subjects', [])):
                    continue
                try:
                    for item in self.store.closure(ref, db=db):
                        if isinstance(item, SourceVersion):
                            source_allowed(item, scope)
                except Forbidden:
                    continue
                result.append({**value.model_dump(mode='json'), 'current_validity': self.store.validity(ref, db=db)})
        return result

    def search(self, query, scope=None):
        import jieba
        scope = scope or Scope()
        words = [w for w in jieba.cut(query) if w.strip()]
        if not words:
            return []
        expression = ' OR '.join('"' + w.replace('"', '""') + '"' for w in words[:30])
        visible = {f"{r['id']}@{r['revision']}": r for r in [*self.source_list(scope), *self.knowledge(scope)]}
        with self.store.connect() as db:
            rows = db.execute('SELECT id,revision,kind,title,snippet(search,4,\'\',\'\',\'…\',32) AS snippet '
                              'FROM search WHERE search MATCH ? ORDER BY rank', (expression,))
            return [dict(r) for r in rows if f"{r['id']}@{r['revision']}" in visible][:80]

    def trace(self, run_id, after=0):
        self.get_run(run_id)
        with self.store.connect() as db:
            return [{'seq': r['seq'], 'at': r['at'], 'kind': r['kind'], 'data': json.loads(r['body'])}
                    for r in db.execute('SELECT * FROM trace WHERE run_id=? AND seq>? ORDER BY seq LIMIT 300', (run_id, after))]

"""Capability-scoped tools. Agents can propose research; only the controller commits delivery."""
from __future__ import annotations

import json
import secrets
from typing import Literal
from pydantic import Field

from pitr.domain.common import Contract, Conflict, Forbidden, BudgetExhausted, canonical, digest, uid, utcnow
from pitr.domain.contracts import (
    Ref, ToolRequest, SourceVersion, Snapshot, EvidenceAnchor, Observation, Value,
    Calculation, Assertion, ModelRevision, ReportDocument, Paragraph, Section,
)
from pitr.domain.numbers import parse_literal, locate, conversion, calculate, UNITS

Unit = Literal[tuple(UNITS)]
from pitr.domain.policy import source_allowed


class Empty(Contract):
    pass


class Read(Contract):
    ref: Ref


class SourceRead(Read):
    block_id: str = ''
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=18000, ge=1, le=30000)


class SourceSearch(Contract):
    query: str = Field(min_length=1, max_length=500)


class SourceFetch(Contract):
    url: str
    title: str = ''
    subjects: list[str] = Field(default_factory=list)


class SourcePage(Read):
    page: int = Field(ge=1)


class Quote(Contract):
    source: Ref
    block_id: str
    quote: str = Field(min_length=1, max_length=30000)
    start: int | None = Field(default=None, ge=0)


class Bind(Contract):
    evidence: Ref
    literal: str
    start: int | None = None
    metric: str
    subject: str
    period: str
    original_unit: Unit
    unit: Unit
    unit_evidence: Ref
    period_evidence: Ref
    basis_evidence: Ref
    basis: str
    frequency: Literal['quarter', 'annual', 'ytd', 'point']
    currency: str = ''
    share_basis: str = ''
    role: Literal['actual', 'guidance', 'broker_forecast', 'consensus'] = 'actual'
    precision: int = Field(default=3, ge=0, le=8)
    table: dict = Field(default_factory=dict)


class Assume(Contract):
    metric: str
    amount: str
    unit: Unit
    subject: str
    period: str
    basis: str
    frequency: Literal['quarter', 'annual', 'ytd', 'point']
    currency: str = ''
    share_basis: str = ''
    precision: int = Field(default=3, ge=0, le=8)
    reason: str = Field(min_length=1)
    dependencies: list[Ref] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class Compute(Contract):
    operation: Literal['add', 'subtract', 'multiply', 'divide', 'ratio', 'growth', 'change', 'quarterize']
    inputs: list[Ref] = Field(min_length=2, max_length=2)
    metric: str
    precision: int = Field(default=3, ge=0, le=8)


class Claim(Contract):
    id: str | None = None
    expected_revision: int = Field(default=0, ge=0)
    title: str
    statement: str
    kind: Literal['source_statement', 'fact', 'interpretation', 'forecast', 'relationship']
    subjects: list[str] = Field(default_factory=list)
    support: list[Ref] = Field(min_length=1)
    counterevidence: list[Ref] = Field(default_factory=list)
    values: list[Ref] = Field(default_factory=list)
    depends_on: list[Ref] = Field(default_factory=list)
    alternative: str = ''
    limitations: list[str] = Field(default_factory=list)
    next_check: str = ''
    relation: dict = Field(default_factory=dict)


class Model(Contract):
    id: str | None = None
    expected_revision: int = Field(default=0, ge=0)
    title: str
    subjects: list[str]
    assumptions: list[Ref]
    outputs: list[Ref]
    rationale: str


class Report(Contract):
    title: str
    summary: list[Paragraph]
    sections: list[Section]
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    assertions: list[Ref] = Field(default_factory=list)
    models: list[Ref] = Field(default_factory=list)
    change_reason: str = ''


class Checkpoint(Contract):
    summary: str
    next_actions: list[str]
    refs: list[Ref] = Field(default_factory=list)


class Skill(Contract):
    name: str
    reason: str = Field(min_length=1)


CATALOG = {
    'context': (Empty, '读取固定输入、预算、检查点及本次对象目录'),
    'object.read': (Read, '读取范围内的准确修订'),
    'source.read': (SourceRead, '按块与字符窗口读取原件文字，文本不等于已目视检查'),
    'source.search': (SourceSearch, '检索本次快照的原件文字'),
    'source.discover': (SourceSearch, '通过真实公开检索发现原件网址，仅返回待核查线索；历史范围禁止'),
    'source.fetch': (SourceFetch, '获取公开 URL 的不可变原件并扩展本次快照'),
    'source.tables': (SourcePage, '读取 PDF 表格与定位框；提取失败须标记缺项'),
    'source.page': (SourcePage, '渲染 PDF 页并返回可读取的临时图片地址'),
    'evidence.quote': (Quote, '从原件建立精确引用，重复出现时提供起点'),
    'value.bind': (Bind, '从精确原文解析数值并按明确单位换算，不能传入计算结果'),
    'value.assume': (Assume, '记录带理由、依赖与限制的模型假设，不能冒充实际披露'),
    'value.calculate': (Compute, '使用受控 Decimal 计算、口径与量纲校验'),
    'assertion.propose': (Claim, '提出判断；关系成熟度须依据关系语义，不能依据来源身份'),
    'model.propose': (Model, '固定模型假设、输出和理由'),
    'report.save': (Report, '保存类型化报告；数值和引用使用对象引用，提交不等于通过复核'),
    'checkpoint.save': (Checkpoint, '保存可恢复的工作进度'),
    'skill.load': (Skill, '按需加载方法包，固定版本与选择理由'),
    'reference.load': (Skill, '按需加载有来源的公司阅读参考；不能作为本次证据或替代原件'),
}
READ_TOOLS = {'context', 'object.read', 'source.read', 'source.search', 'source.tables', 'source.page', 'skill.load', 'reference.load'}
FINISH_TOOLS = {'context', 'object.read', 'assertion.propose', 'model.propose', 'report.save', 'checkpoint.save'}


class ToolService:
    def __init__(self, station):
        self.station, self.store = station, station.store

    def catalog(self, role='researcher'):
        return [{'name': name, 'description': description, 'input': model.model_json_schema(mode='validation')}
                for name, (model, description) in CATALOG.items() if role == 'researcher' or name in READ_TOOLS]

    def issue(self, run_id, generation, role='researcher', report=None, parent_span=None):
        if role not in ('researcher', 'reviewer'):
            raise ValueError('未知工具角色')
        token = secrets.token_urlsafe(40)
        with self.store.connect(write=True) as db:
            run = self.station.fence(db, run_id, generation)
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)', (digest(token.encode()), run_id, generation,
                run.input_revision, role, 1, canonical({'report': report, 'parent_span': parent_span})))
        return token

    def revoke(self, token):
        with self.store.connect(write=True) as db:
            db.execute('UPDATE grants SET active=0 WHERE token_hash=?', (digest(token.encode()),))

    def authenticate(self, db, token):
        row = db.execute('SELECT * FROM grants WHERE token_hash=?', (digest(token.encode()),)).fetchone()
        if not row or not row['active']:
            raise Forbidden('工具凭据已失效')
        run = self.station.fence(db, row['run_id'], row['generation'])
        if run.input_revision != row['input_revision']:
            raise Forbidden('工具凭据的输入修订已过期')
        return run, dict(row)

    def allowed(self, db, run, ref, kind=None):
        ref = Ref.model_validate(ref)
        self.station.reports._owned(db, run, ref)
        value = self.store.get(ref, kind, db=db)
        snapshot = self.store.get(run.snapshot, 'snapshot', db=db)
        for item in self.store.closure(ref, db=db):
            if isinstance(item, SourceVersion):
                source_allowed(item, snapshot.scope)
                if snapshot.scope.mode!='historical' and self.store.validity(item.ref, db=db)['status'] != 'available':
                    raise Conflict('引用依赖的来源已经更新或撤回')
        return value

    def call(self, token, request):
        from .trace import span
        request = ToolRequest.model_validate(request)
        # A known capability permits audit attribution, never a business write.
        with self.store.connect() as db:
            grant = db.execute('SELECT * FROM grants WHERE token_hash=?', (digest(token.encode()),)).fetchone()
            if not grant:
                return self._call(token, request)
            run = self.station.get_run(grant['run_id'], db=db)
            run.generation = grant['generation']
            run.input_revision = grant['input_revision']
            context = json.loads(grant['body'])
        with span(self.store, run, request.name, 'tool', parent_id=context.get('parent_span'),
                  operation_id=request.operation_id, arguments=request.arguments, role=grant['role']) as (identity, outcome):
            try:
                result = self._call(token, request, identity)
                if isinstance(result, dict):
                    outcome['artifact_refs'] = [dict(id=result['id'], revision=result['revision'])] if 'id' in result and 'revision' in result else []
                    if isinstance(result.get('report'), dict):outcome['artifact_refs'].append(result['report'])
                return result
            except Forbidden:
                outcome['status'] = 'interrupted'
                outcome['rejected'] = True
                raise

    def _call(self, token, request, trace_id=None):
        request = ToolRequest.model_validate(request)
        if request.name not in CATALOG:
            raise ValueError('未知工具')
        args = CATALOG[request.name][0].model_validate(request.arguments)
        acquired = None
        # Network reads happen outside the transaction; the final write is fenced again.
        if request.name in ('source.fetch','source.discover','source.page','source.tables'):
            with self.store.connect() as db:
                run, grant = self.authenticate(db, token)
                self._permit(db, run, grant, request.name)
                if request.name=='source.fetch':self._fetch_scope(db, run, args)
                if request.name in ('source.page','source.tables'):
                    source=self.allowed(db,run,args.ref,'source')
                    if source.media_type!='application/pdf' or args.page>source.page_count:raise ValueError('请指定 PDF 中存在的页码')
                cached = db.execute('SELECT digest,body FROM commands WHERE id=?', (request.operation_id,)).fetchone()
                payload = {'tool': request, 'run': run.id, 'generation': run.generation, 'role': grant['role']}
                if cached:
                    if cached['digest'] != digest(payload):
                        raise Conflict('此操作标识已用于不同请求')
                    return json.loads(cached['body'])
                if run.tool_calls >= int(run.budget.tool_calls*(1-run.budget.reserve_fraction)):
                    raise BudgetExhausted('研究工具预算已到收尾阈值，请保存已有成果')
            if request.name=='source.fetch':
                from pitr.adapters.public_fetch import fetch_public
                from pitr.adapters.originals import parse
                fetched = fetch_public(args.url, contact=self.station.settings.read().get('sec_user_agent', ''))
                acquired=(*fetched,parse(fetched[0],fetched[1]))
            elif request.name=='source.discover':
                from pitr.research.discovery import search
                def fence():
                    with self.store.connect() as conn:self.authenticate(conn,token)
                acquired=search(self.station,run,args.query,fence)
            else:
                from pitr.adapters.originals import tables,render_page
                import base64
                raw=self.store.read_blob(source.digest)
                acquired={'source':source.ref,'page':args.page}
                if request.name=='source.tables':acquired['tables']=tables(raw,args.page)
                else:acquired.update(png_base64=base64.b64encode(render_page(raw,args.page)).decode(),read_kind='page_image',note='渲染不等于已目视理解；引用须准确文字锚点')
        with self.store.connect(write=True) as db:
            run, grant = self.authenticate(db, token)
            # Scope and role checks precede the idempotency cache on every request.
            self._permit(db, run, grant, request.name)
            payload = {'tool': request, 'run': run.id, 'generation': run.generation, 'role': grant['role']}
            def invoke(conn):
                reserve = run.budget.reserve_fraction if request.name not in FINISH_TOOLS else 0
                if run.tool_calls >= int(run.budget.tool_calls*(1-reserve)):
                    raise BudgetExhausted('研究工具预算已到收尾阈值；保存部分报告与检查点后结束，等待显式继续')
                run.tool_calls += 1
                result = self._dispatch(conn, run, grant, request.name, args, acquired)
                self.station.fence(conn, run.id, run.generation)
                self.station.save_run(conn, run)
                self.store.event(conn, run.id, 'tool.called', {'name': request.name, 'operation_id': request.operation_id,
                    'arguments': request.arguments, 'result': result, 'generation': run.generation, 'role': grant['role'], 'span_id': trace_id})
                return result
            def check_refs(value):
                if isinstance(value,dict):
                    if set(value)=={'id','revision'}:self.allowed(db,run,Ref.model_validate(value))
                    else:
                        for item in value.values():check_refs(item)
                elif isinstance(value,list):
                    for item in value:check_refs(item)
            check_refs(request.arguments)
            return self.store.once(request.operation_id, payload, invoke, db=db)

    def _permit(self, db, run, grant, name):
        if grant['role'] != 'researcher' and name not in READ_TOOLS:
            raise Forbidden('独立复核只能读取原件和判断，不能修改研究')
        if name in ('source.fetch','source.discover') and not self.store.get(run.snapshot, 'snapshot', db=db).scope.allow_public_search:
            raise Forbidden('本次执行禁止获取范围外的新来源')

    def _fetch_scope(self, db, run, args):
        scope = self.store.get(run.snapshot, 'snapshot', db=db).scope
        if scope.subjects and not set(args.subjects).issubset(scope.subjects):
            raise Forbidden('获取来源的主体超出本次范围')

    def put(self, db, run, kind, value, dependencies=(), expected=None):
        for ref in dependencies:
            self.allowed(db, run, ref)
        self.store.put(db, kind, value, dependencies=dependencies, expected=expected)
        db.execute('INSERT OR IGNORE INTO run_objects VALUES(?,?,?)', (run.id, value.id, value.revision))
        return value.model_dump(mode='json')

    def _dispatch(self, db, run, grant, name, args, acquired=None):
        snapshot = self.store.get(run.snapshot, 'snapshot', db=db)
        if name=='source.discover':return acquired
        if name == 'context':
            case = self.station.get_case(run.case_id, db=db)
            owned = [self.store.get(Ref(id=r[0], revision=r[1]), db=db) for r in db.execute(
                'SELECT id,revision FROM run_objects WHERE run_id=?', (run.id,))]
            changed=[]
            for row in db.execute("SELECT DISTINCT o.id,o.revision FROM run_objects o JOIN runs r ON r.id=o.run_id WHERE r.case_id=?",(run.case_id,)):
                ref=Ref(id=row[0],revision=row[1]);obj=self.store.get(ref,db=db)
                if isinstance(obj,(Assertion,ModelRevision)) and self.store.validity(ref,db=db)['status']!='available' and self.store.get(obj.id,db=db).revision==obj.revision:
                    changed.append({'ref':ref,'title':obj.title,'reason':self.store.validity(ref,db=db)['reason']})
            from pitr.skills.library import references
            return {'input': case.input, 'snapshot': snapshot, 'run': run,'changed_judgments':changed,
                'reference_packages':[{'name':p['name'],'title':p['title'],'version':p['version']} for p in references(snapshot.scope.subjects)],
                'subjects':[self.store.get(r,'subject',db=db) for r in snapshot.subject_versions],
                'reused_objects':[{'ref':r,'type':type(self.store.get(r,db=db)).__name__} for r in snapshot.reused],
                'objects': [{'ref': o.ref, 'type': type(o).__name__, 'title': getattr(o, 'title', getattr(o, 'metric', ''))} for o in owned],
                'review_report': json.loads(grant['body']).get('report')}
        if name == 'object.read':
            return self.allowed(db, run, args.ref).model_dump(mode='json')
        if name == 'source.read':
            source = self.allowed(db, run, args.ref, 'source')
            selected = [b for b in source.blocks if not args.block_id or b.id == args.block_id]
            if args.block_id and not selected:
                raise KeyError('原件块不存在')
            if not args.block_id:
                return {'source': source.ref, 'title': source.title, 'issues': source.issues,
                    'blocks': [{'id': b.id, 'page': b.page, 'characters': len(b.text), 'preview': b.text[:300]} for b in selected]}
            block = selected[0]
            return {'source': source.ref, 'block_id': block.id, 'page': block.page, 'offset': args.offset,
                'text': block.text[args.offset:args.offset+args.limit], 'total': len(block.text), 'read_kind': 'extracted_text'}
        if name == 'source.search':
            hits = []
            for ref in snapshot.sources:
                source = self.allowed(db, run, ref, 'source')
                for block in source.blocks:
                    offset = block.text.casefold().find(args.query.casefold())
                    if offset >= 0:
                        start = max(0, offset-300)
                        hits.append({'source': ref, 'block_id': block.id, 'offset': start, 'text': block.text[start:offset+2000]})
            return {'hits': hits[:30]}
        if name == 'source.fetch':
            self._fetch_scope(db, run, args)
            raw, media, final, receipts,parsed = acquired
            source = self.station.import_source(raw, media, title=args.title, url=final, subjects=args.subjects,
                operation_id=uid('acquired'), db=db,_parsed=parsed)
            if source.ref not in snapshot.sources:
                updated = snapshot.model_copy(update={'revision': snapshot.revision+1, 'created_at': utcnow(),
                    'sources': [r for r in snapshot.sources if r.id != source.id] + [source.ref]})
                self.store.put(db, 'snapshot', updated, dependencies=[*updated.sources, *updated.knowledge,*updated.reused,*updated.subject_versions])
                run.snapshot = updated.ref
            return {'source': source.ref, 'title': source.title, 'receipts': receipts, 'snapshot': run.snapshot}
        if name in ('source.tables', 'source.page'):
            source = self.allowed(db, run, args.ref, 'source')
            if source.media_type != 'application/pdf' or args.page > source.page_count:
                raise ValueError('请指定 PDF 中存在的页码')
            return acquired
        if name == 'evidence.quote':
            source = self.allowed(db, run, args.source, 'source')
            block = next((b for b in source.blocks if b.id == args.block_id), None)
            if not block:
                raise KeyError('原件块不存在')
            starts = [i for i in range(len(block.text)) if block.text.startswith(args.quote, i)]
            start = args.start if args.start is not None else starts[0] if len(starts) == 1 else None
            if start not in starts:
                raise ValueError('引文不完全匹配，或需要指定重复引文的准确位置')
            value = EvidenceAnchor(id=uid('evidence'), created_at=utcnow(), source=source.ref,
                block_id=block.id, start=start, end=start+len(args.quote), quote=args.quote, page=block.page, bbox=block.bbox)
            return self.put(db, run, 'evidence', value, [source.ref])
        if name == 'value.bind':
            evidence = self.allowed(db, run, args.evidence, 'evidence')
            source = self.allowed(db, run, evidence.source, 'source')
            if args.subject not in source.subjects:
                raise Forbidden('该原件未绑定到此主体，不能写入主体数值')
            proofs = [self.allowed(db, run, r, 'evidence') for r in
                      (args.unit_evidence, args.period_evidence, args.basis_evidence)]
            if any(p.source != source.ref for p in proofs):
                raise ValueError('数值的单位、期间与会计口径依据须来自同一原件版本')
            if not args.basis.strip() or args.basis.lower() in ('unknown', 'disclosed'):
                raise ValueError('必须明确 GAAP、IFRS、调整后等会计口径')
            from pitr.domain.numbers import binding_proofs
            binding_proofs(args,*(p.quote for p in proofs))
            index = locate(evidence.quote, args.literal, args.start)
            amount = parse_literal(args.literal) * conversion(args.original_unit, args.unit)
            observation = Observation(id=uid('observation'), created_at=utcnow(),
                **args.model_dump(exclude={'start', 'unit', 'currency', 'share_basis', 'precision'}), start=index)
            deps = [evidence.ref, *(p.ref for p in proofs)]
            self.put(db, run, 'observation', observation, deps)
            value = Value(id=uid('value'), created_at=utcnow(), kind='observed', metric=args.metric,
                amount=amount, unit=args.unit, subject=args.subject, period=args.period, basis=args.basis,
                frequency=args.frequency, currency=args.currency, share_basis=args.share_basis, role=args.role,
                precision=args.precision, observation=observation.ref, dependencies=[observation.ref],
                limitations=['单位、期间及列对应关系仍需独立复核原件；解析与换算已确定性检查'])
            return self.put(db, run, 'value', value, [observation.ref])
        if name == 'value.assume':
            if snapshot.scope.subjects and args.subject not in snapshot.scope.subjects:
                raise Forbidden('假设主体超出研究范围')
            self.store.get(args.subject, 'subject', db=db)
            value = Value(id=uid('value'), created_at=utcnow(), kind='assumption', role='assumption', **args.model_dump())
            return self.put(db, run, 'value', value, args.dependencies)
        if name == 'value.calculate':
            left, right = [self.allowed(db, run, r, 'value') for r in args.inputs]
            amount, unit, period, frequency = calculate(args.operation, left, right)
            calculation = Calculation(id=uid('calculation'), created_at=utcnow(), operation=args.operation,
                inputs=args.inputs, amount=amount, unit=unit)
            self.put(db, run, 'calculation', calculation, args.inputs)
            value = Value(id=uid('value'), created_at=utcnow(), kind='derived', metric=args.metric, amount=amount,
                unit=unit, subject=left.subject, period=period, basis=left.basis, frequency=frequency,
                currency=left.currency if unit not in ('percent','ratio','multiple','percentage_points') else '',
                share_basis='ADS' if unit.endswith('_per_ADS') else 'ordinary' if unit.endswith('_per_share') else left.share_basis,
                role=next((v.role for v in (left,right) if v.role not in ('actual','derived')),'derived'), precision=args.precision,
                calculation=calculation.ref, dependencies=args.inputs)
            return self.put(db, run, 'value', value, [calculation.ref, *args.inputs])
        if name in ('assertion.propose', 'model.propose'):
            body = args.model_dump(exclude={'id', 'expected_revision'})
            kind = 'assertion' if name.startswith('assertion') else 'model'
            if snapshot.scope.subjects and not set(args.subjects).issubset(snapshot.scope.subjects):
                raise Forbidden('判断主体超出研究范围')
            for subject in args.subjects:
                self.store.get(subject, 'subject', db=db)
            if args.id:
                prior=Ref(id=args.id,revision=args.expected_revision)
                # A changed judgment from this same case can be repaired with wholly valid new dependencies.
                same_case=db.execute('SELECT 1 FROM run_objects o JOIN runs r ON r.id=o.run_id WHERE r.case_id=? AND o.id=? AND o.revision=?',
                                     (run.case_id,prior.id,prior.revision)).fetchone()
                if not same_case:self.allowed(db,run,prior,kind)
                old=self.store.get(prior,kind,db=db)
                if snapshot.scope.subjects and not set(old.subjects).issubset(snapshot.scope.subjects):raise Forbidden('待修订判断超出当前主体范围')
            elif args.expected_revision:
                raise ValueError('新对象预期修订为零')
            if kind == 'assertion':
                for ref in args.support + args.counterevidence:
                    self.allowed(db, run, ref, 'evidence')
                for ref in args.values:
                    self.allowed(db, run, ref, 'value')
                if args.kind in ('interpretation','forecast','relationship') and not args.alternative.strip():
                    raise ValueError('核心解释、预测和关系判断需记录替代解释')
                if args.kind == 'relationship':
                    required = {'from', 'to', 'type', 'maturity', 'semantic_basis'}
                    if not required.issubset(args.relation) or not args.relation['semantic_basis']:
                        raise ValueError('关系需包含双方、关系类型、成熟度和来源语义依据')
                    if args.relation['maturity'] not in ('proposed','announced','in_operation','ended','uncertain'):
                        raise ValueError('关系成熟度不是来源等级')
                    if not {args.relation['from'], args.relation['to']}.issubset(set(args.subjects)):
                        raise ValueError('关系双方须包含在判断主体中')
                value = Assertion(id=args.id or uid(kind), revision=args.expected_revision+1, created_at=utcnow(), **body)
                deps = [*args.support, *args.counterevidence, *args.values, *args.depends_on]
            else:
                for ref in args.assumptions + args.outputs:
                    self.allowed(db, run, ref, 'value')
                value = ModelRevision(id=args.id or uid(kind), revision=args.expected_revision+1, created_at=utcnow(), **body)
                deps = [*args.assumptions, *args.outputs]
            result = self.put(db, run, kind, value, deps, expected=args.expected_revision)
            if args.id:
                self.store.invalidate(db, Ref(id=args.id, revision=args.expected_revision), '判断或模型已有新修订', 'superseded')
            return result
        if name == 'report.save':
            case = self.station.get_case(run.case_id, db=db)
            previous = self.store.get(run.report, 'report', db=db) if run.report else None
            document = ReportDocument(id=previous.id if previous else uid('report'),
                revision=previous.revision+1 if previous else 1, created_at=utcnow(), case_id=run.case_id,
                run_id=run.id, input_revision=run.input_revision, snapshot=run.snapshot,
                report_type=case.input.report_type, skills=run.checkpoint.get('skills', []), **args.model_dump())
            self.station.reports.freeze(db, document, expected=previous.revision if previous else 0)
            run.report = document.ref
            return {'report': document.ref, 'delivery': 'awaiting_checks'}
        if name == 'checkpoint.save':
            for ref in args.refs:
                self.allowed(db, run, ref)
            run.checkpoint = {**run.checkpoint, 'research': args.model_dump()}
            return {'saved': True}
        if name in ('skill.load','reference.load'):
            from pitr.skills.library import load,references
            skills = run.checkpoint.get('skills', [])
            pinned=next((s for s in skills if s['name']==args.name),None)
            if pinned and pinned.get('package_digest'):
                return {**json.loads(self.store.read_blob(pinned['package_digest'])),'selection':pinned}
            if name=='skill.load':package=load(args.name)
            else:
                package=next((p for p in references(snapshot.scope.subjects) if p['name']==args.name),None)
                if not package:raise KeyError('此范围没有该参考包')
                package={**package,'digest':digest(package)}
            chosen = {'name': args.name, 'version': package['version'], 'digest': package['digest'], 'reason': args.reason}
            chosen['package_digest']=self.store.blob(canonical(package).encode())
            if not any(s['name'] == args.name for s in skills):
                run.checkpoint = {**run.checkpoint, 'skills': [*skills, chosen]}
            return {**package, 'selection': chosen}
        raise ValueError('未知工具')

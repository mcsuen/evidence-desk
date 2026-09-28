"""Freeze one report tree for the reader, editor, reviewer and document compiler."""
from __future__ import annotations

import json
import re

from pitr.domain.common import Conflict, Forbidden, canonical, uid, utcnow
from pitr.domain.contracts import (
    Ref, ReportDocument, ReportView, Value, EvidenceAnchor, SourceVersion, Assertion,
    ModelRevision, Paragraph, TableBlock, ChartBlock, ValueSpan, CitationSpan,
    CheckResult, ReviewGroup, ReviewDecision, Decide, ReviseReport, ExportRequest,
    ExportJob, Snapshot,
)
from pitr.domain.policy import source_allowed


def blocks(document):
    yield from document.summary
    for section in document.sections:
        yield from section.blocks


def references(document):
    refs = [document.snapshot, *document.assertions, *document.models]
    for block in blocks(document):
        if isinstance(block, Paragraph):
            refs += block.assertions
            spans = block.inlines
        elif isinstance(block, TableBlock):
            spans = [span for row in block.rows for cell in row for span in cell]
        else:
            refs += [ref for series in block.series for ref in series.values if ref]
            spans = []
        refs += [span.ref for span in spans if isinstance(span, (ValueSpan, CitationSpan))]
    return list({ref.key: ref for ref in refs}.values())


class Reports:
    def __init__(self, station):
        self.station, self.store = station, station.store

    def _owned(self, db, run, ref):
        if ref.id == run.snapshot.id and ref.revision<=run.snapshot.revision:
            self.store.get(ref,'snapshot',db=db)
            return
        if db.execute('SELECT 1 FROM run_objects WHERE run_id=? AND id=? AND revision=?',
                      (run.id, ref.id, ref.revision)).fetchone():
            return
        snapshot = self.store.get(run.snapshot, 'snapshot', db=db)
        allowed = {item.ref.key for root in [*snapshot.sources, *snapshot.knowledge,*snapshot.reused,*snapshot.subject_versions]
                   for item in self.store.closure(root, db=db)}
        if ref.key not in allowed:
            raise Forbidden('报告引用不属于本次输入或本次执行：' + ref.key)

    def validate(self, db, document):
        run = self.station.get_run(document.run_id, db=db)
        if (document.case_id, document.input_revision) != (run.case_id, run.input_revision) or document.snapshot.id!=run.snapshot.id or document.snapshot.revision>run.snapshot.revision:
            raise Forbidden('报告与执行固定输入不一致')
        snapshot = self.store.get(document.snapshot, 'snapshot', db=db)
        ids = [section.id for section in document.sections] + [block.id for block in blocks(document)]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', i) for i in ids):
            raise ValueError('章节和内容标识必须唯一，使用字母开头的短标识')
        if not document.summary or not document.sections:
            raise ValueError('报告必须包含摘要与正文；部分报告请明确记录缺项')
        if document.report_type in ('earnings','company','industry') and not document.assertions:
            raise ValueError('财报、公司与产业报告必须登记核心 assertion 并在报告引用；收尾额度允许 assertion.propose')
        listed={r.key for r in document.assertions}
        for block in blocks(document):
            if isinstance(block,Paragraph) and any(r.key not in listed for r in block.assertions):
                raise ValueError('段落判断必须包含在报告的 assertions 中，以进入复核与采纳')
        for ref in references(document):
            self._owned(db, run, ref)
            self.store.get(ref, db=db)
        for block in blocks(document):
            if isinstance(block, ChartBlock):
                for series in block.series:
                    for ref in series.values:
                        if ref:
                            value = self.store.get(ref, 'value', db=db)
                            if value.unit != block.unit:
                                raise ValueError('图表序列单位必须与图表单位一致')
                            if value.role not in ('actual','derived') and series.role == 'actual':
                                raise ValueError('预测或假设不得绘制为实际值')
                continue
            spans = block.inlines if isinstance(block, Paragraph) else [s for row in block.rows for cell in row for s in cell]
            for span in spans:
                if hasattr(span,'text') and re.search(r'(?:\d[\d,.]*\s*(?:%|％|个百分点|亿元|万元|百万元|RMB|USD|million|billion)|(?:RMB|USD|US\$|人民币|美元)\s*[\-−(]?\d)',span.text,re.I):
                    raise ValueError('正文金额、比率与百分点必须使用类型化数值引用，不能手抄在文字中')
                if isinstance(span, ValueSpan):
                    self.store.get(span.ref, 'value', db=db)
                if isinstance(span, CitationSpan):
                    self.store.get(span.ref, 'evidence', db=db)
        for ref in document.assertions:
            self.store.get(ref, 'assertion', db=db)
        for ref in document.models:
            self.store.get(ref, 'model', db=db)
        for ref in [r for r in references(document) if r != document.snapshot]:
            for item in self.store.closure(ref, db=db):
                if snapshot.scope.mode!='historical' and self.store.validity(item.ref,db=db)['status']!='available':
                    raise Conflict('报告引用的判断、模型或其依赖已变化，请修订受影响内容')
                if isinstance(item, SourceVersion):
                    source_allowed(item, snapshot.scope)
                    if snapshot.scope.mode!='historical' and self.store.validity(item.ref, db=db)['status'] != 'available':
                        raise Conflict('报告使用了已更新或撤回的来源，需要重新研究')
        return run

    def check(self, db, target, name, status, *, findings=(), coverage=(), limitations=()):
        value = CheckResult(id=uid('check'), created_at=utcnow(), target=target, name=name,
            status=status, coverage=list(coverage), findings=list(findings), limitations=list(limitations),
            policy_version='review.1')
        self.store.put(db, 'check', value, dependencies=[target])
        self.store.event(db, '', 'report.checked', value)
        return value

    def requires_review(self, db, document):
        risky = [ref for ref in document.assertions
                 if (self.store.get(ref, 'assertion', db=db).kind != 'source_statement'
                     or self.store.get(ref, 'assertion', db=db).values)]
        risky += document.models
        narrative=False
        for block in blocks(document):
            if not isinstance(block,Paragraph):
                narrative=True;continue
            text=''.join(s.text for s in block.inlines if hasattr(s,'text')).strip()
            quotes=[self.store.get(s.ref,'evidence',db=db).quote for s in block.inlines if isinstance(s,CitationSpan)]
            if text and text not in quotes:narrative=True
            if any(isinstance(s,ValueSpan) for s in block.inlines):narrative=True
        # Narratives without assertion annotations also require an independent read.
        return bool(risky or narrative or not document.assertions), risky

    def freeze(self, db, document, *, expected=0):
        document = ReportDocument.model_validate(document)
        self.validate(db, document)
        # Snapshot membership is provenance, not a claim that every allowed source was used.
        self.store.put(db, 'report', document, dependencies=[r for r in references(document) if r != document.snapshot], expected=expected)
        db.execute('INSERT OR IGNORE INTO run_objects VALUES(?,?,?)', (document.run_id, document.id, document.revision))
        self.check(db, document.ref, 'deterministic', 'passed', coverage=[
            'exact_revision_references', 'scope_and_availability', 'typed_values_and_citations', 'table_and_chart_structure'])
        needed, _ = self.requires_review(db, document)
        self.check(db, document.ref, 'independent', 'not_run' if needed else 'not_applicable',
                   limitations=['叙事、判断和原件的独立复核尚未执行'] if needed else [])
        self._groups(db, document)
        self.store.event(db, document.run_id, 'report.frozen', {'report': document.ref})
        return document

    def checks(self, ref, *, db):
        latest = {}
        for row in db.execute("SELECT body FROM revisions WHERE kind='check' ORDER BY rowid"):
            check = CheckResult.model_validate_json(row[0])
            if check.target == ref:
                latest[check.name] = check
        return list(latest.values())

    def view(self, ref):
        from pitr.domain.numbers import display
        with self.store.connect() as db:
            document = self.store.get(ref, 'report', db=db)
            objects = self.store.closure(document.ref, db=db)
            checks = self.checks(document.ref, db=db)
            ready = len(checks) >= 2 and all(c.status in ('passed', 'not_applicable') for c in checks)
            delivery = 'ready' if ready and not document.gaps else 'partial' if document.gaps else 'draft'
            return ReportView(document=document, delivery=delivery, checks=checks,
                current_validity=self.store.validity(document.ref, db=db),
                values=[v for v in objects if isinstance(v, Value)],
                value_labels={v.ref.key: display(v) for v in objects if isinstance(v, Value)},
                evidence=[v for v in objects if isinstance(v, EvidenceAnchor)],
                sources=[v for v in objects if isinstance(v, SourceVersion)],
                assertions=[v for v in objects if isinstance(v, Assertion)],
                exports=[ExportJob.model_validate_json(r[0]) for r in db.execute('SELECT body FROM exports')
                         if json.loads(r[0])['report'] == document.ref.model_dump()])

    def revise(self, report_id, request: ReviseReport):
        request = ReviseReport.model_validate(request)
        def save(db):
            previous = self.store.get(report_id, 'report', db=db)
            if previous.revision != request.expected_revision:
                raise Conflict('报告已经有新修订，请刷新后编辑')
            body = request.model_dump(exclude={'operation_id', 'expected_revision', 'reason'})
            document = ReportDocument.model_validate({**previous.model_dump(), **body,
                'revision': previous.revision+1, 'created_at': utcnow(), 'change_reason': request.reason})
            self.freeze(db, document, expected=previous.revision)
            # Revision review is independent of the research queue and never reruns acquisition.
            if self.requires_review(db, document)[0]:
                db.execute('INSERT INTO outbox VALUES(?,?,?,?)', (uid('review'), 'report_review', 'queued',
                           canonical({'report': document.ref})))
            return document.model_dump(mode='json')
        return self.store.once(request.operation_id, {'command': 'report.revise', 'id': report_id, 'request': request}, save)

    def _groups(self, db, document):
        # Atomic adoption only for genuinely dependent assertions/models, not for shared sources.
        refs = {r.key: r for r in [*document.assertions, *document.models]}
        edges = {key: set() for key in refs}
        for key, ref in refs.items():
            for item in self.store.closure(ref, db=db):
                if item.ref.key in refs and item.ref.key != key:
                    edges[key].add(item.ref.key)
                    edges[item.ref.key].add(key)
        while refs:
            pending, component = [next(iter(refs))], {}
            while pending:
                key = pending.pop()
                if key in component:
                    continue
                component[key] = refs[key]
                pending += list(edges[key])
            targets = list(component.values())
            for key in component:
                del refs[key]
            matching=[g for g in self.store.list('review_group',db=db) if {r.key for r in g.targets}==set(component)]
            if any(db.execute('SELECT status FROM review_state WHERE id=?',(g.id,)).fetchone()[0]=='adopt' for g in matching):
                continue
            for existing in matching:
                db.execute("UPDATE review_state SET status='superseded' WHERE id=? AND status='pending'",(existing.id,))
            expected = {}
            for ref in targets:
                row = db.execute('SELECT revision FROM accepted WHERE id=?', (ref.id,)).fetchone()
                expected[ref.id] = row[0] if row else 0
            group = ReviewGroup(id=uid('review_group'), created_at=utcnow(), title=' / '.join(
                self.store.get(r, db=db).title for r in targets), targets=targets, expected_heads=expected,
                report=document.ref, reason='相互依赖的判断需要一起采纳' if len(targets)>1 else '可独立采纳的判断')
            self.store.put(db, 'review_group', group, dependencies=[*targets, document.ref])
            db.execute('INSERT INTO review_state VALUES(?,?,NULL)', (group.id, 'pending'))

    def groups(self):
        with self.store.connect() as db:
            result = []
            for group in self.store.list('review_group', db=db):
                state = db.execute('SELECT status,decision_id FROM review_state WHERE id=?', (group.id,)).fetchone()
                result.append({**group.model_dump(mode='json'), **dict(state),
                    'case_id': self.store.get(group.report,'report',db=db).case_id if group.report else None,
                    'run_id': self.store.get(group.report,'report',db=db).run_id if group.report else None,
                    'objects': [self.store.get(r, db=db).model_dump(mode='json') for r in group.targets],
                    'checks':[c.model_dump(mode='json') for c in self.checks(group.report,db=db)] if group.report else [],
                    'current_validity': self.store.validity(group.ref, db=db)})
            return result

    def decide(self, group_id, request: Decide):
        request = Decide.model_validate(request)
        def save(db):
            group = self.store.get(group_id, 'review_group', db=db)
            if group.revision != request.expected_revision:
                raise Conflict('审核组版本已变化')
            row = db.execute('SELECT status FROM review_state WHERE id=?', (group_id,)).fetchone()
            if row['status'] != 'pending':
                raise Conflict('此审核已有决定')
            if request.action == 'adopt':
                for ref in group.targets:
                    head = self.store.get(ref.id, db=db)
                    row = db.execute('SELECT revision FROM accepted WHERE id=?', (ref.id,)).fetchone()
                    if head.revision != ref.revision or (row[0] if row else 0) not in (group.expected_heads[ref.id],ref.revision):
                        raise Conflict('判断或已采纳版本已变化，需要重新审核')
                    if self.store.validity(ref, db=db)['status'] != 'available':
                        raise Conflict('判断依赖已变化，需要重新研究')
                if group.report:
                    checks = self.checks(group.report, db=db)
                    if any(c.status in ('failed', 'error') for c in checks):
                        raise Conflict('报告检查存在失败项，修订后才能采纳')
            decision = ReviewDecision(id=uid('decision'), created_at=utcnow(), group_id=group_id,
                targets=group.targets, action=request.action, reason=request.reason)
            self.store.put(db, 'decision', decision, dependencies=[group.ref, *group.targets])
            if request.action == 'adopt':
                for ref in group.targets:
                    db.execute('INSERT INTO accepted VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET '
                        'revision=excluded.revision,decision_id=excluded.decision_id', (ref.id, ref.revision, decision.id))
            db.execute('UPDATE review_state SET status=?,decision_id=? WHERE id=?', (request.action, decision.id, group_id))
            self.store.event(db, '', 'review.decided', decision)
            return decision.model_dump(mode='json')
        return self.store.once(request.operation_id, {'command': 'review.decide', 'group': group_id, 'request': request}, save)

    def export(self, request: ExportRequest):
        from pitr.domain.common import digest
        from pitr.artifacts.docx import TEMPLATE,COMPILER
        request = ExportRequest.model_validate(request)
        def save(db):
            report=self.store.get(request.report, 'report', db=db)
            checks=self.checks(request.report,db=db)
            refs=[c.ref for c in checks]
            ready=len(checks)>=2 and all(c.status in ('passed','not_applicable') for c in checks)
            delivery='partial' if report.gaps else 'ready' if ready else 'draft'
            signature = digest({'report': request.report, 'paper': request.paper, 'template': TEMPLATE, 'compiler': COMPILER,'checks':refs,'delivery':delivery})
            row = db.execute('SELECT body FROM exports WHERE signature=?', (signature,)).fetchone()
            if row:
                return json.loads(row[0])
            job = ExportJob(id=uid('export'), report=request.report, signature=signature,
                status='queued', paper=request.paper, template_version=TEMPLATE,check_refs=refs,delivery_at_request=delivery, created_at=utcnow(), updated_at=utcnow())
            db.execute('INSERT INTO exports(id,signature,status,body) VALUES(?,?,?,?)', (job.id, signature, job.status, canonical(job)))
            self.store.event(db, report.run_id, 'export.queued', {'job': job.id, 'report': job.report})
            return job.model_dump(mode='json')
        return self.store.once(request.operation_id, {'command': 'report.export', 'request': request}, save)

    def retry_export(self, job_id, operation_id):
        def save(db):
            row = db.execute('SELECT body FROM exports WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError('导出不存在')
            job = ExportJob.model_validate_json(row[0])
            if job.status != 'failed':
                raise Conflict('只能重试失败的导出')
            job.status, job.error, job.updated_at = 'queued', '', utcnow()
            db.execute('UPDATE exports SET status=?,owner=NULL,lease_until=NULL,body=? WHERE id=?',
                       (job.status, canonical(job), job_id))
            report=self.store.get(job.report, 'report', db=db)
            self.store.event(db, report.run_id, 'export.queued', {'job': job.id, 'report': job.report, 'retry': True})
            return job.model_dump(mode='json')
        return self.store.once(operation_id, {'command': 'export.retry', 'job': job_id}, save)

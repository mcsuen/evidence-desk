"""Observed trace projection. Replay never borrows future status, timing or results."""
import json
import time
from contextlib import contextmanager
from pitr.domain.common import uid, instant, Forbidden
from pitr.domain.contracts import Ref
from pitr.domain.views import TraceView, TraceSpan, TraceLink, TraceSummary


def record(store, run_id, kind, data):
    with store.connect(write=True) as db:
        store.event(db, run_id, kind, data)


@contextmanager
def span(store, run, name, kind, *, parent_id=None, span_id=None, **metadata):
    identity = span_id or uid('span')
    start = time.monotonic()
    record(store, run.id, 'span.started', {'id': identity, 'parent_id': parent_id, 'name': name,
        'kind': kind, 'executor': run.agent.get('provider', run.lane) if kind == 'agent' else 'deterministic',
        'generation': run.generation, 'input_version': run.input_revision, 'metadata': metadata})
    outcome = {}
    try:
        yield identity, outcome
    except BaseException as error:
        record(store, run.id, 'span.finished', {'id': identity, 'status': 'interrupted' if isinstance(error, Forbidden) else 'failed',
            'duration_ms': (time.monotonic()-start)*1000, 'error': str(error)[:4000], **outcome})
        raise
    else:
        record(store, run.id, 'span.finished', {'id': identity, 'status': 'completed',
            'duration_ms': (time.monotonic()-start)*1000, **outcome})


def trace_view(station, run_id, at_seq=None, *, detail_id=None):
    run = station.get_run(run_id)
    with station.store.connect() as db:
        rows = list(db.execute('SELECT * FROM trace WHERE run_id=? ORDER BY seq', (run_id,)))
    latest = rows[-1]['seq'] if rows else 0
    rows = [r for r in rows if at_seq is None or r['seq'] <= at_seq]
    spans, links, tokens, gaps, producers = {}, [], {}, [], {}
    generation, status, previous, queue_start = 0, 'unobserved', None, None
    continuing = False
    queue_seconds = 0.0
    def link(a, b, kind):
        if a and a != b:
            identity=f'{a}:{b}:{kind}'
            if not any(l.id == identity for l in links):
                links.append(TraceLink(id=identity, source=a, target=b, kind=kind))
    def refs(value):
        if isinstance(value, dict):
            if set(value) == {'id','revision'}:
                yield f"{value['id']}@{value['revision']}"
            else:
                for item in value.values():yield from refs(item)
        elif isinstance(value, list):
            for item in value:yield from refs(item)
    for row in rows:
        seq, at, kind, data = row['seq'], row['at'], row['kind'], json.loads(row['body'])
        if data.get('content_digest'):
            data = json.loads(station.store.read_blob(data['content_digest']))
        if kind in ('run.queued', 'run.continued'):
            status, queue_start = 'queued', at
            continuing = kind == 'run.continued'
        elif kind == 'run.claimed':
            generation, status = data['generation'], 'running'
            recovered = continuing or data.get('recovered', False) or generation > 1
            continuing = False
            if queue_start:
                queue_seconds += max(0, (instant(at)-instant(queue_start)).total_seconds())
                queue_start = None
            # A claim fences the preceding lease; unfinished observations remain visibly interrupted.
            for value in spans.values():
                if value.status == 'running':
                    value.status, value.last_seq = 'interrupted', seq
            identity = f'claim:{seq}'
            spans[identity] = TraceSpan(id=identity, name='恢复执行' if recovered else '开始执行',
                kind='control', status='completed', generation=generation, started_at=at,
                input_version=run.input_revision, first_seq=seq, last_seq=seq)
            link(previous, identity, 'recovery' if recovered else 'sequence')
            previous = identity
        elif kind == 'span.started':
            inputs = list(refs(data.get('metadata', {}).get('arguments', {})))
            repair = data['kind'] == 'agent' and data.get('metadata', {}).get('role') == 'research' and any(
                s.kind == 'agent' and s.generation == data['generation'] and s.metadata.get('role') == 'research' for s in spans.values())
            if data['id'] != detail_id:
                data['metadata'] = {k:v for k,v in data.get('metadata', {}).items() if k != 'arguments'}
            value = TraceSpan(**data, first_seq=seq, last_seq=seq, started_at=at)
            spans[value.id] = value
            if value.kind not in ('tool', 'rejected_tool') or not value.parent_id:
                link(previous, value.id, 'repair' if repair else 'sequence')
                previous = value.id
            for key in inputs:
                link(producers.get(key), value.parent_id or value.id, 'dependency')
        elif kind == 'span.finished' and data['id'] in spans:
            value = spans[data['id']]
            value.ended_at, value.last_seq = at, seq
            value.status = data['status']
            value.duration_ms, value.timing = data.get('duration_ms'), 'measured'
            value.metadata.update({k:v for k,v in data.items() if k not in ('id','status','duration_ms')})
            value.artifact_refs = data.get('artifact_refs', [])
            if value.status == 'completed' and value.name in ('source.fetch','evidence.quote','value.bind','value.assume','value.calculate','assertion.propose','model.propose','report.save'):
                for key in refs(data.get('artifact_refs', [])):
                    producers[key] = value.parent_id or value.id
            value.issue_count = data.get('issue_count', 0)
            if data.get('rejected'):
                value.kind = 'rejected_tool'
        elif kind == 'tool.called' and data.get('span_id'):
            value = spans.get(data['span_id'])
            if value and value.id == detail_id:
                result = data.get('result')
                if isinstance(result, dict):
                    result = {k:v for k,v in result.items() if k != 'png_base64'}
                value.metadata['result'] = result
                value.last_seq = seq
        elif kind == 'tool.called':
            # Older E records contain completion observations only. Never synthesize their start.
            identity = f'tool:{seq}'
            parent = next((s.id for s in reversed(list(spans.values())) if s.kind == 'agent' and s.status == 'running' and s.generation == data.get('generation',generation)), None)
            result = data.get('result')
            output_refs = []
            if isinstance(result, dict):
                if 'id' in result and 'revision' in result:output_refs.append({'id':result['id'],'revision':result['revision']})
                if isinstance(result.get('report'),dict):output_refs.append(result['report'])
            spans[identity] = TraceSpan(id=identity, parent_id=parent, kind='tool', name=data['name'],
                executor='deterministic', status='completed', ended_at=at, generation=data.get('generation',generation),
                first_seq=seq, last_seq=seq, artifact_refs=output_refs, metadata=data if identity == detail_id else {'operation_id':data.get('operation_id')})
        elif kind == 'agent.event':
            event = data.get('event', data)
            parent = spans.get(data.get('span_id'))
            if parent:
                parent.last_seq = seq
                parent.metadata['event_count'] = parent.metadata.get('event_count', 0) + 1
                if parent.id == detail_id:
                    parent.metadata['events'] = [*parent.metadata.get('events', [])[-79:],
                        {'seq':seq,'at':at,'event':event}]
            usage = event.get('usage') or {}
            if event.get('type') == 'turn.completed':
                for key, value in usage.items():
                    if isinstance(value, int):tokens[key] = tokens.get(key, 0) + value
        elif kind in ('report.frozen', 'review.completed', 'export.queued', 'export.claimed', 'export.completed', 'export.failed'):
            if kind == 'review.completed' and 'status' not in data and data.get('check'):
                check = station.store.get(Ref.model_validate(data['check']), 'check')
                data = {**data,'status':check.status,'findings':check.findings}
            identity = f'{kind}:{seq}'
            is_export = kind.startswith('export.')
            if kind == 'export.queued':
                continue
            if kind in ('export.completed', 'export.failed'):
                identity = next((s.id for s in reversed(list(spans.values())) if s.kind == 'export' and s.metadata.get('job') == data['job'] and s.status == 'running'), identity)
            value = spans.get(identity)
            if value:
                value.status, value.ended_at, value.last_seq = ('failed' if kind.endswith('failed') else 'completed'), at, seq
                value.duration_ms = max(0, (instant(at)-instant(value.started_at)).total_seconds()*1000)
                value.timing = 'observed'
                value.metadata.update(data)
                if data.get('artifact'):value.artifact_refs.append(Ref.model_validate(data['artifact']))
                continue
            value = TraceSpan(id=identity, name={'report.frozen':'冻结报告','review.completed':'保存独立复核','export.claimed':'生成 Word','export.completed':'Word 已交付','export.failed':'Word 导出失败'}[kind],
                kind='export' if is_export else 'artifact', status='running' if kind.endswith('claimed') else 'failed' if kind.endswith('failed') else 'completed',
                started_at=at if kind.endswith('claimed') else None, ended_at=None if kind.endswith('claimed') else at,
                generation=generation, first_seq=seq, last_seq=seq, metadata=data,
                artifact_refs=[data[k] for k in ('report','check','artifact') if isinstance(data.get(k),dict)])
            if kind == 'review.completed':
                value.status = 'completed' if data.get('status') in ('passed','not_applicable') else 'needs_review'
                value.issue_count = len(data.get('findings', []))
            spans[identity] = value
            earlier = next((s.id for s in reversed(list(spans.values())) if s.id != identity and s.metadata.get('job') == data.get('job') and data.get('job')), None)
            link(earlier or previous, identity, 'recovery' if earlier else 'artifact')
            if not is_export:previous = identity
        elif kind.startswith('run.'):
            status = kind.removeprefix('run.')
            if status in ('cancelled','failed','budget_exhausted','waiting_user','completed'):
                for value in spans.values():
                    if value.status == 'running' and value.kind != 'export':
                        value.status, value.last_seq = 'interrupted', seq
                identity = f'run:{seq}'
                spans[identity] = TraceSpan(id=identity, name={'cancelled':'取消研究','failed':'执行失败','budget_exhausted':'预算耗尽','waiting_user':'等待补充','completed':'研究执行结束'}[status],
                    kind='control', status=status, ended_at=at, generation=generation, first_seq=seq, last_seq=seq, metadata=data)
                link(previous, identity, 'sequence');previous = identity
    for value in spans.values():
        children = [s for s in spans.values() if s.parent_id == value.id]
        value.tool_count = len(children)
    tools = [s for s in spans.values() if s.kind in ('tool', 'rejected_tool')]
    measured = [s for s in tools if s.duration_ms is not None]
    if any(s.duration_ms is None for s in tools):gaps.append('部分调用仅记录完成事件，开始时间和耗时未采集。')
    if not any(s.kind == 'agent' for s in spans.values()):gaps.append('当前记录未采集 Agent 调用区间；仅展示已观察事件。')
    if not tokens:gaps.append('本次记录没有可汇总的输入与输出 token 用量。')
    # Unparented historical tool records must remain selectable in both graph and waterfall.
    for value in tools:
        if not value.parent_id:
            value.kind = 'tool_observation'
    return TraceView(run_id=run_id, case_id=run.case_id, seq=rows[-1]['seq'] if rows else 0,
        latest_seq=latest, task_status=status, spans=list(spans.values()), links=links,
        summary=TraceSummary(active_seconds=run.active_seconds if at_seq is None else None,
            queue_seconds=queue_seconds if queue_start is None else None, tool_count=len(tools), measured_tools=len(measured),
            tool_seconds=sum(s.duration_ms for s in measured)/1000 if measured else None,
            budget_tool_count=run.tool_calls if at_seq is None else None, tokens=tokens, gaps=gaps))

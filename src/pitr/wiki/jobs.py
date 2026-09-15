"""Durable company Wiki jobs and local schedules on the existing desk queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pitr.desk.contracts import TaskInput, utcnow
from pitr.desk.storage import Conflict, canonical, digest, uid
from .contracts import CompanyRegistration, WikiJobRequest, WikiUpdateSchedule
from .store import change, get, state
from .discovery import discover, fetch_public, public_url, FetchError, failure_details
from .acquisition import alternative_candidates, check_payload, validate_original, provenance, coverage_for, supported_needs, REGULATORS, STATISTICS


DEFAULT_COMPANIES = {
    'PDD': {'name': 'PDD Holdings · 拼多多', 'aliases': ['拼多多', 'PDD Holdings', 'Pinduoduo'],
            'official_domains': ['investor.pddholdings.com', 'pinduoduo.gcs-web.com'],
            'catalog_urls': ['https://investor.pddholdings.com/financial-information/quarterly-results',
                             'https://investor.pddholdings.com/financial-information/annual-reports']},
    'BABA': {'name': 'Alibaba Group · 阿里巴巴', 'aliases': ['阿里巴巴', 'Alibaba', 'Alibaba Group', 'Alibaba Group Holding Limited'], 'official_domains': ['www.alibabagroup.com'], 'catalog_urls': []},
    'JD': {'name': 'JD.com · 京东', 'aliases': ['京东', 'JD.com'], 'official_domains': ['ir.jd.com'], 'catalog_urls': []},
    'AMZN': {'name': 'Amazon', 'aliases': ['亚马逊'], 'official_domains': ['ir.aboutamazon.com'], 'catalog_urls': []},
    'MELI': {'name': 'MercadoLibre', 'aliases': ['美客多'], 'official_domains': ['investor.mercadolibre.com'], 'catalog_urls': []},
}
TERMINAL = {'completed', 'partial', 'failed', 'cancelled'}


def next_run(schedule, after):
    """One wall-clock run per local date; skip nonexistent DST times."""
    zone = ZoneInfo(schedule['timezone'])
    after = datetime.fromtimestamp(after, timezone.utc) if isinstance(after, (int, float)) else after
    local = after.astimezone(zone)
    hour, minute = map(int, schedule['local_time'].split(':'))
    weekdays = range(7) if schedule['frequency'] == 'daily' else schedule['weekdays']
    for offset in range(15):
        day = local.date() + timedelta(days=offset)
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        normalized = candidate.astimezone(timezone.utc).astimezone(zone)
        if candidate.weekday() in weekdays and normalized.hour == hour and normalized.minute == minute and candidate > after:
            return candidate.astimezone(timezone.utc).isoformat()
    raise ValueError('没有有效的下次执行时间')


class WikiJobs:
    def __init__(self, wiki, queue=None):
        self.wiki, self.queue = wiki, queue

    def companies(self, db=None):
        if db is None:
            with self.wiki.store.connect() as conn:
                return self.companies(conn)
        return {**{k: {'company': k, **v} for k, v in DEFAULT_COMPANIES.items()}, **state(db, 'companies')}

    def resolve(self, name, db=None):
        companies = self.companies(db)
        matches = [c for c in companies.values() if name.casefold() in
                   [c['company'].casefold(), c['name'].casefold(), *[a.casefold() for a in c['aliases']]]]
        if len(matches) != 1:
            raise ValueError('公司主体未明确，请先登记公司代码、名称及官方域名' if not matches else '存在同名主体，请使用公司代码')
        return matches[0]

    def register(self, request: CompanyRegistration):
        payload = request.model_dump()
        for host in request.official_domains:
            if not re.fullmatch(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', host):
                raise ValueError('官方域名格式无效')
            public_url('https://' + host, resolve=False)
        for url in request.catalog_urls:
            public_url(url, resolve=False)
            if urlsplit(url).hostname not in request.official_domains:
                raise ValueError('官方目录必须位于已登记官方域名')
        with self.wiki.store.connect(write=True) as db:
            cached = self.wiki._cached(db, request.operation_id, payload)
            if cached:
                return cached
            previous = self.companies(db).get(request.company)
            result = {k: v for k, v in payload.items() if k != 'operation_id'}
            result.update(version=previous.get('version', 0) + 1 if previous else 1, registered_at=utcnow())
            self.wiki._emit(db, request.company, 'company.registered', [change('companies', request.company, result)])
            return self.wiki._remember(db, request.operation_id, payload, result)

    def create(self, request: WikiJobRequest, *, notification_event_id='', db=None):
        from contextlib import nullcontext
        if request.as_of and request.as_of > utcnow():
            raise ValueError('研究时点不能位于未来')
        payload = {**request.model_dump(), 'notification_event_id': notification_event_id}
        with self.wiki.store.connect(write=True) if db is None else nullcontext(db) as conn:
            cached = self.wiki._cached(conn, request.operation_id, payload)
            if cached:
                return cached
            company = self.resolve(request.company, conn)
            for sid in request.source_ids:
                source = get(conn, 'sources', sid)
                if not source or source['company'] != company['company'] or source['state'] != 'available':
                    raise ValueError('补充材料不属于本公司或已不可用')
            previous = get(conn, 'jobs', request.resume_job_id) if request.resume_job_id else None
            if request.resume_job_id and (not previous or previous['company'] != company['company'] or previous['execution_status'] not in TERMINAL):
                raise Conflict('只能继续同一公司的已结束任务')
            if previous and previous['request'].get('as_of') != request.as_of:
                raise Conflict('研究时点已改变，请新建任务；恢复任务保持原时点')
            jid, tid = uid('wiki-job'), uid('task')
            req = TaskInput(operation_id=request.operation_id, workflow='wiki_job', company=company['company'],
                            parameters={'job_id': jid}, budget_seconds=request.budget_seconds)
            task = {'id': tid, 'request': req.model_dump(), 'status': 'queued', 'stage': 'queued',
                    'created_at': utcnow(), 'versions': {'workflow': 'wiki-job.1', 'tools': 'wiki.1'}, 'attempts': 0}
            result = {'id': jid, 'task_id': tid, 'company': company['company'], 'identity': company,
                      'request': {**request.model_dump(), 'company': company['company']},
                      'policy': self.wiki._policy(conn), 'created_at': utcnow(), 'stage': 'queued',
                      'execution_status': 'queued', 'publication_status': 'not_published',
                      'materials': [], 'coverage': [], 'checks': [], 'failures': [], 'skipped': [],
                      'notification_event_id': notification_event_id,
                      'resumed_from': previous['id'] if previous else None}
            if previous:
                # Reuse only successfully acquired originals. Failed candidates remain retryable.
                result['materials'] = [m for m in previous['materials'] if m.get('source_id') or m.get('payload_object')]
                result['previous_failures'] = [*previous.get('previous_failures', []),
                    *[{**f, 'job_id': previous['id']} for f in previous['failures']]]
                result['catalog_checks'] = previous.get('catalog_checks', [])
                result['resume_proposal_id'] = previous.get('proposal_id')
                result['resume_candidates'] = previous.get('candidates', [])
                prior_task = conn.execute('SELECT body FROM tasks WHERE id=?', (previous['task_id'],)).fetchone()
                prior_result = json.loads(prior_task['body']).get('result', {}) if prior_task else {}
                if prior_result.get('wiki_proposal') and previous['request']['research_focus'] == request.research_focus:
                    result['resume_compilation_object'] = self.wiki.objects.json(prior_result)
                if previous.get('discovery', {}).get('candidates'):
                    result['discovery'] = previous['discovery']
            from pitr.agent_runtime import bind_task
            bind_task(self.wiki.desk,task,request.agent_provider,request.model,
                      parent=json.loads(prior_task['body']) if previous and prior_task else None)
            if task.get('agent'):result['agent']=task['agent']
            conn.execute('INSERT INTO tasks(id,status,body) VALUES(?,?,?)', (tid, 'queued', canonical(task)))
            self.wiki._emit(conn, company['company'], 'job.created', [change('jobs', jid, result)])
            return self.wiki._remember(conn, request.operation_id, payload, result)

    def list(self, company):
        with self.wiki.store.connect() as db:
            return [self.get(j['id'], db) for j in sorted(state(db, 'jobs').values(), key=lambda j: j['created_at'], reverse=True) if j['company'] == company]

    def get(self, jid, db=None):
        if db is None:
            with self.wiki.store.connect() as conn:
                return self.get(jid, conn)
        job = get(db, 'jobs', jid)
        if not job:
            raise KeyError('Wiki 任务不存在')
        proposal = get(db, 'proposals', job.get('proposal_id', ''))
        if proposal:
            job['publication_status'] = 'published' if proposal['status'] == 'adopted' else 'rejected' if proposal['status'] == 'rejected' else 'waiting_review'
        task = db.execute('SELECT status,body FROM tasks WHERE id=?', (job['task_id'],)).fetchone()
        if task:
            job['task_status'] = task['status']
            job['task_error'] = json.loads(task['body']).get('error')
            if json.loads(task['body']).get('agent'):job['agent']=json.loads(task['body'])['agent']
        return job

    def schedule(self, request: WikiUpdateSchedule):
        payload = request.model_dump()
        with self.wiki.store.connect(write=True) as db:
            cached = self.wiki._cached(db, request.operation_id, payload)
            if cached:
                return cached
            company = self.resolve(request.company, db)['company']
            previous = get(db, 'update_schedules', company) or {}
            result = {**payload, 'company': company, 'id': company, 'version': previous.get('version', 0) + 1,
                      'updated_at': utcnow(), 'policy': self.wiki._policy(db), 'cancelled': False}
            result['next_at'] = next_run(result, time.time()) if request.enabled else None
            self.wiki._emit(db, company, 'update.schedule_changed', [change('update_schedules', company, result)])
            return self.wiki._remember(db, request.operation_id, payload, result)

    def cancel_schedule(self, company, operation_id):
        with self.wiki.store.connect(write=True) as db:
            payload = {'company': company, 'cancel': True}
            cached = self.wiki._cached(db, operation_id, payload)
            if cached:
                return cached
            record = get(db, 'update_schedules', company)
            if not record:
                raise KeyError('更新计划不存在')
            record.update(enabled=False, cancelled=True, next_at=None, version=record['version'] + 1)
            self.wiki._emit(db, company, 'update.schedule_cancelled', [change('update_schedules', company, record)])
            return self.wiki._remember(db, operation_id, payload, record)

    def tick(self, now=None):
        now = time.time() if now is None else now
        with self.wiki.store.connect(write=True) as db:
            for schedule in state(db, 'update_schedules').values():
                if not schedule['enabled'] or not schedule.get('next_at') or datetime.fromisoformat(schedule['next_at']).timestamp() > now:
                    continue
                due = schedule['next_at']
                # A queued update already covers missed local intervals. Executing jobs
                # keep their scope; one following check is queued, never overlapping.
                queued = next((j for j in state(db, 'jobs').values() if j['company'] == schedule['company'] and
                               j['request']['intent'] == 'update' and j['execution_status'] == 'queued'), None)
                if not queued:
                    self.create(WikiJobRequest(operation_id='schedule:' + schedule['company'] + ':' + due,
                        intent='update', company=schedule['company'], channel='schedule',
                        research_focus=schedule['research_focus'], budget_seconds=schedule['budget_seconds']),
                        notification_event_id=schedule['notification_event_id'], db=db)
                schedule.update(last_due_at=due, next_at=next_run(schedule, now))
                self.wiki._emit(db, schedule['company'], 'update.schedule_fired', [change('update_schedules', schedule['company'], schedule)],
                                details={'coalesced_into': queued['id'] if queued else None})


def finalize(wiki, db, task):
    jid = task['request']['parameters']['job_id']
    job = get(db, 'jobs', jid)
    if not job:
        return
    result = task.get('result', {})
    job.update(execution_status='failed' if task['status'] == 'failed' else 'cancelled' if task['status'] == 'cancelled' else result.get('execution_status', 'completed'),
               stage='finished', finished_at=utcnow(), error=task.get('error'),
               proposal_id=result.get('proposal_id'), publication_status='waiting_review' if result.get('proposal_id') else 'not_published')
    for check in job['checks']:
        if check['kind'] == 'publication':
            check['status'] = 'passed' if result.get('proposal_id') else 'failed'
            check['note'] = '统一版本、数字、引文与依赖校验通过，语义仍需人工采纳' if result.get('proposal_id') else '提案未通过发布前校验，未修改正式 Wiki'
    if task.get('error'):
        job['failures'].append({'stage': task.get('stage'), 'reason': task['error']})
    notifications = []
    if job.get('notification_event_id') and not result.get('reused_proposal') and (job.get('proposal_id') or job['execution_status'] in ('failed', 'partial')):
        summary = '资料整理完成，等待人工采纳' if job.get('proposal_id') else '检查未完成，请查看失败与缺口'
        notifications = [('slack', {'event_id': job['notification_event_id'],
                         'text': f"{job['company']} Wiki：{summary}。工作台 /wiki?company={job['company']}&job={jid}"})]
    wiki._emit(db, job['company'], 'job.finished', [change('jobs', jid, job)], jobs=notifications)


def requirements(request):
    today = datetime.fromisoformat(request['as_of']) if request.get('as_of') else datetime.now(timezone.utc)
    items = [{'id': f'annual:{today.year - i}', 'label': f'{today.year - i} 财年', 'period': f'{today.year - i}FY'} for i in range(1, request['years'] + 1)]
    q = today.year * 4 + (today.month - 1) // 3 - 1
    for offset in range(request['quarters']):
        year, quarter = divmod(q - offset, 4)
        period = f'{year}Q{quarter + 1}'
        items.append({'id': 'quarter:' + period, 'label': period + ' 披露', 'period': period})
    items += [{'id': key, 'label': label} for key, label in [('business', '业务与盈利驱动'), ('competition', '竞争与同业'),
              ('industry', '行业与公共统计'), ('media', '媒体与公开访谈'), ('risk', '风险与反证')]]
    return [{**item, 'status': 'pending', 'source_ids': []} for item in items]


def run(wiki, task, owner, checkpoint, *, discovery_fn=None, fetch_fn=None, compile_fn=None):
    from .worker import compile_sources
    from pitr.desk.sources import extract_pdd_metrics
    from .parsing import parse_original
    jobs = WikiJobs(wiki)
    job = jobs.get(task['request']['parameters']['job_id'])
    request, company = job['request'], job['company']
    started = time.monotonic()
    budget = request['budget_seconds']
    already_spent = job.get('elapsed_seconds', 0)
    reserve = min(300, budget * .3)
    settings_path = wiki.desk.root / 'private/settings.json'
    contact = json.loads(settings_path.read_text()).get('sec_user_agent', '') if settings_path.exists() else ''
    host_failures = job.setdefault('host_failures', {})

    def remaining():
        return max(0, budget - already_spent - (time.monotonic() - started))

    def download(url, timeout):
        host = urlsplit(url).hostname
        if host_failures.get(host, 0) >= 2:
            raise FetchError('本站连续连接失败，本轮先处理其他来源', kind='host_deferred', phase='connect', retryable=True, next_action='resume')
        try:
            if fetch_fn:
                result = fetch_fn(url, timeout=timeout)
            else:
                result = fetch_public(url, timeout=timeout, **({'contact': contact} if contact else {}))
            host_failures[host] = 0
            return result
        except Exception as error:
            if failure_details(error)['error_type'] in ('connection_failed', 'tls_error'):
                host_failures[host] = host_failures.get(host, 0) + 1
            raise

    def fence(db):
        if not db.execute("SELECT 1 FROM tasks WHERE id=? AND owner=? AND status='running' AND lease_until>=?", (task['id'], owner, time.time())).fetchone():
            raise Conflict('任务已取消或执行权已转移')

    def save(stage, **updates):
        checkpoint({'stage': stage, 'wiki_job_id': job['id']})
        job.update(stage=stage, execution_status='running', **updates)
        job['elapsed_seconds'] = round(already_spent + time.monotonic() - started, 2)
        with wiki.store.connect(write=True) as db:
            fence(db)
            wiki._emit(db, company, 'job.progress', [change('jobs', job['id'], job)])

    if request['channel'] == 'schedule':
        with wiki.store.connect() as db:
            schedule = get(db, 'update_schedules', company)
        if not schedule or not schedule['enabled']:
            return {'status': 'cancelled', 'execution_status': 'cancelled', 'reason': '更新计划已暂停或取消'}
    if not job['coverage']:
        job['coverage'] = requirements(request)
    save('wiki_planning')
    with wiki.store.connect() as db:
        st = wiki._view_state(db, request.get('as_of'))
        pages = wiki._visible(st, company, request.get('as_of'))
        context = {'company': job['identity'], 'request': request, 'policy': st['revisions'].get(f"{job['policy']['id']}@v{job['policy']['version']}"),
                   'needs': job['coverage'], 'wiki': [{'id': p['id'], 'version': p['version'], 'title': p['title'], 'summary': p.get('summary')} for p in pages],
                   'unresolved': [i for i in st.get('issues', {}).values() if i['company'] == company and i.get('status') != 'closed'],
                   'pending_proposals': [{'id': p['id'], 'reason': p['request']['reason']} for p in st.get('proposals', {}).values() if p['company'] == company and p['status'] == 'pending'],
                   'source_checks': [c for c in st.get('source_checks', {}).values() if c['company'] == company]}
    context['previous_failures'] = job.get('previous_failures', [])
    job['context_object'] = wiki.objects.json(context)
    for sid in request.get('source_ids', []):
        source = st.get('sources', {}).get(sid)
        if not source or source['state'] != 'available':
            job['failures'].append({'source_id': sid, 'stage': 'input', 'reason': '补充来源已不可用'})
        elif not any(m.get('source_id') == sid for m in job['materials']):
            job['materials'].append({'url': source.get('url') or sid, 'source_id': sid, 'title': source['title'],
                'status': 'provided', 'provider': source['provider'], 'payload_object': source['payload_object'],
                'subject_company': source.get('subject_company', source['company']), 'needs': []})
    if not job.get('discovery'):
        save('wiki_discovering')
        try:
            job['discovery'] = (discovery_fn or discover)(wiki, {**task, 'owner': owner}, context, max(1, min(240, remaining() * .4)), checkpoint)
        except Exception as error:
            job['failures'].append({'stage': 'discovery', 'reason': str(error), 'runtime_object': getattr(error, 'runtime_object', None)})
            job['discovery'] = {'candidates': [], 'search_log': [], 'excluded': [], 'gaps': ['实时公开搜索未完成']}
        save('wiki_discovered')
    candidates = list(job.get('candidates', [])) + list(job['discovery']['candidates']) + job.get('resume_candidates', [])
    known_urls = {c['url'] for c in candidates}
    # Official directories are discovered independently; known documents are
    # fetched again on updates to detect revisions at an unchanged URL.
    seeds = list(request['seed_urls'])
    if request['intent'] == 'update':
        seeds += [s['url'] for s in st.get('sources', {}).values() if s['company'] == company and
                  s['state'] == 'available' and s.get('url', '').startswith('https://') and s['provider'] not in ('slack', 'claude', 'codex')]
    for url in seeds:
        if url not in known_urls:
            candidates.append({'url': url, 'title': '', 'category': 'official' if urlsplit(url).hostname in job['identity']['official_domains'] else 'media',
                               'subject': company, 'publisher': urlsplit(url).hostname, 'rationale': '用户指定或重要来源复查', 'needs': []})
            known_urls.add(url)
    # Official catalog pages provide actual links even when public search fails.
    for url in job['identity']['catalog_urls']:
        if remaining() < reserve + 15:
            job['skipped'].append({'url': url, 'reason': '预算不足，未检查官方目录'})
            continue
        try:
            saved = next((c for c in job.get('catalog_checks', []) if c['url'] == url), None)
            if saved:
                raw, media, base, receipts = wiki.objects.get(saved['payload_object']), saved.get('media_type', 'text/html'), saved.get('final_url', url), saved.get('receipts', [])
            else:
                raw, media, base, receipts = download(url, timeout=min(30, remaining() - reserve))
            check_payload(raw, media)
            from selectolax.parser import HTMLParser
            from urllib.parse import urljoin
            parsed = HTMLParser(raw)
            for node in parsed.css('a'):
                title = (node.attributes.get('title', '') + ' ' + node.text()).strip()
                if not re.search(r'annual report|earnings release|quarter.*20\d{2}|年度报告|季度业绩', title, re.I):
                    continue
                link = urljoin(base, node.attributes.get('href', ''))
                if link in known_urls:
                    continue
                year = re.search(r'20\d{2}', title)
                period = (year[0] + 'FY') if year and 'annual' in title.lower() else ''
                quarter = re.search(r'(first|second|third|fourth) quarter', title, re.I)
                if year and quarter:
                    period = year[0] + 'Q' + str(['first', 'second', 'third', 'fourth'].index(quarter[1].lower()) + 1)
                compact = re.search(r'(20\d{2})[ _.-]*Q([1-4])', title, re.I)
                if compact:period = compact[1] + 'Q' + compact[2]
                if not period or period not in {n.get('period') for n in job['coverage']}:
                    job.setdefault('catalog_excluded', []).append({'url': link, 'title': title, 'reason': '目录项期间未明确或不在本次范围'})
                    continue
                candidates.append({'url': link, 'title': (company + ' · ' + period + ' ' + title) if period else title, 'category': 'official', 'subject': company,
                                   'publisher': job['identity']['name'], 'rationale': '公司官方目录', 'period': period,
                                   'discovery_basis': 'issuer_catalog',
                                   'needs': [n['id'] for n in job['coverage'] if n.get('period') == period]})
                known_urls.add(link)
            if not saved:
                job.setdefault('catalog_checks', []).append({'url': url, 'payload_object': wiki.objects.put(raw), 'receipts': receipts, 'media_type': media, 'final_url': base})
        except Exception as error:
            job['failures'].append({'url': url, 'stage': 'catalog', 'reason': str(error), **failure_details(error), 'receipts': getattr(error, 'receipts', [])})
    # Preserve full candidate inventory before applying budget/size limits.
    job['candidates'] = list({c['url']: c for c in candidates}.values())
    save('wiki_acquiring')
    done = {m['url'] for m in job['materials'] if m.get('source_id')}
    known_urls = {c['url'] for c in job['candidates']}
    processed = set(job.get('processed_urls', []))
    index = 0
    while True:
        if index >= len(job['candidates']):
            coverage_for(job['coverage'], job['materials'])
            missing = [n for n in job['coverage'] if n['status'] == 'gap']
            if job.get('supplemental_discovery') or not missing or len(done) >= request['max_documents'] or remaining() < reserve + 30:
                break
            supplement_context = {**context, 'supplemental': True, 'needs': job['coverage'], 'missing_needs': missing,
                'previous_candidates': job['candidates'], 'failures': job['failures'],
                'instruction': '仅补查 missing_needs。避开已失败的同一网址，每个缺口最多两个新候选。优先原发布方的其他格式或明确署名的公开转载；保留 original_url 和 alternative_of。不能把搜索摘要当作原件。'}
            save('wiki_discovering')
            try:
                extra = (discovery_fn or discover)(wiki, {**task, 'owner': owner}, supplement_context, min(240, remaining() - reserve - 15), checkpoint)
                job['supplemental_discovery'] = extra
                counts = {n['id']: 0 for n in missing}
                for item in extra['candidates']:
                    matching = [n for n in counts if n in item.get('needs', []) or
                        any(m['id'] == n and m.get('period') and m['period'] == item.get('period') for m in missing)]
                    if item['url'] in known_urls or not matching or any(counts[n] >= 2 for n in matching):
                        continue
                    for n in matching:counts[n] += 1
                    job['candidates'].append({**item, 'discovery_basis': item.get('discovery_basis') or 'gap_search'})
                    known_urls.add(item['url'])
            except Exception as error:
                job['supplemental_discovery'] = {'candidates': [], 'search_log': [], 'gaps': ['缺口补搜未完成'], 'excluded': []}
                job['failures'].append({'stage': 'supplemental_discovery', 'reason': str(error), 'runtime_object': getattr(error, 'runtime_object', None)})
            save('wiki_acquiring')
            continue
        candidate = job['candidates'][index]
        index += 1
        if candidate['url'] in done:
            continue
        replacement = next((m for m in job['materials'] if m.get('source_id') and m.get('alternative_of') == candidate['url'] and
                            st.get('sources', {}).get(m['source_id'], {}).get('origin_relation') in ('publisher_version', 'linked_original')), None)
        if replacement:
            # Recovery already has the usable publication; keep the original
            # failed attempt without re-parsing the same empty landing page.
            for m in job['materials']:
                if m['url'] == candidate['url'] and not m.get('source_id'):m['resolved_by'] = replacement['source_id']
            continue
        if candidate['url'] in processed:
            continue
        if candidate.get('discovery_basis') == 'issuer_catalog' and any(m.get('source_id') and m.get('is_subject') and m.get('provider') == 'official' and
                m.get('period_check') == 'matched_original' and m.get('observed_period') == candidate.get('period') for m in job['materials']):
            job.setdefault('catalog_excluded', []).append({'url': candidate['url'], 'reason': '同一期间已有取得并核对的官方原件'})
            continue
        if remaining() < reserve + 15 or len(done) >= request['max_documents']:
            job['skipped'].append({'url': candidate['url'], 'reason': '本次时间或资料数量预算已用尽'})
            continue
        material = {**candidate, 'status': 'fetching', 'checked_at': utcnow()}
        raw, final_url = None, candidate['url']
        try:
            downloaded = next((m for m in job['materials'] if m['url'] == candidate['url'] and m.get('payload_object') and not m.get('source_id')), None)
            if downloaded:
                raw, media = wiki.objects.get(downloaded['payload_object']), downloaded.get('media_type', '')
                final_url, receipts = downloaded.get('final_url', candidate['url']), downloaded.get('receipts', [])
                job['materials'].remove(downloaded)
            else:
                raw, media, final_url, receipts = download(candidate['url'], timeout=min(45, remaining() - reserve))
            sha = wiki.objects.put(raw)
            material.update(payload_object=sha, receipts=receipts, final_url=final_url, media_type=media, status='downloaded')
            job['materials'].append(material)
            save('wiki_acquiring')
            subject = candidate.get('subject') or company
            registered = jobs.companies()
            identities = [c for c in registered.values() if subject.casefold() in [c['company'].casefold(), c['name'].casefold(), *[a.casefold() for a in c['aliases']]]]
            subject_identity = identities[0] if len(identities) == 1 else None
            if subject_identity:
                subject = subject_identity['company']
            official = subject_identity and urlsplit(final_url).hostname in subject_identity['official_domains']
            category = candidate.get('category', 'media')
            provider = 'official' if official else 'regulatory' if urlsplit(final_url).hostname in REGULATORS else 'industry' if category == 'industry' or urlsplit(final_url).hostname in STATISTICS else 'media'
            check_payload(raw, media)
            doc = parse_original(raw, media, final_url, subject, candidate.get('title', ''), timeout=min(60, remaining()))
            if company != subject:
                doc.id = 'source_' + digest([company, subject, final_url, sha])[:24]
                doc.file_name = doc.id + ('.pdf' if doc.media_type == 'application/pdf' else '.html' if doc.media_type == 'text/html' else '.txt')
            observed_period, body_text = validate_original(doc, candidate, official)
            material['period_check'] = 'matched_original' if observed_period and observed_period == candidate.get('period') else 'requires_review'
            material.update(observed_period=observed_period, is_subject=subject == company,
                            supported_needs=supported_needs(candidate, body_text, provider))
            lineage = provenance(candidate, final_url, raw, sha, subject, observed_period, body_text)
            # Identity from search is a lead. Official provenance requires the
            # registered issuer domain; peer/industry evidence retains its subject.
            source = {**doc.model_dump(), 'company': company, 'subject_company': subject,
                      'provider': provider, 'category': category, 'publisher': candidate.get('publisher', ''),
                      'author': candidate.get('author', ''), **lineage,
                      'declared_period': candidate.get('period', ''), 'payload_object': sha, 'state': 'available',
                      'policy': job['policy'], 'job_id': job['id'], 'review_status': 'unreviewed',
                      'external_id': final_url, 'capture_key': provider + ':' + final_url,
                      'checks': doc.issues, 'available_at': doc.available_at if provider == 'official' else doc.observed_at,
                      'observed_period': observed_period, 'period_check': material['period_check'], 'supported_needs': material['supported_needs']}
            with wiki.store.connect(write=True) as db:
                fence(db)
                prior = next((s for s in reversed(list(state(db, 'sources').values())) if s['company'] == company and s.get('url') == final_url and s['state'] == 'available'), None)
                if prior and prior['digest'] == sha:
                    source = prior
                    material['status'] = 'unchanged'
                else:
                    # Same bytes at another URL belong to one content group.
                    duplicate = next((s for s in state(db, 'sources').values() if s['digest'] == sha), None)
                    if duplicate:source['origin_group'] = duplicate['origin_group']
                    if prior:
                        source.update(revision_of=prior['id'], available_at=utcnow())
                    source['record_object'] = wiki.objects.json({k: source[k] for k in ('id', 'provider', 'digest', 'payload_object', 'blocks', 'subject_company', 'publisher', 'original_url', 'retrieved_url', 'origin_group', 'origin_relation', 'alternative_of', 'discovery_basis')})
                    changes = [change('sources', source['id'], source)]
                    if prior:
                        changes.append(change('sources', prior['id'], {**prior, 'state': 'superseded', 'changed_at': utcnow()}))
                    # Original financial extraction remains issuer-specific.
                    if provider == 'official':
                        destination = wiki.desk.files / doc.file_name
                        destination.write_bytes(raw)
                        db.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?)', (doc.id, doc.company, source['available_at'], canonical(doc)))
                        for metric in extract_pdd_metrics(doc):
                            db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)', (metric.id, doc.company, doc.id, canonical(metric)))
                    wiki._emit(db, company, 'source.acquired', changes, details={'job_id': job['id'], 'candidate': candidate})
                    if prior:
                        wiki._source_impacts(db, prior['id'], '主动更新发现原始资料修订')
                    material['status'] = 'revised' if prior else 'acquired'
                material.update(source_id=source['id'], provider=source['provider'], subject_company=subject,
                                parse_issues=source.get('issues', []), origin_group=source['origin_group'],
                                acquisition_result='alternative_acquired' if candidate.get('alternative_of') else 'acquired')
                check = {'id': digest([company, candidate['url']]), 'company': company, 'url': candidate['url'],
                         'source_id': source['id'], 'last_success': utcnow(), 'digest': sha, 'job_id': job['id']}
                wiki._emit(db, company, 'source.checked', [change('source_checks', check['id'], check)])
            done.add(candidate['url'])
            for failure in job['failures']:
                if candidate.get('alternative_of') and lineage['origin_relation'] in ('publisher_version', 'linked_original') and failure.get('url') == candidate['alternative_of']:
                    failure['resolved_by'] = source['id']
        except Conflict:
            raise
        except Exception as error:
            details = failure_details(error)
            if raw is not None and details['error_type'] == 'download_error':
                details.update(error_type='parse_failed', phase='parse', next_action='parse_or_alternative')
            material.update(status='failed', error=str(error), receipts=getattr(error, 'receipts', None) or material.get('receipts', []), **details)
            job['failures'].append({'url': candidate['url'], 'stage': 'acquisition', 'reason': str(error), **details})
            # At most two alternate routes per original; keep their distinct raw
            # bytes and attempts, even when they later join one publication group.
            for alt in alternative_candidates(candidate, raw, final_url):
                parent = candidate.get('fallback_root') or candidate['url']
                count = sum(c.get('fallback_root') == parent for c in job['candidates'])
                if alt['url'] not in known_urls and count < 2:
                    job['candidates'].insert(index, {**alt, 'fallback_root': parent})
                    known_urls.add(alt['url'])
        if material not in job['materials']:
            job['materials'].append(material)
        processed.add(candidate['url'])
        job['processed_urls'] = sorted(processed)
        save('wiki_acquiring')
    acquired = [m for m in job['materials'] if m.get('source_id')]
    coverage_for(job['coverage'], job['materials'])
    unresolved = [f for f in job['failures'] if not f.get('resolved_by')]
    job['checks'] = [{'kind': 'acquisition', 'status': 'passed' if not unresolved else 'incomplete', 'checked': len(acquired)},
                     {'kind': 'coverage', 'status': 'incomplete' if any(n['status'] == 'gap' for n in job['coverage']) else 'materials_found',
                      'note': '找到资料不等于命题已核验；正文、数字与引文在提案检查及人工审核中验证'},
                     {'kind': 'source_identity', 'status': 'recorded', 'note': '官方域名独立核对；其他来源保留主体与类别，不能升级为公司披露事实'}]
    save('wiki_checking')
    source_ids = sorted({m['source_id'] for m in acquired if m['status'] != 'unchanged' or request['intent'] == 'build'})
    # Unchanged but uncompiled sources still need a source interpretation.
    existing_notes = {p['id'] for p in pages}
    source_ids += [m['source_id'] for m in acquired if 'source-note:' + m['source_id'] not in existing_notes and m['source_id'] not in source_ids]
    partial = bool(unresolved or job['skipped'] or job['discovery'].get('gaps') or job.get('supplemental_discovery', {}).get('gaps') or any(n['status'] == 'gap' for n in job['coverage']))
    result = {'execution_status': 'partial' if partial else 'completed', 'job_id': job['id']}
    # Rechecking unchanged sources must not manufacture a second pending draft.
    if acquired and ((request['intent'] == 'update' and all(m['status'] == 'unchanged' for m in acquired)) or job.get('resumed_from')):
        with wiki.store.connect() as db:
            current = state(db)
            for pending in sorted(current.get('proposals', {}).values(), key=lambda p: p['created_at'], reverse=True):
                if pending['company'] != company or pending['status'] != 'pending' or pending['request']['policy'] != job['policy']:
                    continue
                covered = {c['source_id'] for d in pending['request']['changes'] for c in d['citations']}
                if not {m['source_id'] for m in acquired} <= covered:
                    continue
                try:
                    from .contracts import ProposalInput
                    wiki._validate(db, ProposalInput.model_validate(pending['request']))
                except (ValueError, KeyError, OSError):
                    continue
                result.update(proposal_id=pending['id'], reused_proposal=True)
                save('wiki_review_ready')
                return result
    if acquired and job.get('resume_compilation_object'):
        cached = json.loads(wiki.objects.get(job['resume_compilation_object']))
        from .contracts import ProposalInput
        previous_request = ProposalInput.model_validate(cached['wiki_proposal'])
        covered = {c.source_id for d in previous_request.changes for c in d.citations}
        if {m['source_id'] for m in acquired} <= covered and previous_request.policy.model_dump() == job['policy']:
            try:
                with wiki.store.connect() as db:wiki._validate(db, previous_request)
            except (ValueError, KeyError, OSError):
                pass
            else:
                # Reuse frozen model prose only after today's complete validation;
                # a repaired parser/check does not require regenerating analysis.
                previous_request.operation_id = 'compile:' + task['id']
                result.update({k: v for k, v in cached.items() if k in ('model_output', 'input_object', 'number_catalog_object')},
                              wiki_proposal=previous_request.model_dump(mode='json'), reused_compilation=True)
                job['checks'].append({'kind':'publication','status':'awaiting_validation','note':'复用已冻结的完整草稿，重新核验当前依据与目标版本'})
                save('wiki_review_ready')
                return result
    if source_ids and remaining() >= 15:
        save('wiki_compiling')
        compile_task = {**task, 'request': {**task['request'], 'budget_seconds': max(10, int(remaining())),
            'parameters': {'source_ids': source_ids, 'research_focus': request['research_focus'],
                           'intent': request['intent'], 'as_of': request.get('as_of'), 'policy': job['policy']}}}
        result.update((compile_fn or compile_sources)(wiki, compile_task, checkpoint))
        job['checks'].append({'kind': 'publication', 'status': 'awaiting_validation', 'note': '版本、数字、引文与依赖必须通过统一提案校验后进入审核'})
    elif source_ids:
        result['execution_status'] = 'partial'
        job['skipped'].append({'stage': 'compilation', 'reason': '资料已保存，整理预算不足，可继续任务'})
    elif not acquired:
        result['execution_status'] = 'partial'
        job['failures'].append({'stage': 'coverage', 'reason': '本次没有取得可用原件'})
    else:
        result['no_change'] = not partial
    save('wiki_review_ready' if result.get('wiki_proposal') else 'wiki_check_finished', elapsed_seconds=round(time.monotonic() - started, 2))
    return result

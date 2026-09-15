from fastapi import APIRouter, HTTPException, Request
from pitr.desk.contracts import Command, TaskInput, AgentCommand
from .contracts import CaptureEnvelope, ProposalInput, DecisionRecord, IssueInput, IssueDecision, QueryInput, AnswerInput, InspectionFeedback, ValidateUse, WikiJobRequest, WikiUpdateSchedule, CompanyRegistration


def router(wiki, queue):
    api = APIRouter(prefix='/api/desk/wiki', tags=['company-wiki'])

    def human(request):
        # The public agent surface is explicitly capability-limited. Existing
        # localhost workbench review shares the same human decision boundary.
        if request.headers.get('x-pitr-actor') == 'agent':
            raise HTTPException(403, 'Agent 无发布或处理审核权限')

    from .jobs import WikiJobs
    jobs = WikiJobs(wiki, queue)

    @api.get('/workspace')
    def workspace(company: str = 'PDD', as_of: str | None = None):
        from .workspace import workspace
        return workspace(wiki, company.upper(), as_of)

    @api.get('/page')
    def page(id: str, version: int | None = None, as_of: str | None = None):
        from .workspace import page
        return page(wiki, id, version, as_of)

    @api.get('/log')
    def log(company: str = 'PDD', as_of: str | None = None):
        from .workspace import log
        return log(wiki, company.upper(), as_of)

    @api.get('/sources/{sid}')
    def source(sid: str, as_of: str | None = None):
        from .workspace import source
        return source(wiki, sid, as_of)

    @api.get('/sources/{sid}/file')
    def original(sid: str, as_of: str | None = None):
        from fastapi.responses import Response
        from .workspace import source
        record = source(wiki, sid, as_of)
        return Response(wiki.objects.get(record['payload_object']), media_type=record.get('media_type', 'text/plain'),
                        headers={'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    @api.get('/companies')
    def companies():
        return list(jobs.companies().values())

    @api.post('/companies')
    def register_company(body: CompanyRegistration, request: Request):
        human(request)
        return jobs.register(body)

    @api.get('/jobs')
    def job_list(company: str = 'PDD'):
        return jobs.list(company.upper())

    @api.post('/jobs')
    def create_job(body: WikiJobRequest):
        return jobs.create(body)

    @api.get('/jobs/{jid}')
    def get_job(jid: str):
        return jobs.get(jid)

    @api.post('/jobs/{jid}/cancel')
    def cancel_job(jid: str, body: Command):
        queue.cancel(jobs.get(jid)['task_id'])
        return jobs.get(jid)

    @api.post('/jobs/{jid}/resume')
    def resume_job(jid: str, body: Command):
        previous = jobs.get(jid)
        return jobs.create(WikiJobRequest.model_validate({**previous['request'], 'operation_id': body.operation_id,
                            'resume_job_id': jid}), notification_event_id=previous.get('notification_event_id', ''))

    @api.get('/schedules')
    def schedules(company: str = 'PDD'):
        from .store import get
        with wiki.store.connect() as db:
            return get(db, 'update_schedules', company.upper())

    @api.post('/schedules')
    def update_schedule(body: WikiUpdateSchedule):
        return jobs.schedule(body)

    @api.post('/schedules/{company}/cancel')
    def cancel_schedule(company: str, body: Command):
        return jobs.cancel_schedule(company.upper(), body.operation_id)

    @api.get('/proposals/{pid}')
    def get_proposal(pid: str):
        from .store import get
        with wiki.store.connect() as db:
            proposal = get(db, 'proposals', pid)
        if not proposal:
            raise KeyError('提案不存在')
        return proposal

    @api.get('')
    def overview(company: str = 'PDD'):
        return wiki.overview(company.upper())

    @api.get('/pages')
    def pages(company: str = 'PDD', as_of: str | None = None):
        return wiki.list(company.upper(), as_of)

    @api.get('/versions/{object_id:path}')
    def versions(object_id: str, as_of: str | None = None):
        return wiki.history(object_id, as_of)

    @api.get('/lifecycle/{object_id:path}')
    def lifecycle(object_id: str, as_of: str | None = None):
        return wiki.history(object_id, as_of)

    @api.get('/search')
    def search(q: str, company: str = 'PDD', as_of: str | None = None, hybrid: bool = False):
        from .search import search
        return search(wiki, company.upper(), q, as_of=as_of, hybrid=hybrid)

    @api.get('/observations')
    def observations(company: str = 'PDD'):
        import json
        with wiki.store.connect() as db:
            return [json.loads(r['body']) for r in db.execute('SELECT body FROM observations WHERE company=?',(company,))]

    @api.get('/inspection-metrics')
    def inspection_metrics(company: str = 'PDD'):
        from .evaluation import inspection_metrics
        return inspection_metrics(wiki, company)

    @api.post('/validate')
    def validate_use(body: ValidateUse):
        return wiki.validate_use(body.company,[r.model_dump() for r in body.references],body.as_of)

    @api.get('/policy')
    def policy():
        return wiki.policy()

    @api.post('/captures')
    def capture(body: CaptureEnvelope):
        return wiki.capture(body)

    @api.post('/sources/{sid}/classify')
    def classify(sid: str, body: dict):
        return wiki.classify(sid, body['company'].upper(), body['operation_id'])

    @api.post('/sources/{sid}/compile')
    def compile(sid: str, body: AgentCommand):
        from .store import get
        with wiki.store.connect() as db:
            source = get(db, 'sources', sid)
        if not source or not source['company']:
            raise ValueError('请先归类公司')
        return queue.enqueue(TaskInput(operation_id=body.operation_id, workflow='wiki_compile',
            company=source['company'], parameters={'source_ids': [sid]}, budget_seconds=600,
            agent_provider=body.agent_provider,model=body.model))

    @api.post('/proposals')
    def propose(body: ProposalInput):
        return wiki.propose(body)

    @api.post('/proposals/{pid}/review')
    def review(pid: str, body: DecisionRecord, request: Request):
        human(request)
        return wiki.review(pid, body)

    @api.post('/issues')
    def report(body: IssueInput):
        return wiki.report(body)

    @api.post('/issues/{iid}/decisions')
    def decide(iid: str, body: IssueDecision, request: Request):
        human(request)
        return wiki.issue_decision(iid, body)

    @api.post('/query')
    def query(body: QueryInput):
        from .research import query
        return query(wiki, body)

    @api.post('/query/{query_id}/answer')
    def generate(query_id: str, body: AgentCommand):
        from .store import get
        with wiki.store.connect() as db:
            reading = get(db, 'uses', query_id)
        if not reading or not reading.get('items'):
            raise ValueError('没有可用的 Wiki 阅读上下文')
        return queue.enqueue(TaskInput(operation_id=body.operation_id, workflow='wiki_answer',
            company=reading['company'], parameters={'query_id':query_id}, budget_seconds=300,
            agent_provider=body.agent_provider,model=body.model))

    @api.post('/answers')
    def answer(body: AnswerInput):
        from .research import save_answer
        return save_answer(wiki, body)

    @api.post('/inspections')
    def inspect(body: dict):
        if body.get('kind', 'rules') not in ('rules', 'semantic'):
            raise ValueError('未知巡检类型')
        return queue.enqueue(TaskInput(operation_id=body['operation_id'], workflow='wiki_inspect',
            company=body.get('company', 'PDD'), parameters={'kind': body.get('kind', 'rules')}, budget_seconds=600,
            agent_provider=body.get('agent_provider'),model=body.get('model')))

    @api.post('/inspections/{run_id}/feedback')
    def feedback(run_id: str, body: InspectionFeedback, request: Request):
        human(request)
        from .evaluation import record_feedback
        return record_feedback(wiki,run_id,body)

    @api.post('/rebuild')
    def rebuild(body: Command, request: Request):
        human(request)
        return wiki.rebuild()

    @api.post('/outbox/{job_id}/retry')
    def retry(job_id: str, body: Command):
        with wiki.store.connect(write=True) as db:
            db.execute("UPDATE wiki_outbox SET status='pending',next_at=0,attempts=0 WHERE id=? AND status='failed'", (job_id,))
        return {'id': job_id, 'status': 'pending'}

    return api

"""Versioned owner API. Agent capabilities are served on another loopback port."""
from contextlib import asynccontextmanager
import json
import asyncio
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, Query, HTTPException, Request
from fastapi.responses import Response, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from pitr.application.service import Workstation
from pitr.domain.common import Command, Contract, Conflict, Forbidden, uid, canonical
from pitr.domain.contracts import (
    Scope, Ref, Subject, SourceVersion, ResearchCase, Run, ReportDocument, ReportView,
    CreateCase, UpdateInput, StartRun, ContinueRun, ReviseReport, ExportRequest, Decide,
)
from pitr.domain.views import TraceView, TraceEvent, TraceSpan, CompanyView
from pitr.application.trace import trace_view
from pitr.application.views import company_view
from pitr.application.evaluation import HumanEvaluation,BlindPack


class SubjectCommand(Command):
    identity: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    official_domains: list[str] = Field(default_factory=list)
    identifiers: dict[str,str] = Field(default_factory=dict)
    expected_revision: int = Field(default=0,ge=0)
    evidence: list[Ref] = Field(default_factory=list)


class FetchSource(Command):
    url: str
    title: str = ''
    subjects: list[str] = Field(default_factory=list)


class DiscoverSubjects(Command):
    name: str
    market: Literal['SEC','HKEX','SSE','SZSE','BSE','CNINFO']
    code: str = ''


class WithdrawSource(Command):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1)


class DiscoverSources(Command):
    subject: str
    adapter: str
    since: str = ''
    until: str = ''
    urls: list[str] = Field(default_factory=list)


class FetchDiscovery(Command):
    discovery_id: str
    index: int = Field(ge=0)


class SlackConfiguration(Contract):
    enabled: bool
    team_id: str
    user_id: str
    channel_ids: list[str]
    app_token: str = ''
    bot_token: str = ''


class SettingsCommand(Command):
    agent_provider: Literal['codex','claude'] | None = None
    agent_models: dict[str,str|None] | None = None
    sec_user_agent: str | None = None
    slack: SlackConfiguration | None = None


class SubscriptionCommand(Command):
    id: str | None = None
    expected_revision: int = Field(default=0,ge=0)
    subject: str
    url: str
    enabled: bool = True
    interval_hours: int = Field(default=24,ge=1,le=720)


class CalibrateBudget(Command):
    depth: Literal['interactive','standard','deep']
    apply: bool = False


def scoped(subject='', mode='live', as_of=None):
    return Scope(subjects=[subject] if subject else [],mode=mode,as_of=as_of,allow_public_search=mode!='historical')


def create_app(root,*,station=None,workers=True,auth=None,web_dir=None):
    station=station or Workstation(root)
    @asynccontextmanager
    async def lifespan(app):
        resources=[]
        if workers:
            from .tool_http import ToolServer
            from pitr.research.queue import ResearchQueue
            from pitr.artifacts.queue import ExportQueue
            from pitr.application.watch import WatchWorker
            from .slack import SlackConnection
            resources=[ToolServer(station),ResearchQueue(station),ExportQueue(station),WatchWorker(station),SlackConnection(station)]
            if station.agents:station.agents.refresh(background=True)
            from pitr.lab.news.worker import NewsWorker
            worker=NewsWorker(app.state.news);worker.start();resources.append(worker)
        yield
        for resource in reversed(resources):
            try:
                (getattr(resource,'close',None) or getattr(resource,'stop'))()
            except Exception:pass
    app=FastAPI(title='PITR Research',version='1.0',lifespan=lifespan)
    app.state.station=station
    for error,status in [(Conflict,409),(Forbidden,403),(ValueError,422),(KeyError,404)]:
        async def handler(request,exc,status=status):return JSONResponse(status_code=status,content={'detail':str(exc)})
        app.add_exception_handler(error,handler)
    routes=APIRouter(prefix='/api/v1')

    @routes.get('/evaluations')
    def evaluations():
        from pitr.application.evaluation import summary
        return summary(station)

    @routes.post('/evaluations')
    def evaluate(body:HumanEvaluation):
        from pitr.application.evaluation import record
        return record(station,body)

    @routes.post('/evaluations/blind-pack')
    def evaluation_pack(body:BlindPack):
        from pitr.application.evaluation import blind_pack
        return Response(blind_pack(station,body),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="pitr-blind-review.zip"'})

    @routes.get('/health')
    def health():return {'status':'ok','schema':'research.1'}

    @routes.get('/subjects',response_model=list[Subject])
    def subjects():return station.store.list('subject')

    @routes.get('/source-adapters')
    def source_adapters():
        from pitr.adapters.sources.protocol import adapters
        return {'items':[{'name':a.name,'markets':a.markets} for a in adapters().values()]}

    @routes.post('/subjects',response_model=Subject)
    def register(body:SubjectCommand):return station.register_subject(**body.model_dump(mode='json'))

    @routes.post('/subjects/discover')
    def discover_subjects(body:DiscoverSubjects):
        from pitr.research.discovery import identities
        return identities(station,**body.model_dump())

    @routes.get('/sources')
    def sources(subject:str='',mode:Literal['live','historical']='live',as_of:str|None=None,all_revisions:bool=False):return station.source_list(scoped(subject,mode,as_of),all_revisions)

    @routes.post('/sources/fetch',response_model=SourceVersion)
    def fetch(body:FetchSource):return station.fetch_source(**body.model_dump())

    @routes.post('/sources/discover')
    def discover(body:DiscoverSources):
        from pitr.research.discovery import directory
        return directory(station,**body.model_dump())

    @routes.post('/sources/discovery-fetch',response_model=SourceVersion)
    def discovery_fetch(body:FetchDiscovery):
        from pitr.research.discovery import fetch_item
        return fetch_item(station,**body.model_dump())

    @routes.post('/sources/upload',response_model=SourceVersion)
    async def upload(file:UploadFile=File(),operation_id:str=Form(),subjects:str=Form('[]')):
        raw=await file.read(40_000_001)
        return station.import_source(raw,file.content_type or 'application/octet-stream',title=file.filename or '',
                                     subjects=json.loads(subjects),operation_id=operation_id)

    @routes.get('/sources/{source_id}/revisions/{revision}',response_model=SourceVersion)
    def source(source_id:str,revision:int):return station.store.get(Ref(id=source_id,revision=revision),'source')

    @routes.get('/sources/{source_id}/revisions/{revision}/original')
    def original(source_id:str,revision:int):
        source=station.store.get(Ref(id=source_id,revision=revision),'source')
        return Response(station.store.read_blob(source.digest),media_type=source.media_type,
            headers={'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    @routes.post('/sources/{source_id}/withdraw')
    def withdraw(source_id:str,body:WithdrawSource):return station.withdraw_source(Ref(id=source_id,revision=body.expected_revision),body.operation_id,body.reason)

    @routes.get('/cases',response_model=list[ResearchCase])
    def cases():return station.cases()

    @routes.post('/cases',response_model=ResearchCase)
    def create(body:CreateCase):return station.create_case(body)

    @routes.get('/cases/{case_id}',response_model=ResearchCase)
    def case(case_id:str):return station.get_case(case_id)

    @routes.post('/cases/{case_id}/inputs',response_model=ResearchCase)
    def update(case_id:str,body:UpdateInput):return station.update_input(case_id,body)

    @routes.post('/cases/{case_id}/runs',response_model=Run)
    def start(case_id:str,body:StartRun):return station.start_run(case_id,body)

    @routes.get('/runs',response_model=list[Run])
    def runs(case_id:str|None=None):return station.runs(case_id)

    @routes.get('/runs/{run_id}',response_model=Run)
    def run(run_id:str):return station.get_run(run_id)

    @routes.post('/runs/{run_id}/cancel',response_model=Run)
    def cancel(run_id:str,body:Command):return station.cancel(run_id,body.operation_id)

    @routes.post('/runs/{run_id}/continue',response_model=Run)
    def resume(run_id:str,body:ContinueRun):return station.continue_run(run_id,body)

    @routes.get('/runs/{run_id}/trace',response_model=TraceView)
    def trace(run_id:str,at_seq:int|None=Query(default=None,ge=0)):
        return trace_view(station,run_id,at_seq)

    @routes.get('/runs/{run_id}/trace/spans/{span_id}',response_model=TraceSpan)
    def trace_span(run_id:str,span_id:str,at_seq:int|None=Query(default=None,ge=0)):
        view=trace_view(station,run_id,at_seq,detail_id=span_id)
        for value in view.spans:
            if value.id==span_id:return value
        raise KeyError('该回放位置没有此节点')

    @routes.get('/runs/{run_id}/trace/records',response_model=list[TraceEvent])
    def trace_records(run_id:str,after:int=Query(default=0,ge=0)):
        return station.trace(run_id,after)

    @routes.get('/runs/{run_id}/trace/events')
    async def trace_events(run_id:str,request:Request,after_seq:int=Query(default=0,ge=0)):
        station.get_run(run_id)
        last=request.headers.get('last-event-id','0')
        cursor=max(after_seq,int(last) if last.isdecimal() else 0)
        async def events():
            nonlocal cursor
            while not await request.is_disconnected():
                rows=await asyncio.to_thread(station.trace,run_id,cursor)
                for event in rows:
                    cursor=event['seq']
                    # The subscription invalidates the read model; node payloads load on selection.
                    notice={**event,'data':{k:v for k,v in event['data'].items() if k in ('id','span_id','generation')}}
                    yield f"id: {cursor}\nevent: trace\ndata: {canonical(notice)}\n\n"
                if not rows:yield ': heartbeat\n\n'
                await asyncio.sleep(.7)
        return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @routes.get('/companies/{subject}/view',response_model=CompanyView)
    def company(subject:str,mode:Literal['live','historical']='live',as_of:str|None=None):
        return company_view(station,subject,scoped(subject,mode,as_of))

    @routes.get('/reports',response_model=list[ReportDocument])
    def reports():return station.store.list('report')

    @routes.get('/reports/{report_id}/revisions',response_model=list[ReportDocument])
    def history(report_id:str):return [r for r in station.store.list('report',all_revisions=True) if r.id==report_id]

    @routes.get('/reports/{report_id}/revisions/{revision}',response_model=ReportView)
    def report(report_id:str,revision:int):return station.reports.view(Ref(id=report_id,revision=revision))

    @routes.post('/reports/{report_id}/revisions',response_model=ReportDocument)
    def revise(report_id:str,body:ReviseReport):return station.reports.revise(report_id,body)

    @routes.get('/objects/{object_id}/revisions/{revision}')
    def object(object_id:str,revision:int):
        ref=Ref(id=object_id,revision=revision)
        return {'object':station.store.get(ref),'dependencies':station.store.closure(ref),'current_validity':station.store.validity(ref)}

    @routes.get('/review')
    def review():return station.reports.groups()

    @routes.post('/review/{group_id}/decisions')
    def decide(group_id:str,body:Decide):return station.reports.decide(group_id,body)

    @routes.post('/exports')
    def export(body:ExportRequest):return station.reports.export(body)

    @routes.post('/exports/{job_id}/retry')
    def retry(job_id:str,body:Command):return station.reports.retry_export(job_id,body.operation_id)

    @routes.get('/exports')
    def exports():
        with station.store.connect() as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM exports ORDER BY rowid DESC')]

    @routes.get('/artifacts/{artifact_id}/download')
    def download(artifact_id:str):
        artifact=station.store.get(artifact_id,'artifact')
        return Response(station.store.read_blob(artifact.digest),media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition':f'attachment; filename="report-{artifact.report.id}-r{artifact.report.revision}.docx"','ETag':artifact.digest})

    @routes.get('/artifacts/{artifact_id}/render/{page}')
    def rendered(artifact_id:str,page:str):
        artifact=station.store.get(artifact_id,'artifact');render=artifact.manifest['render']
        if page=='pdf':return Response(station.store.read_blob(render['pdf_digest']),media_type='application/pdf')
        index=int(page)-1
        if index<0 or index>=len(render['page_digests']):raise KeyError('页码不存在')
        return Response(station.store.read_blob(render['page_digests'][index]),media_type='image/png')

    @routes.get('/knowledge')
    def knowledge(subject:str='',mode:Literal['live','historical']='live',as_of:str|None=None):return station.knowledge(scoped(subject,mode,as_of))

    @routes.get('/graph')
    def graph(subject:str='',mode:Literal['live','historical']='live',as_of:str|None=None):
        items=station.knowledge(scoped(subject,mode,as_of))
        relations=[i for i in items if i.get('kind')=='relationship']
        included={s for i in relations for s in i.get('subjects',[])}
        return {'subjects':[s for s in station.store.list('subject') if s.id in included], 'relations':relations}

    @routes.get('/search')
    def search(q:str='',subject:str='',mode:Literal['live','historical']='live',as_of:str|None=None):return station.search(q,scoped(subject,mode,as_of))

    @routes.get('/today')
    def today():
        with station.store.connect() as db:
            changes=[]
            for row in db.execute("SELECT v.*,r.kind,r.body FROM validity v JOIN revisions r ON r.id=v.id AND r.revision=v.revision WHERE status!='available' AND r.kind IN ('source','report','assertion','model') ORDER BY updated_at DESC LIMIT 100"):
                obj=json.loads(row['body']);change={k:row[k] for k in row.keys() if k!='body'}
                change['title']=obj.get('title','');change['case_id']=obj.get('case_id')
                if not change['case_id']:
                    related=db.execute('SELECT r.case_id FROM run_objects o JOIN runs r ON r.id=o.run_id WHERE o.id=? AND o.revision=? ORDER BY r.rowid DESC LIMIT 1',(row['id'],row['revision'])).fetchone()
                    change['case_id']=related[0] if related else None
                changes.append(change)
        return {'runs':station.runs()[:30],'reviews':[g for g in station.reports.groups() if g['status']=='pending'],
            'changes':changes,'cases':station.cases()[:20]}

    @routes.get('/settings')
    def settings():
        from pitr.artifacts.render import doctor
        return {'settings':station.settings.public(),'agents':station.agents.status() if station.agents else {'agents':[]},
            'documents':doctor(),'budgets':{d:station.budget(d) for d in ('interactive','standard','deep')}}

    @routes.post('/settings')
    def save_settings(body:SettingsCommand):
        values=body.model_dump(exclude_none=True,exclude={'operation_id','slack'})
        if body.slack:
            values.update({'slack_'+key:value for key,value in body.slack.model_dump().items()})
        def save(db):
            station.settings.save(values)
            return station.settings.public()
        result=station.store.once(body.operation_id,{'command':'settings','body':body},save)
        if body.slack and getattr(station,'slack',None):
            station.slack.stop(disable=False)
            if body.slack.enabled:station.slack.start(enable=False)
        return result

    @routes.post('/agents/refresh')
    def refresh(body:Command):return station.agents.refresh(background=True) if station.agents else {'agents':[]}

    @routes.post('/budgets/calibrate')
    def calibrate_budget(body:CalibrateBudget):
        from pitr.application.evaluation import calibrate
        # Read-only proposals need no command reservation; application is owner initiated.
        if not body.apply:return calibrate(station,body.depth)
        from pitr.research.discovery import cached
        payload={'command':'budget.calibrate','depth':body.depth}
        prior=cached(station,body.operation_id,payload)
        if prior is not None:return prior
        result=calibrate(station,body.depth)
        def save(db):
            if result['status']=='calibrated':
                row=db.execute("SELECT body FROM metadata WHERE key='budgets'").fetchone()
                budgets=json.loads(row[0]) if row else {}
                budgets[body.depth]=result['budget']
                db.execute("INSERT OR REPLACE INTO metadata VALUES('budgets',?)",(canonical(budgets),))
                station.store.event(db,'','budget.calibrated',result)
            return result
        return station.store.once(body.operation_id,payload,save)

    @routes.get('/agents/{provider}/models')
    def models(provider:str):return station.agents.models(provider)

    @routes.get('/maintenance')
    def maintenance():
        with station.store.connect() as db:
            return {'root':str(station.root),'counts':{r[0]:r[1] for r in db.execute('SELECT kind,count(*) FROM revisions GROUP BY kind')},
                'subscriptions':[json.loads(r[0]) for r in db.execute('SELECT body FROM subscriptions')],
                'outbox':[dict(r) for r in db.execute('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 100')],
                'exports':exports(),'changes':today()['changes']}

    @routes.post('/maintenance/rebuild')
    def rebuild(body:Command):
        from pitr.application.maintenance import rebuild
        return rebuild(station.store,body.operation_id)

    @routes.post('/reviews/jobs/{job_id}/retry')
    def retry_review(job_id:str,body:Command):
        def retry(db):
            row=db.execute("SELECT * FROM outbox WHERE id=? AND kind='report_review'",(job_id,)).fetchone()
            if not row:raise KeyError('复核任务不存在')
            if row['status']!='failed':raise Conflict('仅失败的复核可以重试')
            ref=Ref.model_validate(json.loads(row['body'])['report'])
            if station.store.validity(ref,db=db)['status']!='available':raise Conflict('报告依赖已变化，请先继续研究或修订报告')
            db.execute("UPDATE outbox SET status='queued' WHERE id=?",(job_id,))
            return {'id':job_id,'status':'queued'}
        return station.store.once(body.operation_id,{'command':'review.retry','id':job_id},retry)

    @routes.post('/maintenance/backup')
    def backup(body:Command):
        from pitr.application.maintenance import backup
        return Response(backup(station),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="pitr-backup.zip"'})

    @routes.post('/subscriptions')
    def subscription(body:SubscriptionCommand):
        from pitr.application.watch import save_subscription
        return save_subscription(station,body)

    @routes.post('/subscriptions/{subscription_id}/refresh')
    def refresh_source(subscription_id:str,body:Command):
        from pitr.application.watch import refresh
        return refresh(station,subscription_id,body.operation_id)

    app.include_router(routes)
    from pitr.lab.news.service import News
    from pitr.lab.news.api import router
    app.state.news=News(station)
    app.include_router(router(app.state.news))
    web=Path(web_dir) if web_dir else Path(__file__).resolve().parents[3]/'web/dist'
    if (web/'assets').exists():app.mount('/assets',StaticFiles(directory=web/'assets'),name='assets')
    @app.get('/{path:path}')
    def frontend(path:str):
        if path.startswith('api/'):raise HTTPException(404,'接口不存在')
        if (web/'index.html').exists():return FileResponse(web/'index.html')
        return Response('请先构建前端：在 web 目录执行 npm run build',status_code=503)
    if auth:app.add_middleware(type('SessionMiddleware',(),{'__init__':lambda self,app:setattr(self,'wrapped',auth.middleware(app)),
                                                        '__call__':lambda self,scope,receive,send:self.wrapped(scope,receive,send)}))
    return app

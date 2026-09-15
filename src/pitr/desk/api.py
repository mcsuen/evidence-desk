from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from .service import Desk
from .tasks import Queue
from .contracts import *
from .storage import Conflict, canonical


def create_app(root=None, web_dist=None, worker=True, agent_runtime=None):
    root=Path(root or os.environ.get('PITR_DESK_DIR','data/desk_control')).resolve()
    desk=Desk(root);queue=Queue(desk)
    if agent_runtime is not None:
        desk.agents=agent_runtime(desk)
    elif worker:
        from pitr.agent_runtime.runtime import AgentRuntime
        desk.agents=AgentRuntime(desk)
    from pitr.wiki.worker import Worker as WikiWorker
    wiki_worker=WikiWorker(desk.wiki,queue)
    from .integrations import Monitor
    monitor=Monitor(desk,queue)
    @asynccontextmanager
    async def lifespan(app):
        if getattr(desk,'agents',None):desk.agents.refresh(background=True)
        if worker:queue.start();monitor.start();wiki_worker.start();trace_sync.start()
        if worker and read_settings().get('slack_enabled'):
            try:
                await asyncio.to_thread(slack.start, enable=False)
            except ValueError:
                pass  # Failure is visible in the settings page; the desk stays usable.
        yield
        trace_sync.stop()
        monitor.stop()
        wiki_worker.stop()
        queue.stop()
        await asyncio.to_thread(slack.stop, disable=False)
    app=FastAPI(title='PITR Research Desk',version='1.0.0',lifespan=lifespan)
    from .research.api import router as research_router
    app.include_router(research_router(desk,queue))
    from .research.trace.api import router as trace_router
    trace_routes,trace_sync=trace_router(desk);app.include_router(trace_routes)
    app.state.trace_sync=trace_sync
    app.state.desk=desk;app.state.queue=queue
    app.state.wiki_worker=wiki_worker
    from pitr.wiki.api import router as wiki_router
    app.include_router(wiki_router(desk.wiki,queue))

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc!=request.headers.get('host'):
                return JSONResponse({'detail':'仅接受本机工作台的写入请求'},status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request,error):return JSONResponse({'detail':str(error)},status_code=409 if isinstance(error,Conflict) else 422)
    from pitr.agent_runtime.transport import AgentError
    @app.exception_handler(AgentError)
    async def agent_error(request,error):return JSONResponse({'detail':str(error)},status_code=409)

    def runtime():
        if not getattr(desk,'agents',None):raise AgentError('当前服务未启用本机 Agent 桥接')
        return desk.agents
    @app.get('/api/desk/agents')
    def agents():return runtime().status()
    @app.post('/api/desk/agents/refresh')
    def refresh_agents():return runtime().refresh(background=True)
    @app.get('/api/desk/agents/{provider}/models')
    def agent_models(provider: str):return runtime().models(provider)
    @app.exception_handler(KeyError)
    async def missing(request,error):return JSONResponse({'detail':str(error)},status_code=404)

    @app.get('/api/desk/home')
    def home():return desk.home()
    @app.get('/api/desk/documents/{sid}')
    def document(sid: str):return desk.document(sid)
    @app.get('/api/desk/documents/{sid}/file')
    def original(sid: str):
        d=desk.document(sid)
        return FileResponse(desk.files/d.file_name,media_type=d.media_type,headers={'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'"})
    @app.post('/api/desk/documents')
    def source(req: SourceInput):
        from .sources import fetch
        raw,media,url=fetch(req.url,contact=read_settings().get('sec_user_agent',''))
        return desk.ingest(raw,media,url,req.company,req.title)
    @app.post('/api/desk/documents/upload')
    async def upload_source(file: UploadFile=File(),company: str=Form('PDD')):
        raw=await file.read(40_000_001)
        if len(raw)>40_000_000:raise ValueError('原件超过 40 MB')
        return desk.ingest(raw,file.content_type or 'application/pdf','upload:'+file.filename,company,file.filename)
    @app.post('/api/desk/documents/{sid}/withdraw')
    def withdraw(sid: str):return desk.withdraw(sid)
    @app.post('/api/desk/tasks')
    def enqueue(req: TaskInput):return queue.enqueue(req)
    @app.get('/api/desk/tasks')
    def tasks(company: str='PDD',workflow: str='',period: str=''):
        with desk.store.connect() as db:items=[json.loads(r['body']) for r in db.execute('SELECT body FROM tasks ORDER BY rowid DESC')]
        return [{k:v for k,v in t.items() if k not in ('result','trace')} for t in items
            if t['request']['company']==company and (not workflow or t['request']['workflow']==workflow)
            and (not period or t['request']['parameters'].get('period')==period)]
    @app.post('/api/desk/tasks/{tid}/cancel')
    def cancel(tid: str):return queue.cancel(tid)
    @app.get('/api/desk/tasks/{tid}')
    def task(tid: str):
        with desk.store.connect() as db:
            r=db.execute('SELECT body FROM tasks WHERE id=?',(tid,)).fetchone()
            if not r:raise KeyError('任务不存在')
            return json.loads(r['body'])
    @app.get('/api/desk/tasks/{tid}/events')
    def events(tid: str):
        async def stream():
            previous=''
            while True:
                data=task(tid);serialized=canonical(data)
                if serialized!=previous:yield 'data: '+serialized+'\n\n';previous=serialized
                if data['status'] in ('completed','failed','cancelled'):break
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream')


    from pitr.integrations.slack.settings import SettingsFile
    private=desk.root/'private'
    settings_file=desk.agents.settings if getattr(desk,'agents',None) else SettingsFile(private/'settings.json')
    read_settings=settings_file.read
    from .slack import Slack
    from pitr.integrations.slack.settings import MANIFEST
    slack=Slack(desk,queue,read_settings,settings_file.save)
    app.state.slack=slack
    from pitr.integrations.slack import WorkflowUpdate
    wiki_worker.slack_relay=lambda key,body:slack.publish(body['event_id'],'wiki:'+key,WorkflowUpdate(text=body['text']))
    @app.get('/api/desk/slack-manifest')
    def manifest():return Response(MANIFEST,media_type='application/yaml',headers={'Content-Disposition':'attachment; filename="pitr-slack-manifest.yaml"'})
    @app.get('/api/desk/slack')
    def slack_status():return slack.status()
    @app.post('/api/desk/slack/connect')
    def slack_connect():return slack.start()
    @app.post('/api/desk/slack/disconnect')
    def slack_disconnect():slack.stop();return slack.status()
    @app.post('/api/desk/slack/check')
    def slack_check():return slack.check()
    @app.post('/api/desk/slack/test')
    def slack_test(body: dict):return slack.test_message(body.get('channel_id'))
    @app.get('/api/desk/slack/deliveries')
    def slack_deliveries():return slack.journal.deliveries()
    @app.post('/api/desk/slack/deliveries/{delivery_id}/retry')
    def slack_retry(delivery_id: str):
        slack.journal.retry(delivery_id)
        return {'status':'pending'}
    @app.get('/api/desk/slack/attachments')
    def slack_attachments():
        with slack.journal.connect() as db:
            return [json.loads(r['body']) for r in db.execute('SELECT body FROM attachments ORDER BY rowid DESC LIMIT 100')]
    @app.get('/api/desk/slack/attachments/{attachment_id}/file')
    def slack_attachment(attachment_id: str):
        with slack.journal.connect() as db:
            row=db.execute('SELECT body FROM attachments WHERE id=?',(attachment_id,)).fetchone()
        if not row or json.loads(row['body'])['status']!='ready':raise KeyError('附件尚未就绪')
        ref=json.loads(row['body'])
        return FileResponse(slack.journal.files/ref['id'],media_type='application/octet-stream',filename=ref['name'],
                            headers={'Content-Security-Policy':"sandbox; default-src 'none'",'X-Content-Type-Options':'nosniff'})
    @app.post('/api/desk/slack/live-checks')
    def slack_live_check(body: dict):
        allowed={'dm','mention','command','attachment','research_result','approval','reconnect'}
        if body.get('check') not in allowed or not str(body.get('evidence','')).strip():
            raise ValueError('请选择验收项目并填写实际操作证据')
        if not slack.journal.state('last_received_at'):
            raise ValueError('尚未接收真实 Slack 事件，不能登记联调通过')
        checks=slack.journal.state('live_checks',{})
        checks[body['check']]={'status':'passed','evidence':str(body['evidence'])[:1000],'recorded_at':utcnow(),'source':'owner_recorded'}
        slack.journal.set_state('live_checks',checks)
        return checks
    @app.get('/api/desk/settings')
    def settings():
        return settings_file.public()
    @app.post('/api/desk/settings')
    def save_settings(req: SecretInput):
        incoming=req.model_dump(exclude_none=True)
        from pitr.integrations.slack.settings import validate
        merged={**read_settings(),**incoming};validate(merged)
        connection_changed=any(k.startswith('slack_') and k!='slack_enabled' and v!=read_settings().get(k) for k,v in incoming.items())
        if connection_changed and (slack.socket or slack.client or slack.retry_thread):slack.stop(disable=False)
        result=desk.agents.save_selection(incoming) if getattr(desk,'agents',None) else settings_file.save(incoming)
        if connection_changed:
            slack.journal.set_state('diagnostic',None)
            slack.journal.audit('configuration.changed',detail={'previous_live_checks':slack.journal.state('live_checks',{})})
            slack.journal.set_state('live_checks',{})
            slack.journal.set_state('last_received_at',None)
        if incoming.get('slack_enabled') is False and slack.socket:slack.stop()
        return result

    dist=Path(web_dist or Path(__file__).resolve().parents[3]/'web'/'dist')
    @app.get('/{path:path}')
    def page(path: str):
        if path=='api' or path.startswith('api/'):
            return JSONResponse({'detail':'接口不存在'},status_code=404)
        if path.startswith('api/'):return JSONResponse({'detail':'接口不存在'},status_code=404)
        file=(dist/path).resolve()
        if dist.resolve() in file.parents and file.is_file():return FileResponse(file)
        if (dist/'index.html').exists():return FileResponse(dist/'index.html')
        return JSONResponse({'detail':'请先构建前端'},status_code=503)
    return app

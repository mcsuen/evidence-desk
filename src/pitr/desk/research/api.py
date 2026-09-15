import asyncio,json
from fastapi import APIRouter,UploadFile,File,Form
from fastapi.responses import Response,StreamingResponse
from .contracts import ResearchRequest,ResearchOutcome,ResearchMessage
from .service import Research
from .report import html_report,png_chart

def router(desk,queue):
    r=APIRouter(prefix='/api/desk/research');service=Research(desk,queue)
    @r.post('/requests')
    def create(req:ResearchRequest):
        return service.create(req)
    @r.get('/requests')
    def listing():return service.list()
    @r.post('/attachments')
    async def upload(file:UploadFile=File(),company:str=Form('UNASSIGNED')):
        return service.upload(await file.read(40_000_001),file.content_type,file.filename,company)
    @r.get('/requests/{rid}')
    def get(rid:str):return service.get(rid)
    @r.post('/requests/{rid}/messages')
    def message(rid:str,req:ResearchMessage):return service.message(rid,req)
    @r.post('/requests/{rid}/cancel')
    def cancel(rid:str):return queue.cancel(service.get(rid)['task_id'])
    @r.get('/requests/{rid}/report',response_model=ResearchOutcome)
    def report(rid:str,version:int|None=None):return service.artifact(rid,version)
    @r.get('/requests/{rid}/report.html')
    def html(rid:str,version:int|None=None):return Response(html_report(service.artifact(rid,version)),media_type='text/html',headers={'Content-Disposition':'attachment; filename=research-report.html','Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"})
    @r.get('/requests/{rid}/chart.png')
    def png(rid:str):return Response(png_chart(service.artifact(rid)),media_type='image/png')
    @r.get('/requests/{rid}/artifacts')
    def artifacts(rid:str):
        request=service.get(rid)
        with desk.store.connect() as db:
            return {'versions':[{'version':x['version'],**json.loads(x['body'])} for x in db.execute('SELECT * FROM research_artifacts WHERE task_id=? ORDER BY version',(request['task_id'],))],
                    'attempts':[json.loads(x['body']) for x in db.execute('SELECT body FROM research_attempts WHERE task_id=? ORDER BY ordinal',(request['task_id'],))]}
    @r.post('/requests/{rid}/proposals')
    def propose(rid:str,body:dict):
        from .handoff import propose
        return propose(service,rid,body)
    @r.get('/requests/{rid}/events')
    async def events(rid:str):
        service.get(rid)
        async def stream():
            last=None
            while True:
                current=service.get(rid);body=json.dumps(current,ensure_ascii=False)
                if body!=last:yield 'data: '+body+'\n\n';last=body
                if current['task']['status'] in ('completed','cancelled','failed','waiting_user') and current.get('interpretation_status') not in ('pending','running','ready'):break
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream')
    return r

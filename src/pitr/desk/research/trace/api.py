import asyncio,json,hashlib,io,zipfile
from fastapi import APIRouter,Header,Query,Request
from fastapi.responses import Response,StreamingResponse
from .contracts import TraceView,TraceSettings,TraceSyncRequest
from .history import ensure_history
from .sync import Sync,redact
from ..service import Research
from ...storage import canonical


def router(desk):
    r=APIRouter(prefix='/api/desk/research');research=Research(desk);sync=Sync(desk)
    def load(rid):
        request=research.get(rid);return request,ensure_history(desk,request)
    @r.get('/trace-settings')
    def settings():return sync.public()
    @r.post('/trace-settings')
    def save(body:TraceSettings):return sync.save(body)
    @r.get('/requests/{rid}/trace',response_model=TraceView)
    def trace(rid:str,at_seq:int|None=Query(None,ge=0)):
        request,store=load(rid);return store.view(request,at_seq)
    @r.get('/requests/{rid}/trace/spans/{span_id}')
    def detail(rid:str,span_id:str,at_seq:int|None=Query(None,ge=0)):
        _,store=load(rid);return store.detail(span_id,at_seq)
    @r.get('/requests/{rid}/trace/events')
    async def events(rid:str,request:Request,after_seq:int=Query(0,ge=0),last_event_id:str|None=Header(None)):
        _,store=load(rid)
        try:cursor=max(after_seq,int(last_event_id or 0))
        except ValueError:cursor=after_seq
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                batch=await asyncio.to_thread(store.events,cursor)
                for event in batch:
                    cursor=event['seq'];yield 'id: '+str(cursor)+'\nevent: trace\ndata: '+canonical(event)+'\n\n'
                if not batch:yield ': heartbeat\n\n'
                await asyncio.sleep(.5)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @r.get('/requests/{rid}/trace/export')
    def export(rid:str):
        request,store=load(rid);view=store.view(request);events=store.all_events();refs={e['content_ref'] for e in events if e['content_ref']}
        for s in view['spans']:refs.update(s[k] for k in ('input_ref','output_ref','error_ref') if s[k])
        with desk.store.connect() as db:contents={ref:json.loads(row[0]) for ref in refs if (row:=db.execute('SELECT body FROM trace_content WHERE hash=?',(ref,)).fetchone())}
        payloads={'trace.json':view,'events.json':events,'contents.json':contents,'request.json':request['input']}
        files={k:canonical(redact(v,sync.secrets())).encode() for k,v in payloads.items()}
        # Source content hashes remain original identities. Bundle hashes describe the sanitized files.
        manifest={'version':'trace-diagnostic.1','research_id':rid,'event_seq':view['seq'],'redacted':True,'original_pdfs':False,
            'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for k,v in files.items():archive.writestr(k,v)
            archive.writestr('manifest.json',canonical(manifest))
        return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="research-trace.zip"'})
    @r.post('/requests/{rid}/trace/sync')
    def send(rid:str,body:TraceSyncRequest):
        request,store=load(rid);return sync.enqueue(store,request,body.preview_hash,body.preview)
    return r,sync

"""Single control plane shared by Web, Slack, contextual buttons and CLI."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from .contracts import ResearchRequest
from ..storage import Conflict

HOST_COMPANY={'investor.pddholdings.com':'PDD','pinduoduo.gcs-web.com':'PDD',
 'www.alibabagroup.com':'BABA','ir.jd.com':'JD','ir.aboutamazon.com':'AMZN','investor.mercadolibre.com':'MELI'}
SCHEMA='''
CREATE TABLE IF NOT EXISTS research_requests(id TEXT PRIMARY KEY, task_id TEXT UNIQUE, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_inputs(request_id TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY(request_id,version));
CREATE TABLE IF NOT EXISTS research_receipts(task_id TEXT, id TEXT, kind TEXT, body TEXT NOT NULL, PRIMARY KEY(task_id,id));
CREATE TABLE IF NOT EXISTS research_artifacts(task_id TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY(task_id,version));
CREATE TABLE IF NOT EXISTS research_attempts(task_id TEXT, ordinal INTEGER, body TEXT NOT NULL, PRIMARY KEY(task_id,ordinal));
CREATE TABLE IF NOT EXISTS research_meta(key TEXT PRIMARY KEY, body TEXT NOT NULL);
'''


def initialize(desk):
    with desk.store.connect() as db:
        if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('research_requests','research_inputs','research_receipts','research_artifacts','research_attempts','research_meta')").fetchone()[0]!=6:db.executescript(SCHEMA)
        from .intake import SCHEMA as INTAKE_SCHEMA
        if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('research_entities','research_messages','research_interpretations')").fetchone()[0]!=3:db.executescript(INTAKE_SCHEMA)

class Research:
    def __init__(self,desk,queue=None):
        self.desk=desk; self.queue=queue; initialize(desk)

    def create(self,req:ResearchRequest):
        from .intake import Intake
        return Intake(self.desk,self.queue).create(req)

    def get(self,rid,db=None):
        if db is None:
            with self.desk.store.connect() as conn:return self.get(rid,conn)
        row=db.execute('SELECT * FROM research_requests WHERE id=? OR task_id=?',(rid,rid)).fetchone()
        if not row:raise KeyError('研究请求不存在')
        body=json.loads(row['body']);task=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(row['task_id'],)).fetchone()['body'])
        from .intake import describe
        return describe(db,{**body,'task':task})

    def list(self):
        with self.desk.store.connect() as db:return [self.get(r['id'],db) for r in db.execute('SELECT id FROM research_requests ORDER BY rowid DESC LIMIT 100')]


    def upload(self,raw,media,name,company='UNASSIGNED'):
        if len(raw)>40_000_000:raise ValueError('单文件不得超过 40 MB')
        suffix=Path(name).suffix.lower()
        allowed={'.pdf':'application/pdf','.html':'text/html','.htm':'text/html','.txt':'text/plain','.md':'text/markdown'}
        if suffix not in allowed:raise ValueError('支持 PDF、HTML、TXT、Markdown；PDF 可按页读取文本、表格和图像，其他格式尚未解析')
        if suffix!='.pdf':
            try:raw.decode('utf-8')
            except UnicodeDecodeError:raise ValueError('文本文件必须为 UTF-8，未读取其内容')
        doc=self.desk.ingest(raw,allowed[suffix],'upload:research/'+hashlib.sha256(raw).hexdigest()[:20]+'/'+name,company.upper(),name)
        return {'source_id':doc.id,'title':doc.title,'digest':doc.digest,'blocks':len(doc.blocks),
                'reading_status':'not_started','issues':doc.issues}

    def message(self,rid,message):
        from .intake import Intake
        return Intake(self.desk,self.queue).send(rid,message)

    def artifact(self,rid,version=None):
        request=self.get(rid)
        with self.desk.store.connect() as db:
            row=db.execute('SELECT version,body FROM research_artifacts WHERE task_id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1',(request['task_id'],version,version)).fetchone()
        if not row:raise KeyError('研究尚未交付报告')
        result=json.loads(row['body'])['validated']
        result['artifact_version']=row['version']
        with self.desk.store.connect() as db:latest=db.execute('SELECT MAX(version) FROM research_artifacts WHERE task_id=?',(request['task_id'],)).fetchone()[0]
        if row['version']!=latest:result['handoffs']=[]
        if request['task']['status']!='completed':
            result['status']='needs_review';result['handoffs']=[]
            result['issues'].append({'code':'run_incomplete','message':'本次执行尚未完整交付；展示最近保存并核验的草稿。'+request['task'].get('error','')})
        try:
            if request.get('invalidated'):raise Conflict(request['invalidated']['reason'])
            with self.desk.store.connect() as db:self.desk._sources_valid(db,self.desk._snapshot(db,result['snapshot']))
        except (ValueError,KeyError,OSError) as e:
            result['status']='needs_review';result['issues'].append({'code':'source_invalidated','message':str(e)})
            for c in result['claims']:c['validation']='needs_repair'
            result['handoffs']=[]
            result['delivery']={'status':'invalidated','reason':'原件已撤回、更新或不可用，需要重新复核；历史交付记录保留。'}
            result['verification']['independent_review']='invalidated'
            # Re-evaluate the view without rewriting any historical artifact.
            # Withdrawn/superseded/changed originals cannot inflate evidence counts.
            invalid=set()
            with self.desk.store.connect() as db:
                for source in {x['source_id'] for x in result['evidence']}:
                    refs=[x for x in result['evidence'] if x['source_id']==source]
                    try:self.desk._sources_valid(db,{'sources':{source:refs[0]['source_version']}})
                    except (ValueError,KeyError,OSError):invalid.update(x['id'] for x in refs)
            for c in result['claims']:
                c.setdefault('invalid_references',[]).extend({'code':'source_invalidated','field':field,'value':ref,'message':'引用原件已撤回、更新或改变'} for field in ('evidence','counterevidence','original_evidence') for ref in c.get(field,[]) if ref in invalid)
                if invalid & set(c.get('evidence',[])+c.get('counterevidence',[])+c.get('calculation_evidence',[])+c.get('original_evidence',[])):
                    c['independent_source_count']=None  # Reassess independence after invalidation; never display a stale accepted count.
            result['evidence']=[x for x in result['evidence'] if x['id'] not in invalid]
        from pitr.wiki.store import state
        with self.desk.store.connect() as db:
            related=[p for p in state(db,'proposals').values() if any(
                binding.get('research_ref',{}).get('request_id')==request['id'] and binding['research_ref'].get('artifact_version')==row['version']
                for change in p['request']['changes'] for binding in change.get('numeric_assertions',[]))]
        result['human_review']='partially_adopted' if any(p['status']=='adopted' for p in related) else 'pending' if any(p['status']=='pending' for p in related) else 'not_reviewed'
        from .presentation import enrich
        return enrich(result,request['input'].get('scope',{}).get('subjects',result.get('subjects',[])),request['input'].get('scope',{}).get('type'))

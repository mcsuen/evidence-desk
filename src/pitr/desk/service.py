from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from .contracts import *
from .storage import Store, Conflict, canonical, digest
from .financials import build_rows, margin_bridge
from . import sources


def stamp(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('时间必须包含时区')
    return dt.astimezone(timezone.utc)


class Desk:
    def __init__(self, root):
        self.store=Store(root)
        self.root=self.store.root
        self.files=self.store.files
        from pitr.wiki.service import Wiki
        self.wiki=Wiki(self)

    def documents(self, company=None):
        with self.store.connect() as db:
            rows=db.execute('SELECT body FROM documents WHERE (? IS NULL OR company=?) ORDER BY available_at DESC',(company,company))
            return [Document.model_validate_json(r['body']) for r in rows]

    def document(self, sid):
        with self.store.connect() as db:
            row=db.execute('SELECT body FROM documents WHERE id=?',(sid,)).fetchone()
            if not row:raise KeyError('来源不存在')
            return Document.model_validate_json(row['body'])

    def put_document(self, doc):
        metrics=sources.extract_pdd_metrics(doc)
        with self.store.connect(write=True) as db:
            if db.execute('SELECT 1 FROM documents WHERE id=?',(doc.id,)).fetchone():return doc
            db.execute('INSERT INTO documents VALUES(?,?,?,?)',(doc.id,doc.company,doc.available_at,canonical(doc)))
            for m in metrics:
                db.execute('INSERT INTO observations VALUES(?,?,?,?)',(m.id,doc.company,doc.id,canonical(m)))
            self.store.event(db,doc.company,'source.imported',{'title':doc.title,'id':doc.id,'metrics':len(metrics)})
            self.wiki.register_document(db,doc.model_dump(mode='json'))
        return doc

    def ingest(self, content, media_type, url, company, title=''):
        return sources.ingest(self,content,media_type,url,company.upper(),title)


    def snapshot(self, company, as_of):
        cutoff=stamp(as_of)
        docs=[d for d in self.documents(company) if stamp(d.available_at)<=cutoff]
        ids={d.id for d in docs}
        with self.store.connect() as db:
            withdrawn={r['id'] for r in db.execute('SELECT * FROM source_state') if stamp(r['withdrawn_at'])<=cutoff}
            superseded={d.supersedes for d in docs if d.supersedes}
            docs=[d for d in docs if d.id not in withdrawn|superseded]
            ids={d.id for d in docs}
            metrics=[Metric.model_validate_json(r['body']) for r in db.execute('SELECT body,source_id FROM observations WHERE company=?',(company,)) if r['source_id'] in ids]
            visible_objects={}
            for o in db.execute('SELECT * FROM objects WHERE company=? ORDER BY version',(company,)):
                if stamp(o['created_at'])<=cutoff:
                    visible_objects[o['id']]={**dict(o),'body':json.loads(o['body']),'citations':json.loads(o['citations'])}
            context={k:o['version'] for k,o in visible_objects.items()}
            imports=[r['id'] for r in db.execute('SELECT id FROM imports WHERE company=?',(company,))]
        body={'identity':'desk-snapshot.2','company':company,'as_of':cutoff.isoformat(),
              'sources':{d.id:d.digest for d in docs},'observations':[m.model_dump() for m in metrics],
              'versions':context,'objects':visible_objects,'imports':sorted(imports),'method':'financials.1'}
        sid='snapshot_'+digest(body)[:32]
        with self.store.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',(sid,company,canonical(body)))
        path=self.store.snapshots/(sid+'.json')
        if not path.exists():
            path.write_text(canonical(body));path.chmod(0o444)
        return sid,body,docs,metrics

    def view(self, company='PDD', period='', as_of=None, baseline_type='user_forecast'):
        as_of=as_of or utcnow()
        sid,snap,docs,metrics=self.snapshot(company,as_of)
        periods=sorted({m.period for m in metrics if re.fullmatch(r'20\d{2}Q[1-4]',m.period)})
        period=period or (periods[-1] if periods else '2025Q4')
        relevant=[d for d in docs if period in d.title]
        event_time=min((d.available_at for d in relevant),default=as_of)
        with self.store.connect() as db:
            # Observation identity binds immutable source and value. A new read
            # time must not erase a prior human check of the very same source.
            checked={r['observation_id'] for r in db.execute('SELECT * FROM checks')}
            imports=[json.loads(r['body']) for r in db.execute("SELECT body FROM imports WHERE kind='expectation' AND company=?",(company,))]
        expectations=[]
        for item in sorted(imports,key=lambda i:i['effective_at']):
            if item['kind']==baseline_type and stamp(item['effective_at'])<stamp(event_time):expectations.extend(item['rows'])
        rows=build_rows(metrics,{d.id:d.available_at for d in docs},period,expectations,checked,baseline_type)
        issues=[]
        if not expectations:issues.append('没有事件前已冻结且可核实的比较基准')
        if company=='PDD':issues.append('交易服务收入包含多种服务；Temu 独立收入与利润未披露')
        models=[o for o in snap['objects'].values() if o['kind']=='model']
        return DeskView(company=company,period=period,periods=periods,as_of=as_of,snapshot=sid,rows=rows,
            documents=[d.model_copy(update={'blocks':[]}) for d in docs],bridge=margin_bridge(rows),
            model=models[0] if models else None,issues=issues)


    def _snapshot(self, db, sid):
        row=db.execute('SELECT body FROM snapshots WHERE id=?',(sid,)).fetchone()
        if not row:raise ValueError('输入快照不存在')
        snap=json.loads(row['body'])
        if sid!='snapshot_'+digest(snap)[:32]:raise ValueError('输入快照校验失败')
        return snap

    def _sources_valid(self, db, snap):
        for sid,sha in snap['sources'].items():
            if db.execute('SELECT 1 FROM source_state WHERE id=?',(sid,)).fetchone():raise Conflict('来源已撤回，需要重新复核')
            doc=self.document(sid)
            import hashlib
            if hashlib.sha256((self.files/doc.file_name).read_bytes()).hexdigest()!=sha:raise Conflict('原件内容已变化')
            if any(d.supersedes==sid for d in self.documents(doc.company)):raise Conflict('来源已有新版本，需要重新复核')

    def validate_citations(self, refs, snap):
        for ref in refs:
            if ref.source_id not in snap['sources']:raise ValueError('引用不在输入快照内')
            doc=self.document(ref.source_id)
            if not any(b.id==ref.block_id and ref.quote in b.text for b in doc.blocks):raise ValueError('原文没有支持引用定位')


    def withdraw(self, sid):
        doc=self.document(sid)
        with self.store.connect(write=True) as db:
            db.execute('INSERT OR IGNORE INTO source_state VALUES(?,?)',(sid,utcnow()))
            from pitr.wiki.store import get,change
            source=get(db,'sources',sid)
            if source and source['state']!='withdrawn':
                self.wiki._emit(db,doc.company,'source.withdrawn',[change('sources',sid,{**source,'state':'withdrawn','changed_at':utcnow()})])
                self.wiki._source_impacts(db,sid,'来源已撤回')
            self.store.event(db,doc.company,'source.withdrawn',{'id':sid})
        return {'id':sid,'status':'withdrawn'}


    def home(self):
        return {'companies':sorted({d.company for d in self.documents() if d.company not in ('UNASSIGNED','INDUSTRY')})}

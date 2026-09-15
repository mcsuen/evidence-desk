"""Company-scoped snapshots and arithmetic for one multi-subject research session."""
from __future__ import annotations
import re
from urllib.parse import urlsplit
from ..contracts import Metric, utcnow
from ..storage import canonical, digest
from ..financials import build_rows
from .workspace import source_role


def ids(plane):return [s['company_id'] for s in plane.input.get('scope',{}).get('subjects',[]) if s.get('company_id') and s.get('role')!='excluded']

def require_company(plane,company='',allow_topic=False):
    allowed=ids(plane)
    if not allowed and allow_topic and company in ('','INDUSTRY'):return 'INDUSTRY'
    if not company and len(allowed)==1:company=allowed[0]
    if not company and allow_topic:return 'INDUSTRY'
    if company not in allowed:raise ValueError('请使用 context 中明确的 company_id；多公司指标必须指定主体')
    return company

def source_company(plane,url,company=''):
    from .semantics import companies
    host=(urlsplit(url).hostname or '').lower()
    matched=[cid for cid,r in companies(plane.desk).items() if host in r.get('official_domains',[])]
    if len(matched)==1:
        if company and matched[0]!=company:raise ValueError('官网原件与指定公司不一致')
        return require_company(plane,matched[0])
    return require_company(plane,company,allow_topic=True)

def prepare(plane):
    prepared=[];issues=[]
    for url in plane.input['official_urls']:
        try:prepared.append(plane._invoke('prepare.fetch_source',{'url':url},lambda:plane._fetch(url).model_dump())['id'])
        except Exception as error:issues.append(str(error))
    if plane.input['intent']=='earnings' and not plane.input.get('as_of') and not plane.input.get('snapshot'):
        for cid in ids(plane):
            try:
                found=plane.call('discover_sources',{'company':cid})
                choices=[x for x in found.get('links',[]) if not plane.input['period'] or plane.input['period']==x.get('period') or plane.input['period'] in x.get('title','')]
                if choices:
                    item=choices[0];prepared.append(plane._invoke('prepare.fetch_source',{'url':item['url'],'company':cid},lambda:plane._fetch(item['url'],item.get('title',''),cid).model_dump())['id'])
                else:issues.append(cid+'：尚未定位最新披露，请继续公开搜索核实')
            except Exception as error:issues.append(cid+'：'+str(error))
    cutoff=plane.input.get('as_of') or utcnow()
    if plane.input.get('snapshot'):
        with plane.desk.store.connect() as db:snap=plane.desk._snapshot(db,plane.input['snapshot'])
        if snap['company']!=plane.input['company']:raise ValueError('固定快照不属于研究对象')
        cutoff=snap['as_of']
    else:
        snaps=[plane.desk.snapshot(cid,cutoff)[1] for cid in ids(plane)]
        snap={'identity':'research-subjects.1','company':plane.input['company'],'as_of':cutoff,'sources':{},'observations':[],'versions':{},'objects':{},'imports':[],'method':'financials.1'}
        for child in snaps:
            for key in ('sources','versions','objects'):snap[key].update(child[key])
            snap['observations'].extend(child['observations']);snap['imports'].extend(child['imports'])
        snap['imports']=sorted(set(snap['imports']))
    for sid in list(dict.fromkeys(plane.input['source_ids']+prepared)):
        doc=plane.desk.document(sid)
        if doc.available_at>cutoff:issues.append('资料晚于固定信息截止：'+doc.title);continue
        snap['sources'][sid]=doc.digest
    return plane._freeze(snap,issues)

def contexts(plane,snap):
    result=[]
    for subject in plane.input.get('scope',{}).get('subjects',[]):
        cid=subject['company_id'];docs=[plane.desk.document(s) for s in snap['sources'] if plane.desk.document(s).company==cid]
        doc_ids={d.id for d in docs};observations=[m for m in snap['observations'] if m['citation']['source_id'] in doc_ids]
        sub={**snap,'company':cid,'sources':{d.id:d.digest for d in docs},'observations':observations,
             'objects':{k:o for k,o in snap['objects'].items() if o.get('company')==cid}}
        sub['versions']={k:v for k,v in snap['versions'].items() if k in sub['objects']}
        sid='snapshot_'+digest(sub)[:32]
        with plane.desk.store.connect(write=True) as db:
            plane.fence(db);db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?)',(sid,cid,canonical(sub)))
        metrics=[Metric.model_validate(m) for m in observations if source_role(plane.desk.document(m['citation']['source_id']))=='official']
        periods=sorted({m.period for m in metrics if re.fullmatch(r'20\d{2}Q[1-4]',m.period)})
        period=plane.input['period'] or (periods[-1] if periods else '')
        rows=build_rows(metrics,{d.id:d.available_at for d in docs},period,[],[],'user_forecast') if period else []
        result.append({**subject,'snapshot':sid,'period':period,'rows':[r.model_dump() for r in rows],
                       'source_ids':sorted(doc_ids),'model_draft_id':plane.input.get('model_draft_id','') if len(ids(plane))==1 else '',
                       'metric_names':sorted({m.name for m in metrics})})
    return result

def calc_identity(plane,dependencies,extra):
    receipts=plane.receipts();found=set()
    for dep in dependencies:
        ref=receipts.get(dep,{})
        found.update(ref.get('subject_ids',[]))
        if ref.get('company_id'):found.add(ref['company_id'])
    explicit=extra.get('company_id','')
    if explicit:
        require_company(plane,explicit,allow_topic=not ids(plane))
        if found and explicit not in found:raise ValueError('数字主体与原文主体不一致')
        found.add(explicit)
    if not found and len(ids(plane))==1:found.add(ids(plane)[0])
    extra.update(company_id=next(iter(found)) if len(found)==1 else '',subject_ids=sorted(found))
    return extra

def guard_calculation(plane,operation,a,b):
    if (not a) or (not b):return
    left=set(a.get('subject_ids',[]));right=set(b.get('subject_ids',[]))
    if left and right and left!=right:
        if operation!='compare':raise ValueError('跨公司计算仅允许相同口径的 compare；不能混合公司的利润、收入或跨期增长')
        if len(left)!=1 or len(right)!=1:raise ValueError('比较输入必须各自绑定一个公司')
        if not a.get('frequency') or not a.get('basis') or a['basis']=='disclosed':raise ValueError('跨公司比较须明确相同会计口径与频率，未知口径不可比较')

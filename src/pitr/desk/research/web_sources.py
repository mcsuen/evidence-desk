"""Public discovery is isolated from local report content; originals are fetched by the controller."""
from __future__ import annotations
import json
from .workspace import source_role
from ..contracts import utcnow




def search_public(plane, query):
    from pitr.wiki.discovery import Discovery
    from pitr.agent_runtime.runtime import verified_searches,search_log
    result=plane.desk.agents.execute(plane.task,
        'Actually use live web search to find public original sources. Return candidate URLs and publication metadata, duplicates, original_url and gaps. Search snippets are leads, never evidence. Do not invent search logs or URLs. Query: '+query,
        Discovery.model_json_schema(),role='search',live_search=True,fence=plane.fence,timeout=None)
    value=Discovery.model_validate(result.data).model_dump()
    value['search_log']=search_log(result.events)
    value.update(actual_searches=verified_searches(result.events),verified_live_search=True,usage=[result.usage],
                 model=result.model,provider=result.provider,reasoning=plane.task['agent'].get('reasoning'),query=query,runtime_dir=str(result.root))
    return plane.receipt('discovery',value)


def fetch_public_source(plane,url,company=''):
    from pitr.wiki.discovery import fetch_public
    settings=plane.desk.root/'private/settings.json'
    contact=json.loads(settings.read_text()).get('sec_user_agent','') if settings.exists() else ''
    raw,media,final,attempts=fetch_public(url,timeout=45,**({'contact':contact} if contact else {}))
    plane.fence()
    from urllib.parse import urlparse
    from selectolax.parser import HTMLParser
    if 'html' in media:
        title_node=HTMLParser(raw).css_first('title')
        title=title_node.text(strip=True) if title_node else ''
        if (urlparse(final).hostname or '').startswith('unblock.') or title.casefold() in {
            'federal register :: request access','access denied','just a moment...','attention required! | cloudflare'}:
            plane.receipt('acquisition_failure',{'url':url,'final_url':final,'title':title,'attempts':attempts,'reason':'access_challenge'})
            raise ValueError('公开站点返回访问验证页，未取得原件；已保留获取记录，请尝试其他官方原件路径。'+title)
    cid=plane.input['company']
    from .subjects import source_company
    cid=source_company(plane,final,company)
    doc=plane.desk.ingest(raw,media,final,cid)
    for discovery in plane.receipts('discovery').values():
        for candidate in discovery.get('candidates',[]):
            if candidate['url'] in (url,final) and candidate.get('original_url'):
                plane.state.setdefault('source_origins',{})[doc.id]=candidate['original_url']
    with plane.desk.store.connect() as db:snap=plane.desk._snapshot(db,plane.frozen['snapshot'])
    if doc.available_at>snap['as_of']:
        if plane.input.get('as_of') or plane.input.get('snapshot'):
            return {'included':False,'source_id':doc.id,'reason':'原件可得时间晚于用户固定截止时间','attempts':attempts}
        # A present-day investigation advances an explicitly versioned acquisition
        # cutoff. User-selected historical snapshots never move.
        snap['as_of']=max(utcnow(),doc.available_at)
    snap['sources'][doc.id]=doc.digest
    if doc.supersedes and doc.supersedes in snap['sources']:
        snap['sources'].pop(doc.supersedes)
        snap['observations']=[m for m in snap['observations'] if m['citation']['source_id']!=doc.supersedes]
    if source_role(doc)=='official':
        with plane.desk.store.connect() as db:
            ids={m['id'] for m in snap['observations']}
            snap['observations'] += [m for r in db.execute('SELECT body FROM observations WHERE source_id=?',(doc.id,)) if (m:=json.loads(r['body']))['id'] not in ids]
    if plane.frozen['sources'].get(doc.id)!=doc.digest:plane._freeze(snap,[])
    return {'included':True,'source_id':doc.id,'title':doc.title,'source_role':source_role(doc),'attempts':attempts,
        'input_version':plane.state['input_version'],'as_of':plane.frozen['as_of']}

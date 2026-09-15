"""Read-only tools bound to one immutable input snapshot; shared CLI/MCP/Agent."""

class SnapshotTools:
 def __init__(self,desk,snapshot):
  self.desk=desk;self.id=snapshot
  with desk.store.connect() as db:self.snapshot=desk._snapshot(db,snapshot)
 def search(self,query):
  words=query.lower().split()
  if not words:raise ValueError('需要搜索关键词')
  return [{'source_id':d.id,'block_id':b.id,'text':b.text} for sid in self.snapshot['sources'] for d in [self.desk.document(sid)] for b in d.blocks if any(w in b.text.lower() for w in words)][:18]
 def read(self,source_id,offset=0):
  if source_id not in self.snapshot['sources'] or offset<0:raise ValueError('来源或位置不在快照内')
  return [b.model_dump() for b in self.desk.document(source_id).blocks[offset:offset+160]]
 def observations(self,metric=''):
  return [m for m in self.snapshot['observations'] if not metric or m['name']==metric]
 def wiki(self,query=''):
  from pitr.wiki.search import search
  company=self.snapshot['company'];as_of=self.snapshot['as_of']
  return search(self.desk.wiki,company,query,as_of=as_of)['items'] if query else self.desk.wiki.list(company,as_of,include_blocked=False)
 def objects(self):
  allowed={r['id']:r for r in self.wiki()}
  return [{**o,'wiki_status':allowed[o['id']]['availability']} if o['kind']=='wiki' else o
    for o in self.snapshot.get('objects',{}).values() if o['kind']!='wiki' or o['id'] in allowed]

 def operating_model(self,anchor_period,assumptions=None):
  from .company_model import calculate,ModelSpec
  return calculate(self.desk,ModelSpec(snapshot=self.id,anchor_period=anchor_period,assumptions=assumptions or [])).model_dump()

def mcp_server(desk,snapshot):
 from mcp.server.fastmcp import FastMCP
 plane=SnapshotTools(desk,snapshot);server=FastMCP('PITR snapshot research')
 @server.tool()
 def search_sources(query:str):return plane.search(query)
 @server.tool()
 def read_source(source_id:str,offset:int=0):return plane.read(source_id,offset)
 @server.tool()
 def financial_observations(metric:str=''):return plane.observations(metric)
 @server.tool()
 def research_objects():return plane.objects()
 @server.tool()
 def company_wiki(query:str=''):
  """Read existing synthesis at this snapshot's cutoff before inspecting originals."""
  return plane.wiki(query)
 @server.tool()
 def calculate_operating_scenario(anchor_period:str,assumptions:list[dict]):
  """Read-only PDD OP scenario, bounded to this snapshot; does not submit a forecast."""
  return plane.operating_model(anchor_period,assumptions)
 return server

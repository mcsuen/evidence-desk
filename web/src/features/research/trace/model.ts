import type {TraceSpan,TraceView} from '../../../types/trace_view'
export const statusLabel:Record<string,string>={cancelled:'已取消',budget_exhausted:'预算耗尽',running:'进行中',completed:'已结束',failed:'失败',interrupted:'已中断',waiting_user:'等待回答',needs_review:'核验问题',queued:'排队中',unobserved:'未采集'}
export const executorLabel:Record<string,string>={controller:'控制服务',deterministic:'确定性工具',codex:'Codex',claude:'Claude Code',agent:'Agent'}
export const isInvocation=(s:TraceSpan)=>s.kind==='tool'||s.kind==='rejected_tool'
export const isError=(s:TraceSpan)=>['failed','interrupted','needs_review'].includes(s.status)
export const statusTone=(s:TraceSpan):'ok'|'warn'|'danger'|'accent'|'default'=>s.status==='completed'?'ok':s.status==='running'?'accent':isError(s)?'danger':s.status==='waiting_user'?'warn':'default'
export type ToolGroup={key:string;label:string;count:number;failed:number;maxMs:number;totalMs:number;tools:TraceSpan[]}
const groupOf=(name:string):[string,string]=>{const n=name.toLowerCase()
  if(/read|open|fetch_document|pdf|page/.test(n))return ['read','读原件']
  if(/search|discover|lookup|query/.test(n))return ['search','检索']
  if(/calc|compar|compute|financial|ratio|series/.test(n))return ['calc','计算']
  if(/save|write|checkpoint|submit|persist|propose|deliver|quote|bind|assume|record/.test(n))return ['write','写回']
  return ['other','其它']}
export function groupTools(children:TraceSpan[]):ToolGroup[]{
  const m=new Map<string,ToolGroup>()
  for(const t of children){const [key,label]=groupOf(t.name);const g=m.get(key)||{key,label,count:0,failed:0,maxMs:0,totalMs:0,tools:[]};g.count++;if(isError(t)||t.kind==='rejected_tool')g.failed++;if(t.duration_ms!=null){g.maxMs=Math.max(g.maxMs,t.duration_ms);g.totalMs+=t.duration_ms}g.tools.push(t);m.set(key,g)}
  return [...m.values()].sort((a,b)=>b.count-a.count)
}
export const stages=(view:TraceView)=>view.spans.filter(s=>!isInvocation(s))
export const childrenOf=(view:TraceView,id:string)=>view.spans.filter(s=>isInvocation(s)&&s.parent_id===id)
export function attentionItems(view:TraceView){
  const items:{id:string;text:string;tone:'danger'|'warn'}[]=[]
  for(const s of view.spans){
    if(s.kind==='agent'&&isError(s))items.push({id:s.id,text:`${s.name} ${statusLabel[s.status]||s.status}`,tone:'danger'})
    else if(s.kind==='tool'&&isError(s))items.push({id:s.id,text:`工具 ${s.name} 失败`,tone:'danger'})
    else if(s.kind==='rejected_tool')items.push({id:s.id,text:`工具 ${s.name} 被拒`,tone:'warn'})
    else if(!isInvocation(s)&&s.issue_count>0)items.push({id:s.id,text:`${s.name} ${s.issue_count} 个核验问题`,tone:'warn'})
    else if(!isInvocation(s)&&isError(s))items.push({id:s.id,text:`${s.name} ${statusLabel[s.status]||s.status}`,tone:'danger'})
  }
  return items
}

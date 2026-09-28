import {lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import type {TraceView,TraceSpan} from '../../../types/trace_view'
import {api} from '../../../lib/api'
import {useSse} from '../../../lib/useSse'
import {duration,dateTime} from '../../../lib/format'
import {Badge,Button,Card,CardHeader,Drawer,ErrorBoundary,InlineError,Loading,Seg} from '../../../ui'
import {useNarrow} from '../EvidenceRail'
import {Waterfall} from './Waterfall'
import {attentionItems,isInvocation,statusLabel,statusTone} from './model'
import s from './trace.module.css'
const RunGraph=lazy(()=>import('./RunGraph').then(m=>({default:m.RunGraph})))
const ObjectDetails=lazy(()=>import('../../../workbench/ObjectDetails'))
const seconds=(v:number|null)=>v==null?'未采集':v<60?`${v.toFixed(1)} s`:`${Math.floor(v/60)} min ${Math.round(v%60)} s`
export function TracePanel({rid,initialView='graph'}:{rid:string;initialView?:'graph'|'waterfall'}){
 const client=useQueryClient(),narrow=useNarrow(),[mode,setMode]=useState(initialView),[at,setAt]=useState<number|null>(null),[follow,setFollow]=useState(true),[selected,setSelected]=useState(()=>sessionStorage.getItem('trace-node:'+rid)||''),trigger=useRef<HTMLElement|null>(null)
 const {data:view,error}=useQuery({queryKey:['trace',rid,at],queryFn:()=>api<TraceView>(`/runs/${rid}/trace${at==null?'':`?at_seq=${at}`}`),refetchInterval:at==null?3000:false})
 const latest=useRef(0),pending=useRef<ReturnType<typeof setTimeout>|null>(null)
 const stream=useSse(at==null?`/api/v1/runs/${rid}/trace/events`:null,useCallback((_n:string,_d:string,id:string)=>{const seq=Number(id);if(seq<=latest.current)return;latest.current=seq;if(!pending.current)pending.current=setTimeout(()=>{pending.current=null;client.invalidateQueries({queryKey:['trace',rid]})},250)},[client,rid]),{events:['trace']})
 useEffect(()=>()=>{if(pending.current)clearTimeout(pending.current)},[])
 useEffect(()=>{if(view&&follow&&at==null&&!narrow){const live=[...view.spans].reverse().find(x=>x.status==='running'&&!isInvocation(x));if(live)setSelected(live.id)}},[view,follow,at,narrow])
 const select=useCallback((id:string)=>{if(id&&!document.activeElement?.closest('[data-testid="trace-inspector"]'))trigger.current=document.activeElement as HTMLElement;setSelected(id);setFollow(false);sessionStorage.setItem('trace-node:'+rid,id)},[rid])
 if(error&&!view)return <InlineError>无法读取执行记录：{String(error)}</InlineError>
 if(!view)return <Loading>读取执行记录…</Loading>
 const selectedSpan=view.spans.find(x=>x.id===selected),attention=attentionItems(view)
 return <div className={s.panel} data-testid="trace-panel">
 {attention.length>0&&<div className={s.notice}><b>需要注意</b>{attention.slice(0,3).map(a=><span key={a.id}>{a.text}</span>)}<Button size="sm" onClick={()=>select(attention[0].id)}>定位第一处 →</Button></div>}
 <div className={s.stats}><span><b>{seconds(view.summary.active_seconds)}</b> 活跃执行</span><span><b>{seconds(view.summary.queue_seconds)}</b> 排队</span><span><b>{view.summary.tool_count}</b> 次工具调用 · {view.summary.measured_tools} 次可计量</span><span><b>{view.summary.tokens.input_tokens?.toLocaleString()??'未采集'} / {view.summary.tokens.output_tokens?.toLocaleString()??'未采集'}</b> 输入 / 输出 token</span><Badge tone={at!=null?'warn':stream==='live'?'ok':'default'}>{at!=null?'历史回放':stream==='live'?'实时 · 已连接':'重连中 · 定时补查'}</Badge></div>
 <div className={s.stats}><Seg label="流程视图" value={mode} onChange={v=>setMode(v as typeof mode)} options={[{value:'graph',label:'运行图'},{value:'waterfall',label:'瀑布'}]}/><label><input type="checkbox" checked={follow&&at==null} onChange={e=>{setFollow(e.target.checked);if(e.target.checked)setAt(null)}}/>跟随运行</label><label style={{display:'flex',gap:8,alignItems:'center',flex:1,minWidth:200}}>历史回放<input type="range" aria-label="回放事件位置" min={0} max={view.latest_seq||1} value={at??view.latest_seq} onChange={e=>{setAt(Number(e.target.value));setFollow(false);setSelected('')}} style={{flex:1}}/><span>{view.seq} / {view.latest_seq}</span></label>{at!=null&&<Button size="sm" onClick={()=>{setAt(null);setFollow(true)}}>返回最新</Button>}</div>
 {view.summary.gaps.length>0&&<details><summary className="muted">采集说明 · {view.summary.gaps.length}</summary>{view.summary.gaps.map(g=><p className="sub" key={g}>{g}</p>)}</details>}
 <div className={s.body}><div className={s.canvas}><ErrorBoundary label="运行图">{mode==='graph'?<Suspense fallback={<Loading>正在加载运行图…</Loading>}><RunGraph view={view} selected={selectedSpan&&isInvocation(selectedSpan)?selectedSpan.parent_id||selected:selected} onSelect={select} follow={follow&&at==null}/></Suspense>:<Waterfall view={view} selected={selected} onSelect={select}/>}</ErrorBoundary><div className={s.legend} style={{marginTop:8}}><span>— 执行顺序</span><span style={{color:'var(--warn)'}}>↺ 恢复 / 重试</span><span style={{color:'var(--ok)'}}>— 产物</span><span style={{color:'var(--accent)'}}>┄ 数据依赖（选中节点显示）</span></div><p className="sub" style={{marginTop:8}}>只展示已发生的步骤；执行结束、检查通过与人工采纳分别记录。</p></div>
 {narrow?<Drawer open={!!selectedSpan} onOpenChange={open=>{if(!open)select('')}} side="bottom" title="节点检查" returnFocusRef={trigger}>{selectedSpan&&<Inspector rid={rid} at={at} span={selectedSpan} view={view} onSelect={select}/>}</Drawer>:<div className={s.inspector}><Card><CardHeader title="节点检查">{selectedSpan&&<Button size="sm" variant="ghost" onClick={()=>select('')}>关闭</Button>}</CardHeader>{selectedSpan?<Inspector rid={rid} at={at} span={selectedSpan} view={view} onSelect={select}/>:<p className="sub" style={{padding:16}}>选择节点查看执行代次、输入版本、工具调用和准确版本的证据。</p>}</Card></div>}
 </div></div>
}
function Inspector({rid,at,span,view,onSelect}:{rid:string;at:number|null;span:TraceSpan;view:TraceView;onSelect:(id:string)=>void}){
 const {data:detail,error}=useQuery({queryKey:['trace-span',rid,span.id,at,span.last_seq],queryFn:()=>api<TraceSpan>(`/runs/${rid}/trace/spans/${encodeURIComponent(span.id)}${at==null?'':`?at_seq=${at}`}`)})
 const [tab,setTab]=useState('overview'),metadata=detail?.metadata||span.metadata
 const [reference,setReference]=useState<{id:string;revision:number}|null>(null)
 useEffect(()=>{setReference(null);setTab('overview')},[span.id])
 const children=view.spans.filter(x=>x.parent_id===span.id)
 return <div style={{display:'flex',flexDirection:'column',gap:12,padding:16}} data-testid="trace-inspector"><h3>{span.name}</h3><Badge tone={statusTone(span)}>{statusLabel[span.status]||span.status}</Badge><dl className={s.kv}><dt>执行代次</dt><dd>{span.generation}</dd><dt>输入修订</dt><dd>{span.input_version??'未记录'}</dd><dt>开始</dt><dd>{span.started_at?dateTime(span.started_at):'未采集'}</dd><dt>结束</dt><dd>{span.ended_at?dateTime(span.ended_at):'未采集'}</dd><dt>耗时</dt><dd>{span.duration_ms==null?'未采集':duration(span.duration_ms)}{span.timing==='observed'?' · 事件间隔':''}</dd><dt>事件范围</dt><dd>{span.first_seq} → {span.last_seq}</dd></dl>
 {!!span.metadata.error&&<InlineError>{String(span.metadata.error)}</InlineError>}
 {children.length>0&&<><h4>工具调用 · {children.length}</h4>{children.map(c=><Button key={c.id} size="sm" onClick={()=>onSelect(c.id)}>{c.name} · {statusLabel[c.status]||c.status}</Button>)}</>}
 {span.parent_id&&<Button size="sm" onClick={()=>onSelect(span.parent_id!)}>返回父调用</Button>}
 {span.artifact_refs.map(ref=><Button key={ref.id+'@'+ref.revision} size="sm" onClick={()=>setReference(ref)}>查看记录与依据 · 修订 {ref.revision}</Button>)}{reference&&<Suspense fallback={<Loading/>}><ObjectDetails reference={reference}/></Suspense>}
 <Seg label="节点详情" value={tab} onChange={setTab} options={[{value:'overview',label:'概要'},{value:'io',label:'输入 / 输出'},{value:'events',label:'事件'}]}/>
 {error&&<InlineError>{String(error)}</InlineError>}
 {tab==='overview'&&<details><summary>关联记录</summary><pre className={s.json}>{JSON.stringify(Object.fromEntries(Object.entries(metadata).filter(([k])=>!['events','arguments','result'].includes(k))),null,2)}</pre></details>}
 {tab==='io'&&<><h4>执行输入</h4><pre className={s.json}>{JSON.stringify(metadata.arguments??{input_revision:span.input_version,role:metadata.role,report:metadata.report},null,2)}</pre><h4>执行输出</h4><pre className={s.json}>{JSON.stringify(metadata.result??{artifacts:span.artifact_refs,status:span.status,error:metadata.error},null,2)}</pre></>}
 {tab==='events'&&<><p className="sub">{Number(metadata.event_count)||0} 条宿主事件，最多显示最近 80 条；历史回放仅显示当时已收到的记录。</p>{Array.isArray(metadata.events)?metadata.events.map((e:any)=><details key={e.seq}><summary className={s.event}><time>{dateTime(e.at)}</time><span>#{e.seq} · {e.event.type||'event'}</span></summary><pre className={s.json}>{JSON.stringify(e.event,null,2)}</pre></details>):<p className="sub">此节点未采集宿主事件。</p>}</>}
 </div>
}

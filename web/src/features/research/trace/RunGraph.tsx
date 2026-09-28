import {useEffect,useMemo,useRef,useState} from 'react'
import {ReactFlow,ReactFlowProvider,Controls,Background,Handle,Position,useReactFlow,type Node,type Edge,type NodeProps} from '@xyflow/react'
import ELK from 'elkjs/lib/elk.bundled.js'
import '@xyflow/react/dist/style.css'
import type {TraceSpan,TraceView} from '../../../types/trace_view'
import {duration} from '../../../lib/format'
import {token,useThemeVersion} from '../../../lib/tokens'
import {Badge} from '../../../ui'
import {childrenOf,executorLabel,groupTools,isError,isInvocation,stages,statusLabel,statusTone} from './model'
import s from './trace.module.css'
type Data={span:TraceSpan;children:TraceSpan[];selected:boolean;onSelect:(id:string)=>void}
type GNode=Node<Data,'stage'>
const WIDTH=280
function estimateHeight(span:TraceSpan,children:TraceSpan[]){const groups=groupTools(children);return 58+(span.kind==='agent'&&groups.length?10+groups.length*24+groups.reduce((n,g)=>n+(g.failed?18:0),0):0)}
function StageNode({data}:NodeProps<GNode>){
  const {span,children,selected}=data;const groups=span.kind==='agent'?groupTools(children):[]
  return <div className={s.node} data-selected={selected?'true':undefined} data-status={span.status} role="button" tabIndex={0} aria-label={`${span.name}，${statusLabel[span.status]||span.status}，${duration(span.duration_ms)}`} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();data.onSelect(span.id)}}}>
    <Handle type="target" position={Position.Top} style={{opacity:0}}/>
    <div className={s.nodeHead}><b>{span.name}</b><Badge tone={statusTone(span)} style={{height:18,fontSize:11}}>{statusLabel[span.status]||span.status}</Badge></div>
    <div className={s.nodeMeta}><span>{executorLabel[span.executor]||span.executor}{span.attempt?` · 尝试 ${span.attempt}`:''}</span><span>{span.status==='running'?'计时中':duration(span.duration_ms)}</span>{span.tool_count>0&&<span>{span.tool_count} 次调用</span>}{span.issue_count>0&&<span style={{color:'var(--warn)'}}>{span.issue_count} 个问题</span>}{span.artifact_refs.length>0&&<span>{span.artifact_refs.length} 项产物</span>}</div>
    {groups.length>0&&<div className={s.tools}>{groups.map(g=><div key={g.key}><div className={s.toolRow}><span style={{width:44,fontWeight:500}}>{g.label}</span><span className={s.bar}><i style={{width:`${Math.round(100*g.count/Math.max(1,children.length))}%`}}/></span><span className="muted">{g.count} 次{g.maxMs?` · 最长 ${duration(g.maxMs)}`:''}</span></div>{g.tools.filter(t=>isError(t)||t.kind==='rejected_tool').slice(0,2).map(t=><div key={t.id} className={s.toolRow+' '+s.fail}><span style={{width:44,paddingLeft:8}}>└</span><span style={{color:'var(--danger)'}}>{t.name} · {t.kind==='rejected_tool'?'被拒':statusLabel[t.status]||t.status}</span></div>)}</div>)}</div>}
    <Handle type="source" position={Position.Bottom} style={{opacity:0}}/>
  </div>
}
const nodeTypes={stage:StageNode};const elk=new ELK()
function Inner({view,selected,onSelect,follow}:{view:TraceView;selected:string;onSelect:(id:string)=>void;follow:boolean}){
  const flow=useReactFlow();const theme=useThemeVersion()
  const [positions,setPositions]=useState<Record<string,{x:number;y:number}>>({});const cache=useRef<Record<string,{x:number;y:number}>>({});const centered=useRef('')
  const stageSpans=useMemo(()=>stages(view),[view])
  const key=stageSpans.map(x=>x.id+':'+childrenOf(view,x.id).length).join('|')
  const structural=useMemo(()=>view.links.filter(l=>l.kind!=='dependency'&&stageSpans.some(x=>x.id===l.source)&&stageSpans.some(x=>x.id===l.target)),[view,stageSpans])
  useEffect(()=>{let live=true
    const children=stageSpans.map(x=>({id:x.id,width:WIDTH,height:estimateHeight(x,childrenOf(view,x.id))}))
    const edges=structural.map(l=>({id:l.id,sources:[l.source],targets:[l.target]}))
    elk.layout({id:'root',layoutOptions:{'elk.algorithm':'layered','elk.direction':'DOWN','elk.spacing.nodeNode':'40','elk.layered.spacing.nodeNodeBetweenLayers':'56','elk.layered.nodePlacement.strategy':'NETWORK_SIMPLEX'},children,edges}).then(g=>{if(!live)return;const next:Record<string,{x:number;y:number}>={};for(const n of g.children||[])next[n.id]={x:n.x||0,y:n.y||0};cache.current=next;setPositions(next)})
    return()=>{live=false}
  },[key]) // eslint-disable-line react-hooks/exhaustive-deps
  const nodes:GNode[]=useMemo(()=>stageSpans.map(x=>({id:x.id,type:'stage' as const,position:positions[x.id]||cache.current[x.id]||{x:0,y:0},data:{span:x,children:childrenOf(view,x.id),selected:x.id===selected,onSelect},draggable:false,selectable:true})),[stageSpans,positions,selected,view,onSelect])
  const edges:Edge[]=useMemo(()=>{const muted=token('line-strong')||'#9AA3B2',warn=token('warn'),accent=token('accent'),ok=token('ok')
    const base=structural.map(l=>({id:l.id,source:l.source,target:l.target,type:'smoothstep',label:l.kind==='repair'?'↺ 修复':l.kind==='recovery'?'↺ 恢复':l.kind==='artifact'?'产物':undefined,style:{stroke:l.kind==='repair'||l.kind==='recovery'?warn:l.kind==='artifact'?ok:muted,strokeWidth:l.kind==='sequence'?1.4:1.8},labelStyle:{fill:l.kind==='repair'||l.kind==='recovery'?warn:undefined,fontSize:11},markerEnd:{type:'arrowclosed' as const,color:l.kind==='repair'||l.kind==='recovery'?warn:l.kind==='artifact'?ok:muted,width:16,height:16}}))
    const deps=selected?view.links.filter(l=>l.kind==='dependency'&&(l.source===selected||l.target===selected)&&stageSpans.some(x=>x.id===l.source)&&stageSpans.some(x=>x.id===l.target)).map(l=>({id:l.id,source:l.source,target:l.target,type:'smoothstep',label:'数据依赖',style:{stroke:accent,strokeDasharray:'5 4',strokeWidth:1.4},labelStyle:{fill:accent,fontSize:11},markerEnd:{type:'arrowclosed' as const,color:accent,width:14,height:14}})):[]
    return [...base,...deps]},[structural,selected,view,stageSpans,theme])
  const running=['queued','running'].includes(view.task_status)
  useEffect(()=>{if(!Object.keys(positions).length)return;const target=selected||(follow&&running?[...stageSpans].reverse().find(x=>x.status==='running')?.id||stageSpans[stageSpans.length-1]?.id:'');if(!target){if(!centered.current){centered.current='__fit__';setTimeout(()=>flow.fitView({padding:.15,maxZoom:1}),60)}return}if(centered.current===target)return;const p=positions[target];if(!p)return;centered.current=target;flow.setCenter(p.x+WIDTH/2,p.y+80,{zoom:Math.max(.75,Math.min(1,flow.getZoom()||1)),duration:250})},[positions,selected,follow,running,stageSpans,flow])
  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} onNodeClick={(_,n)=>onSelect(n.id)} minZoom={.3} maxZoom={1.5} proOptions={{hideAttribution:true}} data-testid="run-graph"><Background gap={20} color={token('line')||'#e5e5e5'}/><Controls showInteractive={false}/></ReactFlow>
}
export function RunGraph(props:{view:TraceView;selected:string;onSelect:(id:string)=>void;follow:boolean}){
  const empty=!props.view.spans.some(x=>!isInvocation(x))
  return <div className={s.graph}>{empty?<p className="muted" style={{padding:24,fontSize:13}}>尚无已执行节点。系统不会预画未发生的研究步骤。</p>:<ReactFlowProvider><Inner {...props}/></ReactFlowProvider>}</div>
}

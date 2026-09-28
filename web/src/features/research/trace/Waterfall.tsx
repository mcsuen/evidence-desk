import {useEffect,useRef,useState} from 'react'
import type {TraceSpan,TraceView} from '../../../types/trace_view'
import {clock,duration} from '../../../lib/format'
import {Icon} from '../../../ui'
import {isError,isInvocation,statusLabel} from './model'
import s from './trace.module.css'
export function Waterfall({view,selected,onSelect}:{view:TraceView;selected:string;onSelect:(id:string)=>void}){
  const [expanded,setExpanded]=useState<Set<string>>(()=>new Set(view.spans.filter(x=>x.status==='running'&&!isInvocation(x)).map(x=>x.id)))
  const spans=view.spans;const times=spans.flatMap(x=>[x.started_at,x.ended_at].filter(Boolean).map(v=>Date.parse(v!))).filter(n=>!Number.isNaN(n))
  const start=times.length?Math.min(...times):0,end=times.length?Math.max(...times,start+1):1,range=Math.max(1,end-start)
  const rows:TraceSpan[]=[];for(const x of spans.filter(y=>!isInvocation(y))){rows.push(x);if(expanded.has(x.id))rows.push(...spans.filter(t=>isInvocation(t)&&t.parent_id===x.id))}
  const list=useRef<HTMLDivElement>(null),keyboard=useRef(false)
  useEffect(()=>{const row=list.current?.querySelector<HTMLElement>('[aria-selected="true"]');row?.scrollIntoView({block:'nearest'});if(keyboard.current){row?.focus({preventScroll:true});keyboard.current=false}},[selected])
  useEffect(()=>{const parent=view.spans.find(x=>x.id===selected)?.parent_id;if(parent)setExpanded(prev=>new Set([...prev,parent]))},[selected,view.spans])
  const toggle=(id:string)=>setExpanded(prev=>{const n=new Set(prev);if(n.has(id))n.delete(id);else n.add(id);return n})
  return <div className={s.waterfall} ref={list} role="treegrid" aria-label="执行瀑布图" data-testid="waterfall">
    <div className={s.wfHead} role="row"><span>阶段 / 调用</span><span>状态</span><span>耗时</span><span>执行时间 · {times.length?clock(new Date(start).toISOString()):'缺失'}</span></div>
    {rows.map((x,i)=>{const child=isInvocation(x);const hasChildren=!child&&spans.some(t=>isInvocation(t)&&t.parent_id===x.id)
      const st=x.started_at?Date.parse(x.started_at):NaN,en=x.ended_at?Date.parse(x.ended_at):NaN
      const left=Number.isNaN(st)?null:(st-start)/range*100,width=Number.isNaN(st)||Number.isNaN(en)?null:Math.max(.4,(en-st)/range*100)
      return <div key={x.id} role="row" aria-level={child?2:1} aria-selected={x.id===selected} tabIndex={x.id===selected||(!selected&&i===0)?0:-1} className={[s.wfRow,child&&s.child,isError(x)&&s.err].filter(Boolean).join(' ')} onClick={()=>onSelect(x.id)} onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const next=rows[i+(e.key==='ArrowDown'?1:-1)];if(next){keyboard.current=true;onSelect(next.id)}}if(e.key==='ArrowRight'&&hasChildren&&!expanded.has(x.id))toggle(x.id);if(e.key==='ArrowLeft'&&hasChildren&&expanded.has(x.id))toggle(x.id);if(e.key==='Enter')onSelect(x.id)}}>
        <div className={s.wfName}><button type="button" aria-label={(expanded.has(x.id)?'收起':'展开')+x.name} disabled={!hasChildren} onClick={e=>{e.stopPropagation();toggle(x.id)}}>{hasChildren?<Icon name="chevron" size={12} style={{transform:expanded.has(x.id)?'rotate(0)':'rotate(-90deg)'}}/>:'·'}</button><span>{x.name}{x.ordinal?<small className="muted"> #{x.ordinal}</small>:null}</span></div>
        <span>{statusLabel[x.status]||x.status}</span><span>{duration(x.duration_ms)}</span>
        <div className={s.track} title={left!=null?`${clock(x.started_at)} → ${clock(x.ended_at)} · ${x.timing==='measured'?'独立计时':'观察时间'}`:'未采集开始时间'}>{left!=null?<i className={isError(x)?s.err:''} style={{left:`${left}%`,width:`${width??.4}%`}}/>:<span className="muted" style={{fontSize:11,paddingLeft:6}}>未采集开始时间</span>}</div>
      </div>})}
    {!rows.length&&<p className="muted" style={{padding:16,fontSize:13}}>尚无已执行节点。</p>}
  </div>
}

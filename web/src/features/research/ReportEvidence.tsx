import {lazy,Suspense,useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import type {Assertion,EvidenceAnchor,Ref,ReportView,SourceVersion,Value} from '../../types/report_view'
import type {Calculation} from '../../types/calculation'
import type {Observation} from '../../types/observation'
import {api} from '../../lib/api'
import {Badge,Button,Icon,InlineError,Loading} from '../../ui'
import {key,SourceIdentity,Status} from '../../workbench/shared'
import {originalUrl,pageLabel,sourceGroups,type ReadingSelection} from './reportReading'
import s from './research.module.css'

const PdfPage=lazy(()=>import('./PdfPage').then(m=>({default:m.PdfPage})))
type EvidenceObject=Value|EvidenceAnchor|SourceVersion|Calculation|Assertion|Observation
type ObjectView={object:EvidenceObject;dependencies:EvidenceObject[];current_validity:{status:string;reason?:string}}
const isAnchor=(item:EvidenceObject):item is EvidenceAnchor=>'quote' in item
const isValue=(item:EvidenceObject):item is Value=>'kind' in item&&'amount' in item
const isCalculation=(item:EvidenceObject):item is Calculation=>'operation' in item
const isSource=(item:EvidenceObject):item is SourceVersion=>'blocks' in item

function Highlight({text,literal}:{text:string;literal?:string}){
  if(!literal||!text.includes(literal))return <>{text}</>
  return <>{text.split(literal).map((part,i)=><span key={i}>{i>0&&<mark className={s.quoteHighlight}>{literal}</mark>}{part}</span>)}</>
}

function OriginalExcerpt({anchor,source,literal}:{anchor:EvidenceAnchor;source:SourceVersion;literal?:string}){
  const [context,setContext]=useState(false),[preview,setPreview]=useState(false)
  const block=source.blocks.find(b=>b.id===anchor.block_id)
  // Server offsets count Unicode code points; JS string offsets count UTF-16 units.
  const chars=Array.from(block?.text||'')
  const located=chars.slice(anchor.start,anchor.end).join('')===anchor.quote
  const before=located?chars.slice(Math.max(0,anchor.start-240),anchor.start).join(''):''
  const after=located?chars.slice(anchor.end,anchor.end+240).join(''):''
  return <section className={s.originalExcerpt} data-testid="evidence-excerpt">
    <div className={s.excerptLocation}><Icon name="file" size={12}/>{anchor.page?`第 ${anchor.page} 页`:'原文摘录'}</div>
    <blockquote className={s.quote}>
      {context&&before&&<span className={s.quoteContext}>{anchor.start>240?'…':''}{before}</span>}
      <Highlight text={anchor.quote} literal={literal}/>
      {context&&after&&<span className={s.quoteContext}>{after}{chars.length>anchor.end+240?'…':''}</span>}
    </blockquote>
    <div className={s.excerptActions}>
      {located&&(before||after)&&<Button variant="ghost" size="sm" aria-expanded={context} onClick={()=>setContext(!context)}>{context?'收起前后文':'查看前后文'}</Button>}
      {anchor.page&&source.media_type==='application/pdf'&&<Button variant="ghost" size="sm" aria-expanded={preview} onClick={()=>setPreview(!preview)}>{preview?'收起页面':`预览第 ${anchor.page} 页`}</Button>}
      <a href={originalUrl(anchor.source,anchor.page)} target="_blank" rel="noreferrer">打开原件{anchor.page?`第 ${anchor.page} 页`:''}<Icon name="external" size={12}/></a>
    </div>
    {preview&&anchor.page&&<Suspense fallback={<Loading>正在加载原件页面…</Loading>}><PdfPage page={anchor.page} bbox={anchor.bbox.length===4?anchor.bbox:null} url={originalUrl(anchor.source)}/></Suspense>}
  </section>
}

function SourceEvidence({source,anchors,literal}:{source:SourceVersion;anchors:EvidenceAnchor[];literal?:string}){
  const {data,error}=useQuery({queryKey:['object',key(source)],queryFn:()=>api<ObjectView>(`/objects/${source.id}/revisions/${source.revision}`),refetchInterval:5000})
  return <section className={s.evidenceSource} data-testid="evidence-source">
    <div className={s.sourceHeading}><SourceIdentity role={source.source_role}/><span>原件修订 {source.revision}</span></div>
    <h3>{source.title}</h3>
    <p className={s.sourceDate}>{source.published_at&&`${new Date(source.published_at).toLocaleDateString('zh-CN')} · `}{pageLabel(anchors)}</p>
    {data&&data.current_validity.status!=='available'&&<div className={s.validityNotice}><Status value={data.current_validity.status}/><p>{data.current_validity.reason}。此处保留报告引用的原件版本。</p></div>}
    {error&&<p className="sub">当前有效性暂时无法读取，以下为报告保存的原文。</p>}
    {anchors.map(anchor=><OriginalExcerpt key={key(anchor)} anchor={anchor} source={source} literal={literal}/>)}
  </section>
}

const operations:Record<Calculation['operation'],string>={add:'求和',subtract:'差额',multiply:'乘积',divide:'相除',ratio:'比例',growth:'增长率',change:'变动',quarterize:'季度拆分'}

export function ReportEvidence({report,selection}:{report:ReportView;selection:ReadingSelection}){
  const direct=selection.refs.map(ref=>report.evidence.find(e=>key(e)===key(ref))).filter((e):e is EvidenceAnchor=>!!e)
  const objectRef=selection.refs.length===1&&!direct.length?selection.refs[0]:null
  const {data,error}=useQuery({queryKey:['object',objectRef&&key(objectRef)],queryFn:()=>api<ObjectView>(`/objects/${objectRef!.id}/revisions/${objectRef!.revision}`),enabled:!!objectRef,refetchInterval:5000})
  const dependencies=objectRef?data?.dependencies||[]:[]
  const anchors=direct.length?direct:dependencies.filter(isAnchor)
  const sources=[...report.sources,...dependencies.filter(isSource)]
  const groups=sourceGroups(anchors,anchors,sources)
  const value=objectRef&&data&&isValue(data.object)?data.object:null
  const assertion=objectRef&&data&&'statement' in data.object?data.object as Assertion:null
  const calculations=dependencies.filter(isCalculation)
  const observation=value?.observation&&dependencies.find(item=>key(item)===key(value.observation!))
  const literal=selection.literal||(observation&&'literal' in observation?observation.literal:undefined)
  const valueLabel=(ref:Ref)=>report.value_labels[key(ref)]||dependencies.filter(isValue).find(v=>key(v)===key(ref))?.amount||'未记录'
  if(objectRef&&!data)return error?<InlineError>{error.message}</InlineError>:<Loading>正在定位原文…</Loading>
  return <>
    {data&&data.current_validity.status!=='available'&&<div className={s.validityNotice}><Status value={data.current_validity.status}/><p>{data.current_validity.reason}</p></div>}
    {value&&<section className={s.valueDetail} data-testid="value-detail">
      <div className={s.sourceHeading}><Badge>{value.kind==='observed'?'原文数值':value.kind==='derived'?'计算结果':'模型假设'}</Badge><span>数值修订 {value.revision}</span></div>
      <div className={s.valueAmount}>{valueLabel(value)}</div>
      <dl className={s.kv}><dt>指标</dt><dd>{value.metric}</dd><dt>期间</dt><dd>{value.period}</dd><dt>口径</dt><dd>{value.basis||'未记录'}{value.share_basis&&` · ${value.share_basis}`}</dd></dl>
      {value.reason&&<p className="sub">{value.reason}</p>}
      {value.limitations.map((limitation,i)=><p className="sub" key={i}>{limitation}</p>)}
    </section>}
    {selection.literal&&<div className={s.literalNote}><Badge>原文定位</Badge><span>“{selection.literal}”出现在下方引文中，具体单位与口径请结合上下文核对。</span></div>}
    {assertion&&<section className={s.valueDetail}><h3>{assertion.title}</h3><p>{assertion.statement}</p>{assertion.alternative&&<p className="sub">替代解释：{assertion.alternative}</p>}</section>}
    {calculations.map(calculation=><section key={key(calculation)} className={s.calc}><span className="kicker">计算口径 · {operations[calculation.operation]}</span><p>{calculation.inputs.map(ref=>valueLabel(ref)).join(' · ')}</p><b>结果：{calculation.amount} {calculation.unit}</b></section>)}
    {groups.length>0?<div className={s.evidenceSources}>{groups.map(group=><SourceEvidence key={key(group.source)} {...group} literal={literal}/>)}</div>:<p className="sub">这项内容没有直接关联的原文引用。</p>}
  </>
}

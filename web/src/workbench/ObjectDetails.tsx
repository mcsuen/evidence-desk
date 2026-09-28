import {lazy,Suspense,useState} from 'react'
import {useData,Pending,key,Status,SourceIdentity} from './shared'
import {Badge,Button,Loading} from '../ui'
import type {Ref} from '../types/ref'
import s from '../features/research/research.module.css'
const PdfPage=lazy(()=>import('../features/research/PdfPage').then(m=>({default:m.PdfPage})))
export default function ObjectDetails({reference}:{reference:Ref}){
 const {data,error}=useData('/objects/'+encodeURIComponent(reference.id)+'/revisions/'+reference.revision),[page,setPage]=useState<string|null>(null)
 if(!data)return <Pending error={error}/>
 const o=data.object
 return <div className={s.railBody} data-testid="object-details"><div className={s.meta}><Badge>修订 {o.revision}</Badge><Status value={data.current_validity.status}/></div>{data.current_validity.reason&&<p>{data.current_validity.reason}</p>}<h3>{o.title||o.metric||(o.name==='independent'?'独立复核':o.name==='deterministic'?'内容与引用检查':'原文依据')}</h3>{o.status&&<Status value={o.status}/>} {o.reason&&<p>{o.reason}</p>}{o.findings?.map((f:any,i:number)=><p key={i}>{f.message}</p>)}{o.coverage?.length>0&&<p className="sub">检查覆盖：{o.coverage.join(' · ')}</p>}{o.statement&&<p>{o.statement}</p>}{o.rationale&&<p>{o.rationale}</p>}{o.amount!==undefined&&<><div className={s.calc}>{o.amount} {o.unit}</div><p>{o.period} · {o.basis} · {o.subject}</p></>}{o.alternative&&<p>替代解释：{o.alternative}</p>}{o.next_check&&<p>下次核查：{o.next_check}</p>}{o.limitations?.map((v:string,i:number)=><p className="sub" key={i}>{v}</p>)}
 {data.dependencies.filter((d:any)=>d.operation).map((d:any)=><div key={key(d)} className={s.calc}>{d.operation} → {d.amount} {d.unit}</div>)}
 {data.dependencies.filter((d:any)=>d.quote).map((e:any)=>{const source=data.dependencies.find((d:any)=>key(d)===key(e.source));return <section key={key(e)}><b>{source?.title||e.source.id}</b><p className="sub">原件修订 {e.source.revision} · {e.page?`第 ${e.page} 页`:e.block_id}</p><blockquote className={s.quote}>{e.quote}</blockquote><div className={s.chips}><a href={`/api/v1/sources/${e.source.id}/revisions/${e.source.revision}/original`} target="_blank" rel="noreferrer">打开原件 ↗</a>{e.page&&source?.media_type==='application/pdf'&&<Button size="sm" onClick={()=>setPage(page===key(e)?null:key(e))}>查看原件页面</Button>}</div>{page===key(e)&&<Suspense fallback={<Loading/>}><PdfPage page={e.page} bbox={null} url={`/api/v1/sources/${e.source.id}/revisions/${e.source.revision}/original`}/></Suspense>}</section>})}
 {o.blocks&&<><div className={s.meta}><SourceIdentity role={o.source_role}/><a href={`/api/v1/sources/${o.id}/revisions/${o.revision}/original`} target="_blank" rel="noreferrer">下载原件 ↗</a></div><p className="sub">来源身份单独展示，核验与人工采纳以各自记录为准。</p>{o.blocks.map((b:any)=><section key={b.id}><small className="muted">{b.page?`第 ${b.page} 页 · `:''}{b.id}</small><p style={{whiteSpace:'pre-wrap'}}>{b.text}</p></section>)}</>}
 {!o.blocks&&!data.dependencies.some((d:any)=>d.quote)&&<p className="sub">此对象没有直接原文引用。</p>}
 </div>
}

import type {ReportView,ReportDocument,Paragraph} from '../../types/report_view'
import {useData,key,Pending} from '../../workbench/shared'
import {Card,Table} from '../../ui'
import s from './research.module.css'
export default function ReportDiff({before,after}:{before:ReportDocument;after:ReportView}){
 const {data,error}=useData<ReportView>(`/reports/${before.id}/revisions/${before.revision}`)
 if(!data)return <Pending error={error}/>
 const inline=(spans:Paragraph['inlines'],view:ReportView)=>spans.map(p=>p.type==='text'?p.text:p.type==='value'?view.value_labels[key(p.ref)]:`〔引文：${view.evidence.find(e=>key(e)===key(p.ref))?.quote.slice(0,60)||'原件'}〕`).join('')
 const section=(section:ReportDocument['sections'][number]|undefined,view:ReportView)=>!section?<p className="sub">此版本没有该章节</p>:<><b>{section.title}</b>{section.blocks.map(b=>b.type==='paragraph'?<p key={b.id}>{inline(b.inlines,view)}</p>:b.type==='table'?<div key={b.id}><b>{b.title}</b>{b.rows.map((row,i)=><p key={i}>{row.map(cell=>inline(cell,view)).join(' ｜ ')}</p>)}</div>:<div key={b.id}><b>{b.title}</b>{b.series.map(series=><p key={series.name}>{series.name}：{series.values.map((r,i)=>b.categories[i]+' '+(r?view.value_labels[key(r)]:'缺项')).join('；')}</p>)}</div>)}</>
 const ids=[...new Set([...before.sections.map(s=>s.id),...after.document.sections.map(s=>s.id)])]
 return <Card className={s.railBody}><h3>版本差异</h3><div className={s.metricsWrap}><Table><thead><tr><th>上一版本 · {before.revision}</th><th>当前版本 · {after.document.revision}</th></tr></thead><tbody><tr><td>{before.title}</td><td>{after.document.title}</td></tr><tr><td>{before.summary.map(p=><p key={p.id}>{inline(p.inlines,data)}</p>)}</td><td>{after.document.summary.map(p=><p key={p.id}>{inline(p.inlines,after)}</p>)}</td></tr>{ids.map(id=><tr key={id}><td>{section(before.sections.find(s=>s.id===id),data)}</td><td>{section(after.document.sections.find(s=>s.id===id),after)}</td></tr>)}<tr><td>{before.gaps.join('；')}</td><td>{after.document.gaps.join('；')}</td></tr></tbody></Table></div></Card>
}

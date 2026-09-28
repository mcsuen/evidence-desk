import {lazy,Suspense,useCallback,useRef,useState} from 'react'
import type {Paragraph,Ref,ReportView,TableBlock} from '../../types/report_view'
import {Badge,Button,Card,Icon,Loading,NumberChip,Table} from '../../ui'
import {key} from '../../workbench/shared'
import {EvidenceRail} from './EvidenceRail'
import {ReportSources} from './ReportSources'
import {citations,followingCitations,linkedText,pageLabel,sourceGroups,uniqueRefs,type Inline,type ReadingSelection,type SelectEvidence} from './reportReading'
import s from './research.module.css'

const ReportChart=lazy(()=>import('./ReportChart'))
const ReportEvidence=lazy(()=>import('./ReportEvidence').then(m=>({default:m.ReportEvidence})))

function ReportInlines({inlines,report,selected,onSelect,rowRefs=[]}:{inlines:Inline[];report:ReportView;selected:ReadingSelection|null;onSelect:SelectEvidence;rowRefs?:Ref[]}){
  return <>{inlines.map((span,i)=>{
    if(span.type==='citation')return null
    if(span.type==='value'){
      const value=report.values.find(v=>key(v)===key(span.ref))
      return <NumberChip key={i} aria-label={'查看数值依据：'+report.value_labels[key(span.ref)]}
        title={`${value?.metric||'数值'} · ${value?.period||''} · 点击查看原文与口径`}
        active={selected?.refs.some(ref=>key(ref)===key(span.ref))}
        onClick={e=>onSelect({refs:[span.ref],title:'数值与原文'},e.currentTarget)}>{report.value_labels[key(span.ref)]}</NumberChip>
    }
    const refs=followingCitations(inlines,i)
    return <span key={i}>{linkedText(span.text,refs.length?refs:rowRefs,report.evidence).map((part,j)=>part.ref?
      <NumberChip key={j} className={s.quotedNumber} aria-label={'查看原文中的数字：'+part.text}
        title="查看此处引用的原文，结合上下文核对单位与口径" active={selected?.literal===part.text&&selected.refs.some(ref=>key(ref)===key(part.ref!))}
        onClick={e=>onSelect({refs:[part.ref!],title:'数字的原文出处',literal:part.text},e.currentTarget)}>{part.text}</NumberChip>:<span key={j}>{part.text}</span>)}</span>
  })}</>
}

function ReportParagraph({paragraph,report,selected,onSelect}:{paragraph:Paragraph;report:ReportView;selected:ReadingSelection|null;onSelect:SelectEvidence}){
  const refs=citations(paragraph.inlines)
  return <div className={s.reportParagraph}>
    <p><ReportInlines inlines={paragraph.inlines} report={report} selected={selected} onSelect={onSelect}/></p>
    <div className={s.paragraphMeta}>
      <ReportSources refs={refs} report={report} onSelect={onSelect}/>
      {paragraph.assertions.map((ref,i)=><Button key={key(ref)} variant="ghost" size="sm" title={report.assertions.find(a=>key(a)===key(ref))?.title} onClick={e=>onSelect({refs:[ref],title:'判断依据'},e.currentTarget)}>{paragraph.assertions.length>1?`判断依据 ${i+1}`:'查看判断依据'} <Icon name="arrow" size={12}/></Button>)}
    </div>
  </div>
}

function ReportTable({block,report,selected,onSelect}:{block:TableBlock;report:ReportView;selected:ReadingSelection|null;onSelect:SelectEvidence}){
  return <section className={s.reportTable}>
    <div className={s.tableHeading}><h3>{block.title}</h3><span>点选数字查看原文</span></div>
    <div className={s.metricsWrap}><Table><thead><tr>{block.columns.map((column,i)=><th key={i}>{column}</th>)}</tr></thead><tbody>
      {block.rows.map((row,i)=>{
        const rowRefs=citations(row.flat())
        return <tr key={i}>{row.map((cell,j)=><td key={j}><ReportInlines inlines={cell} report={report} selected={selected} onSelect={onSelect} rowRefs={j?rowRefs:[]}/><ReportSources refs={citations(cell)} report={report} onSelect={onSelect} compact/></td>)}</tr>
      })}
    </tbody></Table></div>
    {block.note&&<p className={s.tableNote}>{block.note}</p>}
  </section>
}

export function Report({report}:{report:ReportView}){
  const [selected,setSelected]=useState<ReadingSelection|null>(null),trigger=useRef<HTMLElement|null>(null)
  const close=useCallback(()=>setSelected(null),[])
  const select:SelectEvidence=(selection,el)=>{trigger.current=el;setSelected(selection)}
  const selectValue=(ref:Ref,el:HTMLElement)=>select({refs:[ref],title:'数值与原文'},el)
  const refs=uniqueRefs([...report.document.summary,...report.document.sections.flatMap(section=>section.blocks)].flatMap(block=>block.type==='paragraph'?citations(block.inlines):block.type==='table'?citations(block.rows.flat(2)):[]))
  const groups=sourceGroups(refs,report.evidence,report.sources)
  return <div className={s.reading+(selected?' '+s.withRail:'')} data-testid="research-report"><article className={s.article}>
    <section className={s.answer} data-testid="research-answer" aria-label="研究结论">
      <div className={s.answerHeading}><h2>研究结论</h2><span><span className={s.linkSample}>数字</span>可点选追溯原文</span></div>
      <ol className={s.judgments}>{report.document.summary.map((paragraph,i)=><li className={s.judgment} key={paragraph.id}><i aria-hidden="true">{i+1}</i><ReportParagraph paragraph={paragraph} report={report} selected={selected} onSelect={select}/></li>)}</ol>
    </section>
    <div className={s.narrative}>{report.document.sections.map(section=><article key={section.id}><h2>{section.title}</h2>{section.blocks.map(block=>block.type==='paragraph'?
      <ReportParagraph key={block.id} paragraph={block} report={report} selected={selected} onSelect={select}/>:
      block.type==='table'?<ReportTable key={block.id} block={block} report={report} selected={selected} onSelect={select}/>:
      <Suspense key={block.id} fallback={<Loading>正在加载图表…</Loading>}><ReportChart block={block} report={report} onSelect={selectValue}/></Suspense>)}</article>)}</div>
    {(report.document.gaps.length>0||report.document.next_steps.length>0)&&<div className={s.twoCol}>
      {report.document.gaps.length>0&&<Card className={s.reportNotes}><h2>研究限制与缺项 <Badge>{report.document.gaps.length}</Badge></h2><ul>{report.document.gaps.map((gap,i)=><li key={i}>{gap}</li>)}</ul></Card>}
      {report.document.next_steps.length>0&&<Card className={s.reportNotes}><h2>下一步验证</h2><ul>{report.document.next_steps.map((step,i)=><li key={i}>{step}</li>)}</ul></Card>}
    </div>}
    {report.assertions.length>0&&<details className={s.section}><summary>判断记录与审核交接 · {report.assertions.length}</summary><div className={s.metricsWrap}><Table><thead><tr><th>判断</th><th>替代解释与限制</th><th>依据</th></tr></thead><tbody>{report.assertions.map(assertion=><tr key={key(assertion)}><td><b>{assertion.title}</b><p>{assertion.statement}</p><small className="muted">修订 {assertion.revision}</small></td><td>{assertion.alternative||'未记录替代解释'}{assertion.limitations.map((limitation,i)=><p key={i}>{limitation}</p>)}{assertion.next_check&&<p>下一步：{assertion.next_check}</p>}</td><td><Button size="sm" onClick={e=>select({refs:[assertion],title:'判断依据'},e.currentTarget)}>{assertion.support.length} 支持 / {assertion.counterevidence.length} 反证</Button></td></tr>)}</tbody></Table></div></details>}
    {groups.length>0&&<details className={s.section}><summary>原件与引用 · {groups.length} 份来源 · {refs.length} 处引文</summary><div className={s.sourceIndex}>{groups.map(({source,anchors})=><button type="button" key={key(source)} onClick={e=>select({refs:anchors,title:source.title},e.currentTarget)}><Icon name="file" size={16}/><span><b>{source.title}</b><small>原件修订 {source.revision} · {pageLabel(anchors)}</small></span><Icon name="arrow" size={14}/></button>)}</div></details>}
  </article><EvidenceRail open={!!selected} onClose={close} title={selected?.title||'原文与数值依据'} returnTo={trigger}>
    {selected&&<Suspense fallback={<Loading>正在定位原文…</Loading>}><ReportEvidence key={selected.refs.map(key).join(',')+selected.literal} report={report} selection={selected}/></Suspense>}
  </EvidenceRail></div>
}

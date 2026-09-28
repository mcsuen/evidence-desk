import type {ReportView,Ref} from '../../types/report_view'
import {Icon} from '../../ui'
import {key} from '../../workbench/shared'
import {pageLabel,sourceGroups,type SelectEvidence} from './reportReading'
import s from './research.module.css'

/** A paragraph's citations stay with it, grouped by immutable source version. */
export function ReportSources({refs,report,onSelect,compact=false}:{refs:Ref[];report:ReportView;onSelect:SelectEvidence;compact?:boolean}){
  const groups=sourceGroups(refs,report.evidence,report.sources)
  if(!groups.length)return null
  const visible=groups.slice(0,compact?1:2)
  return <span className={s.sourceLinks} data-testid="report-sources">
    {visible.map(({source,anchors})=><button type="button" key={key(source)} className={s.sourceLink}
      title={`${source.title} · 原件修订 ${source.revision} · ${pageLabel(anchors)}`}
      aria-label={`查看来源：${source.title} · ${pageLabel(anchors)}`}
      onClick={e=>onSelect({refs:anchors,title:source.title},e.currentTarget)}>
      <Icon name="file" size={12}/><span>{source.title}</span><small>{anchors.length>1?`${anchors.length} 处`:anchors[0].page?`p.${anchors[0].page}`:'原文'}</small>
    </button>)}
    {groups.length>visible.length&&<button type="button" className={s.moreSources}
      onClick={e=>onSelect({refs,title:'本段原文依据'},e.currentTarget)} aria-label={`查看全部 ${groups.length} 份来源`}>另 {groups.length-visible.length} 份来源 <Icon name="arrow" size={12}/></button>}
  </span>
}

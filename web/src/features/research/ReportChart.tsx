import {useMemo} from 'react'
import type {ChartBlock,ReportView,Ref} from '../../types/report_view'
import {NumberChip} from '../../ui'
import {Chart} from '../../ui/Chart'
import {key} from '../../workbench/shared'
export default function ReportChart({block,report,onSelect}:{block:ChartBlock;report:ReportView;onSelect:(ref:Ref,el:HTMLElement)=>void}){
  const option=useMemo(()=>({tooltip:{trigger:'axis',renderMode:'richText',formatter:(items:any)=>items.map((item:any)=>{const ref=block.series[item.seriesIndex].values[item.dataIndex];return item.seriesName+'：'+(ref?report.value_labels[key(ref)]:'未披露')}).join('\n')},legend:{bottom:0},grid:{top:20,bottom:60,left:65,right:15},xAxis:{type:'category',data:block.categories},yAxis:{type:'value'},series:block.series.map(s=>({name:s.name+(s.role==='forecast'?'（预测）':''),type:block.kind==='column'?'bar':'line',connectNulls:false,data:s.values.map(ref=>ref?Number(report.values.find(v=>key(v)===key(ref))?.amount):null),lineStyle:{type:s.role==='forecast'?'dashed':'solid'}}))}),[block,report.values,report.value_labels])
  return <section><h3>{block.title}</h3><Chart option={option} label={block.title}/><p className="sub">单位：{block.unit} {block.note}</p><details><summary>查看准确图表数值</summary>{block.series.map((series,i)=><p key={i}>{series.name}：{series.values.map((r,j)=><span key={j}>{block.categories[j]} {r?<NumberChip aria-label={'查看数值依据：'+report.value_labels[key(r)]} onClick={e=>onSelect(r,e.currentTarget)}>{report.value_labels[key(r)]}</NumberChip>:'未披露'}；</span>)}</p>)}</details></section>
}

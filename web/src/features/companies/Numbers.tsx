import {useEffect,useRef,useState} from 'react'
import * as echarts from 'echarts/core'
import {BarChart} from 'echarts/charts'
import {GridComponent,TooltipComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
import type {CompanyValue,Ref} from '../../types/company_view'
import {Card,CardHeader,EmptyState,NumberChip,Select,Table} from '../../ui'
import {key,Status} from '../../workbench/shared'
import {token,useThemeVersion} from '../../lib/tokens'
echarts.use([BarChart,GridComponent,TooltipComponent,CanvasRenderer])
const group=(v:CompanyValue)=>[v.object.metric,v.object.unit,v.object.basis,v.object.frequency,v.object.currency,v.object.share_basis,v.object.role].filter(Boolean).join(' · ')
export default function Numbers({values,onSelect}:{values:CompanyValue[];onSelect:(r:Ref)=>void}){
 const groups=[...new Set(values.map(group))], [selection,setSelection]=useState(''),current=groups.includes(selection)?selection:groups[0],theme=useThemeVersion(),el=useRef<HTMLDivElement|null>(null)
 const series=values.filter(v=>group(v)===current).sort((a,b)=>a.object.period.localeCompare(b.object.period))
 useEffect(()=>{if(!el.current||!series.length)return;const chart=echarts.init(el.current);chart.setOption({textStyle:{fontFamily:'IBM Plex Sans, Noto Sans SC',color:token('ink-2')},grid:{left:72,right:30,bottom:45,top:25},tooltip:{trigger:'axis',renderMode:'richText',formatter:(items:any)=>{const v=series[items[0]?.dataIndex]?.object;return v?`${v.period}\n${v.amount} ${v.unit}`:''}},xAxis:{type:'category',data:series.map(v=>v.object.period+' · r'+v.object.revision),axisLabel:{color:token('ink-3')},axisLine:{lineStyle:{color:token('line')}}},yAxis:{type:'value',axisLabel:{color:token('ink-3')},splitLine:{lineStyle:{color:token('line')}}},series:[{type:'bar',barMaxWidth:48,itemStyle:{color:token('accent'),borderRadius:[3,3,0,0]},data:series.map(v=>Number(v.object.amount))}]});chart.on('click',p=>{if(series[p.dataIndex])onSelect(series[p.dataIndex].object)});const observer=new ResizeObserver(()=>chart.resize());observer.observe(el.current);return()=>{observer.disconnect();chart.dispose()}},[current,JSON.stringify(series),theme,onSelect])
 if(!values.length)return <EmptyState>研究报告与已采纳判断中的可追溯数值会显示在这里。</EmptyState>
 return <><Card><CardHeader title="数值与期间"><Select aria-label="图表指标与口径" value={current} onChange={e=>setSelection(e.target.value)} style={{marginLeft:'auto',maxWidth:'70%',minWidth:0,width:300}}>{groups.map(g=><option key={g}>{g}</option>)}</Select></CardHeader><div ref={el} style={{height:280}} role="img" aria-label={'数值图表：'+current}/></Card><Card style={{overflowX:'auto'}}><Table><thead><tr><th>指标</th><th>期间</th><th>数值</th><th>单位 · 口径</th><th>版本有效性</th></tr></thead><tbody>{values.map(({object:v,current_validity:validity})=><tr key={key(v)}><td>{v.metric}</td><td>{v.period}</td><td><NumberChip onClick={()=>onSelect(v)} aria-label={'查看数值依据：'+v.metric}>{v.amount}</NumberChip></td><td>{v.unit} · {v.basis}</td><td><Status value={String(validity.status)}/></td></tr>)}</tbody></Table></Card></>
}

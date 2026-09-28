import {useEffect,useRef} from 'react'
import * as echarts from 'echarts/core'
import {LineChart,BarChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import {token,useThemeVersion} from '../lib/tokens'
echarts.use([LineChart,BarChart,GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent,SVGRenderer])
/** Theme-aware ECharts container: colours come from the CSS tokens and follow theme switches. */
export function Chart({option,onSelect,label,height=220}:{option:Record<string,unknown>;onSelect?:(index:number)=>void;label:string;height?:number}){
  const ref=useRef<HTMLDivElement>(null);const version=useThemeVersion()
  useEffect(()=>{if(!ref.current)return
    const chart=echarts.init(ref.current,undefined,{renderer:'svg'})
    const ink3=token('ink-3'),line=token('line')
    chart.setOption({animation:false,color:[token('s1'),token('s2'),token('s3'),token('s4')],textStyle:{fontFamily:'IBM Plex Sans, Noto Sans SC, sans-serif',fontSize:11,color:ink3},
      xAxis:{axisLine:{lineStyle:{color:line}},axisLabel:{color:ink3},...(option.xAxis as object||{})},
      yAxis:{splitLine:{lineStyle:{color:line}},axisLabel:{color:ink3},...(option.yAxis as object||{})},
      tooltip:{backgroundColor:token('surface'),borderColor:line,textStyle:{color:token('ink')},...(option.tooltip as object||{})},
      ...option})
    if(onSelect)chart.on('click',p=>onSelect(p.dataIndex))
    const ro=new ResizeObserver(()=>chart.resize());ro.observe(ref.current)
    return()=>{ro.disconnect();chart.dispose()}
  },[option,onSelect,version])
  return <div ref={ref} role="img" aria-label={label} style={{width:'100%',height}}/>
}
/** Inline sparkline: 2px line, faint area, emphasised endpoint; colour from `color` (a CSS colour or token value). */
export function Spark({values,color='var(--s1)',width=96,height=26}:{values:(number|null)[];color?:string;width?:number;height?:number}){
  const data=values.filter((v):v is number=>v!=null);if(data.length<2)return <span className="muted">—</span>
  const min=Math.min(...data),max=Math.max(...data),span=max-min||1
  const pts=values.map((v,i)=>v==null?null:[i/(values.length-1)*(width-4)+2,height-3-(v-min)/span*(height-8)] as const)
  const segments:string[]=[];let cur:string[]=[];pts.forEach(p=>{if(!p){if(cur.length)segments.push(cur.join(' '));cur=[];return}cur.push(`${p[0].toFixed(1)},${p[1].toFixed(1)}`)});if(cur.length)segments.push(cur.join(' '))
  const last=[...pts].reverse().find(Boolean)
  const first=pts.find(Boolean)
  return <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    {segments.length===1&&first&&last&&<polygon points={`${first[0].toFixed(1)},${height-1} ${segments[0]} ${last[0].toFixed(1)},${height-1}`} fill={color} fillOpacity=".12"/>}
    {segments.map((s,i)=><polyline key={i} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" points={s}/>)}
    {last&&<circle cx={last[0]} cy={last[1]} r="2.6" fill={color}/>}
  </svg>
}

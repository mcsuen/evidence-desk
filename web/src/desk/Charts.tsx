import {useEffect,useRef} from 'react'
import * as echarts from 'echarts/core'
import {LineChart,BarChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
echarts.use([LineChart,BarChart,GridComponent,TooltipComponent,LegendComponent,MarkLineComponent,DataZoomComponent,SVGRenderer])
export function Chart({option,onSelect,label}:{option:any,onSelect?:(index:number)=>void,label:string}){
 const ref=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(!ref.current)return;const chart=echarts.init(ref.current,undefined,{renderer:'svg'});chart.setOption({animation:false,textStyle:{fontFamily:'IBM Plex Sans, Noto Sans SC, sans-serif',fontSize:11},...option});if(onSelect)chart.on('click',p=>onSelect(p.dataIndex));const ro=new ResizeObserver(()=>chart.resize());ro.observe(ref.current);return()=>{ro.disconnect();chart.dispose()}},[option,onSelect])
 return <div ref={ref} className="d-chart" role="img" aria-label={label}/>
}
export function Spark({values}:{values:(number|null)[]}){
 const data=values.filter((v):v is number=>v!=null);if(data.length<2)return <span className="d-muted">—</span>
 const min=Math.min(...data),max=Math.max(...data),span=max-min||1
 const parts:string[]=[];let part='';values.forEach((v,i)=>{if(v==null){if(part)parts.push(part);part='';return}part+=`${i/(values.length-1)*94},${23-(v-min)/span*20} `});if(part)parts.push(part)
 return <svg width="96" height="27" viewBox="0 0 96 27" aria-hidden="true">{parts.map((p,i)=><polyline key={i} fill="none" stroke="#334BFF" strokeWidth="1.5" points={p}/>)}</svg>
}

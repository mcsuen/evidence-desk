export function relativeTime(iso:string|number|null|undefined,now=Date.now()):string{
  if(iso==null||iso==='')return '—'
  const numeric=typeof iso==='number'?iso:/^\d+(\.\d+)?$/.test(iso)?Number(iso):NaN
  const t=Number.isNaN(numeric)?Date.parse(String(iso)):(numeric>1e12?numeric:numeric*1000);if(Number.isNaN(t))return String(iso)
  const diff=Math.max(0,now-t),m=Math.round(diff/60000)
  if(m<1)return '刚刚';if(m<60)return `${m} 分钟前`
  const h=Math.round(m/60);if(h<24)return `${h} 小时前`
  const d=Math.round(h/24);if(d<7)return `${d} 天前`
  const date=new Date(t);return `${date.getMonth()+1}-${String(date.getDate()).padStart(2,'0')}`
}
export function clock(iso:string|null|undefined){if(!iso)return '—';const t=Date.parse(iso);return Number.isNaN(t)?'缺失':new Date(t).toLocaleTimeString('zh-CN',{hour12:false})}
export function dateTime(iso:string|null|undefined){if(!iso)return '—';const t=Date.parse(iso);return Number.isNaN(t)?iso:new Date(t).toLocaleString('zh-CN',{hour12:false})}
export const duration=(ms:number|null|undefined)=>ms==null?'耗时缺失':ms<1000?`${Math.round(ms)} ms`:ms<60000?`${(ms/1000).toFixed(1)} s`:`${Math.floor(ms/60000)} min ${Math.round((ms%60000)/1000)} s`

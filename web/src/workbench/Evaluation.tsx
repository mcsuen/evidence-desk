import {useState} from 'react'
import {api,operation} from '../lib/api'
import {localFetch} from '../lib/localSession'
import {Button,Card,Field,InlineError} from '../ui'
import {useData,key} from './shared'
import app from '../app/app.module.css'
import s from '../features/research/research.module.css'

export default function Evaluation(){
 const {data,reload,...query}=useEvaluation(),{data:reports}=useData<any[]>('/reports'),[selected,setSelected]=useState<string[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const [blind,setBlind]=useState(''),[annotator,setAnnotator]=useState(''),[effort,setEffort]=useState('light'),[major,setMajor]=useState(false),[minutes,setMinutes]=useState('0'),[comments,setComments]=useState('')
 async function act(fn:()=>Promise<void>){setBusy(true);try{setError('');await fn();await reload()}catch(e){setError(String(e))}finally{setBusy(false)}}
 async function packet(){const refs=selected.map(k=>{const n=k.lastIndexOf('@');return {id:k.slice(0,n),revision:Number(k.slice(n+1))}});const response=await localFetch('/api/v1/evaluations/blind-pack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation_id:operation(),reports:refs})});if(!response.ok)throw new Error(await response.text());const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='pitr-blind-review.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000)}
 return <div className={app.page}><h1 className="display">研究效果评测</h1><p className="sub">由两名评阅者独立记录实际修改成本。工程检查与模型复核不计作真人盲评。</p>{error&&<InlineError>{error}</InlineError>}{query.error&&<InlineError>{String(query.error)}</InlineError>}
 <Card className={s.railBody}><h2>评阅进度</h2><p>{data?.paired_reports||0} 份报告已有两人记录 · 轻度编辑可用比例 {data?.light_edit_ratio==null?'尚未评估':Math.round(data.light_edit_ratio*100)+'%'}</p><p className="sub">目标 80%。当前不声明已完成人类验证；请结合样本范围与评阅分歧判断。</p></Card>
 <Card className={s.railBody}><h2>生成盲评材料</h2><p className="sub">文件使用随机编号，不带宿主或模型信息。评阅者分别填写包内记录表。</p>{reports?.map(r=><label key={key(r)} style={{display:'block'}}><input type="checkbox" checked={selected.includes(key(r))} onChange={e=>setSelected(old=>e.target.checked?[...old,key(r)]:old.filter(k=>k!==key(r)))}/>{r.title} · 修订 {r.revision}</label>)}<Button disabled={busy||!selected.length} onClick={()=>act(packet)}>下载盲评包</Button></Card>
 <Card className={s.followup}><h2>登记真人评阅结果</h2><Field label="盲评编号"><input value={blind} onChange={e=>setBlind(e.target.value)}/></Field><Field label="评阅者"><input value={annotator} onChange={e=>setAnnotator(e.target.value)}/></Field><Field label="修改程度"><select value={effort} onChange={e=>setEffort(e.target.value)}><option value="none">可直接使用</option><option value="light">轻度编辑</option><option value="heavy">大幅修改</option><option value="unusable">不可用</option></select></Field><Field label="实际核对与编辑分钟数"><input type="number" min="0" value={minutes} onChange={e=>setMinutes(e.target.value)}/></Field><label><input type="checkbox" checked={major} onChange={e=>setMajor(e.target.checked)}/>发现重大研究错误</label><Field label="分歧与评阅意见"><textarea value={comments} onChange={e=>setComments(e.target.value)}/></Field><Button disabled={busy||!blind||!annotator} onClick={()=>act(async()=>{await api('/evaluations',{operation_id:operation(),blind_id:blind,annotator,edit_effort:effort,major_error:major,editing_minutes:Number(minutes),comments})})}>保存评阅记录</Button></Card>
 </div>
}
function useEvaluation(){const query=useData('/evaluations');return {...query,reload:query.refetch}}

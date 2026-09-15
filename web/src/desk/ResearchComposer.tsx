import {useRef,useState} from 'react'
import {useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {api,operation} from './api'

export type ComposerProps={company?:string;notify:(s:string)=>void;snapshot?:string;period?:string;metric?:string;modelDraftId?:string;question?:string;wikiRef?:string;intent?:'earnings'|'report_review'|'investigation'|'auto'}
type Attachment={file:File;sourceId?:string;status:'ready'|'uploading'|'uploaded'|'error';error?:string}
export function useAttachments(notify:(s:string)=>void){
 const[files,setFiles]=useState<Attachment[]>([])
 const latest=useRef(files);latest.current=files
 function add(input:FileList|null){const incoming=Array.from(input||[]);if(files.length+incoming.length>10||incoming.some(f=>f.size>40_000_000)){notify('最多十个附件，每个不超过 40 MB');return}setFiles([...files,...incoming.filter(f=>!files.some(a=>a.file.name===f.name&&a.file.size===f.size)).map(file=>({file,status:'ready' as const}))])}
 async function upload(){const result:string[]=[]
  for(const item of latest.current){if(item.sourceId){result.push(item.sourceId);continue}
   setFiles(fs=>fs.map(a=>a===item?{...a,status:'uploading',error:undefined}:a))
   try{const form=new FormData();form.set('file',item.file);form.set('company','UNASSIGNED');const response=await fetch('/api/desk/research/attachments',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw Error(data.detail||'附件上传失败');item.sourceId=data.source_id;result.push(data.source_id);setFiles(fs=>fs.map(a=>a.file===item.file?{...a,sourceId:data.source_id,status:'uploaded'}:a))}
   catch(e){setFiles(fs=>fs.map(a=>a.file===item.file?{...a,status:'error',error:String(e)}:a));throw e}
  }return result
 }
 return {files,add,upload,clear:()=>setFiles([]),remove:(i:number)=>setFiles(fs=>fs.filter((_,n)=>n!==i))}
}
export function Attachments({attachments,disabled=false}:{attachments:ReturnType<typeof useAttachments>;disabled?:boolean}){
 return <><label className="rx-attach"><span aria-hidden="true">＋</span> 添加材料<input aria-label="研究附件" type="file" accept=".pdf,.html,.htm,.txt,.md" multiple disabled={disabled} onChange={e=>{attachments.add(e.target.files);e.target.value=''}}/></label>{attachments.files.length>0&&<ul className="rx-attachments">{attachments.files.map((a,i)=><li key={a.file.name+':'+a.file.size}><span><b>{a.file.name}</b><small>{a.status==='uploading'?'正在上传…':a.status==='uploaded'?'已保存':a.status==='error'?a.error:'待上传 · '+(a.file.size/1024).toFixed(0)+' KB'}</small></span><button type="button" disabled={disabled} aria-label={'移除 '+a.file.name} onClick={()=>attachments.remove(i)}>×</button></li>)}</ul>}</>
}
export default function ResearchComposer(props:ComposerProps){
 const navigate=useNavigate(),client=useQueryClient(),op=useRef(operation()),inflight=useRef(false),sent=useRef('')
 const[question,setQuestion]=useState(props.question||''),[company,setCompany]=useState(props.company||''),[period,setPeriod]=useState(props.period||''),[asOf,setAsOf]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[bound,setBound]=useState(true)
 const attachments=useAttachments(props.notify)
 function changed(){op.current=operation();setError('')}
 async function submit(){if(inflight.current||(!question.trim()&&!attachments.files.length))return;const fingerprint=JSON.stringify([question,company,period,asOf,bound,attachments.files.map(a=>[a.file.name,a.file.size,a.file.lastModified])]);if(fingerprint!==sent.current){op.current=operation();sent.current=fingerprint}inflight.current=true;setBusy(true);setError('')
  try{const source_ids=await attachments.upload();const r=await api('/research/requests',{operation_id:op.current,workflow_version:3,question,company:bound?company:'',period:bound?period:'',intent:props.intent||'auto',snapshot:bound?(props.snapshot||''):'',as_of:asOf?new Date(asOf).toISOString():null,model_draft_id:bound?(props.modelDraftId||''):'',context_source:bound&&props.snapshot?'workspace':bound&&company?'explicit':'none',context:bound?{metric:props.metric||'',wiki_refs:props.wikiRef?[props.wikiRef]:[]}: {},source_ids});client.invalidateQueries({queryKey:['research-requests']});client.invalidateQueries({queryKey:['home']});navigate('/research/'+r.id)}catch(e){setError(String(e))}finally{inflight.current=false;setBusy(false)}}
 return <form className="rx-composer" onSubmit={e=>{e.preventDefault();void submit()}}>
  <label className="rx-question-label" htmlFor="research-question">你想弄清楚什么？</label>
  <textarea id="research-question" aria-label="研究问题" value={question} disabled={busy} onChange={e=>{setQuestion(e.target.value);changed()}} onKeyDown={e=>{if(!e.nativeEvent.isComposing&&(e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();void submit()}}} rows={4} placeholder="例如：比较拼多多和阿里的利润持续性，哪些增长有真实现金流支撑？"/>
  {bound&&(props.snapshot||props.wikiRef||props.metric||props.company)&&<div className="rx-context"><span>已带入 {company}{period?' · '+period:''}{props.snapshot?' · 固定财务快照':''}{props.wikiRef?' · Wiki 依据':''}{props.metric?' · '+props.metric:''}</span><button type="button" disabled={busy} onClick={()=>{setBound(false);setCompany('');setPeriod('');changed()}}>移除上下文 ×</button></div>}
  <div className="rx-composer-tools"><Attachments attachments={attachments} disabled={busy}/><details className="rx-scope"><summary>研究范围 <span>可选</span></summary><div><label>公司或上市代码<input aria-label="可选研究公司" disabled={busy} value={company} placeholder="从问题中识别" onChange={e=>{setCompany(e.target.value);setBound(true);changed()}}/></label><label>财报期间<input aria-label="研究期间" disabled={busy} value={period} placeholder="自动识别" onChange={e=>{setPeriod(e.target.value);setBound(true);changed()}}/></label><label>信息截止<input aria-label="信息截止时间" type="datetime-local" disabled={busy||!!(bound&&props.snapshot)} value={asOf} onChange={e=>{setAsOf(e.target.value);changed()}}/></label></div></details><button className="primary rx-start" type="submit" disabled={busy||(!question.trim()&&!attachments.files.length)}>{busy?'正在保存…':attachments.files.some(a=>a.status==='error')?'重试并开始研究':'开始研究'} <span aria-hidden="true">↗</span></button></div>
  {error&&<p className="rx-error" role="alert">{error}。输入和已上传材料已保留。</p>}
  <p className="rx-composer-hint">可以直接描述公司、行业或比较问题，也可以附上研报。系统只在关键歧义时向你确认。</p>
 </form>
}

import {lazy,Suspense,useEffect,useState} from 'react'
import {Link,useParams,useSearchParams} from 'react-router-dom'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {api,operation,upload} from '../../lib/api'
import {Select,Textarea,Badge,Button,Card,Dot,EmptyState,Field,InlineError,Loading,Seg,useToast} from '../../ui'
import type {ResearchCase} from '../../types/research_case'
import type {Run} from '../../types/run'
import type {ReportView,ReportDocument} from '../../types/report_view'
import type {SourceVersion} from '../../types/source_version'
import {Status,key,useData,Pending,labels} from '../../workbench/shared'
import {Report} from './Report'
import s from './research.module.css'
import app from '../../app/app.module.css'
const Editor=lazy(()=>import('./ReportEditor'))
const ReportDiff=lazy(()=>import('./ReportDiff'))
const Trace=lazy(()=>import('./trace/TracePanel').then(m=>({default:m.TracePanel})))
function VerifyStrip({report}:{report:ReportView}){
 const {data:groups}=useData<any[]>('/review',5000),targets=[...report.document.assertions,...report.document.models].map(key)
 const adopted=new Set((groups||[]).filter(g=>g.status==='adopt').flatMap(g=>g.targets.map(key))),count=targets.filter(k=>adopted.has(k)).length
 return <div className={s.verify} data-testid="research-verify">{[['deterministic','内容与引用'],['independent','独立复核']].map(([name,title])=>{const check=report.checks.find(c=>c.name===name),state=check?.status||'not_run';return <div key={name}><Dot tone={state==='passed'?'ok':['failed','error'].includes(state)?'danger':state==='not_applicable'?'pending':'warn'}/><span><b>{title}</b><br/><span className="muted">{labels[state]||state}</span></span></div>})}<div><Dot tone={targets.length&&count===targets.length?'ok':count?'accent':'pending'}/><span><b>人工采纳</b><br/><Link to="/review">{!targets.length?'没有待采纳判断':!groups?'读取决定记录…':`${count} / ${targets.length} 项已采纳`}</Link></span></div><div><Dot tone={report.delivery==='ready'?'ok':'warn'}/><span><b>报告交付</b><br/><span className="muted">{report.delivery==='ready'?'已具备交付条件':report.delivery==='partial'?'包含明确缺项':'待完成核验'}</span></span></div></div>
}
export function ResearchRecordPage(){
 const {rid}=useParams(),[params,setParams]=useSearchParams(),client=useQueryClient(),{notify}=useToast()
 const {data:record,error}=useData<ResearchCase>('/cases/'+rid,3000),{data:runs}=useData<Run[]>('/runs?case_id='+rid,2000)
 const patch=(name:string,value:string)=>setParams(p=>{const n=new URLSearchParams(p);if(value)n.set(name,value);else n.delete(name);return n})
 const tab=params.get('tab')||'overview',runId=params.get('run')||'',revision=params.has('version')?Number(params.get('version')):null
 const setRevision=(value:number|null)=>patch('version',value?String(value):'')
 const [edit,setEdit]=useState(false),[showInput,setShowInput]=useState(false),[showDiff,setShowDiff]=useState(false),[paper,setPaper]=useState('Letter'),[busy,setBusy]=useState(false)
 const run=runs?.find(r=>r.id===runId)||runs?.[0]
 const {data:history}=useQuery({queryKey:['report-history',run?.report?.id],queryFn:()=>api<ReportDocument[]>('/reports/'+run!.report!.id+'/revisions'),enabled:!!run?.report,refetchInterval:2000})
 const version=revision||history?.[0]?.revision||run?.report?.revision
 const {data:view,error:viewError}=useQuery({queryKey:['report-view',run?.report?.id,version],queryFn:()=>api<ReportView>(`/reports/${run!.report!.id}/revisions/${version}`),enabled:!!run?.report&&!!version,refetchInterval:2000})
 useEffect(()=>{if(showInput){document.getElementById('research-followup')?.scrollIntoView({block:'center'});document.querySelector<HTMLTextAreaElement>('#research-followup textarea')?.focus({preventScroll:true})}},[showInput])
 async function action(fn:()=>Promise<unknown>){setBusy(true);try{await fn();await client.invalidateQueries()}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
 if(!record)return <Pending error={error}/>
 const start=()=>action(()=>api('/cases/'+record.id+'/runs',{operation_id:operation(),expected_revision:record.input.revision}))
 const previous=history?.find(d=>d.revision===(version||1)-1)
 return <div className={app.page} data-testid="research-record"><header className={s.head}><Link to="/research" className="sub">← 研究记录</Link><h1 className={'display '+s.title}>{record.title}</h1><div className={s.meta}><Badge>输入修订 {record.input.revision}</Badge>{run&&<Status value={run.status}/>}<Button size="sm" onClick={()=>setShowInput(v=>!v)}>补充材料与问题</Button>{!run||!['queued','running'].includes(run.status)?<Button size="sm" disabled={busy} onClick={start}>从当前输入研究</Button>:<Button size="sm" disabled={busy} onClick={()=>action(()=>api('/runs/'+run.id+'/cancel',{operation_id:operation()}))}>取消研究</Button>}</div></header>
 {runs&&runs.length>1&&<label>执行记录 <Select value={run?.id} onChange={e=>setParams(p=>{const n=new URLSearchParams(p);n.set('run',e.target.value);n.delete('version');return n})}>{runs.map(r=><option key={r.id} value={r.id}>{new Date(r.created_at).toLocaleString()} · {r.status}</option>)}</Select></label>}
 {run&&<Card className={s.progress}><div className={s.meta}><Status value={run.status}/>{run.status==='running'&&<Status value={run.stage}/>}<span>{Math.round(run.active_seconds)} / {run.budget.active_seconds} 秒 · 工具 {run.tool_calls} / {run.budget.tool_calls} · 费用 {run.cost===null?'未知':run.cost}</span><Button size="sm" onClick={()=>patch('tab',tab==='flow'?'overview':'flow')}>执行详情</Button></div>{run.error&&<p className="sub">{run.error}</p>}{run.questions.map((q,i)=><p key={i}>{q}</p>)}{(['budget_exhausted','failed','cancelled'].includes(run.status)||(run.status==='completed'&&view&&view.delivery!=='ready'))&&run.input_revision===record.input.revision&&<Button disabled={busy} onClick={()=>action(()=>api('/runs/'+run.id+'/continue',{operation_id:operation(),expected_generation:run.generation}))}>从检查点继续研究</Button>}{run.status==='waiting_user'&&<p>请通过“补充材料与问题”回答，再从新输入继续。</p>}</Card>}
 {view&&<VerifyStrip report={view}/>}
 <div className={s.tabsRow}><Seg label="研究视图" value={tab} onChange={v=>patch('tab',v)} options={[{value:'overview',label:'研究'},{value:'flow',label:'执行流程'},{value:'trace',label:'Trace'}]}/></div>
 {tab!=='overview'&&run&&<Suspense fallback={<Loading/>}><Trace key={run.id+tab} rid={run.id} initialView={tab==='trace'?'waterfall':'graph'}/></Suspense>}
 {tab==='overview'&&<>
 {viewError&&<InlineError>{String(viewError)}</InlineError>}
 {view&&<><header className={s.reportHeader}><h2 className="display">{view.document.title}</h2><div className={s.reportToolbar}><Status value={view.delivery}/><label>报告版本 <Select aria-label="报告版本" value={version} onChange={e=>{setRevision(Number(e.target.value));setEdit(false)}}>{history?.map(d=><option key={d.revision} value={d.revision}>修订 {d.revision}{d.revision===history[0].revision?' · 最新':''}</option>)}</Select></label><Button size="sm" onClick={()=>setEdit(v=>!v)}>修订报告</Button>{previous&&<Button size="sm" onClick={()=>setShowDiff(v=>!v)}>比较上一版本</Button>}</div>{view.document.change_reason&&<details className={s.revisionNote}><summary>本版修改说明</summary><p>{view.document.change_reason}</p></details>}</header>
 {view.current_validity.status!=='available'&&<InlineError>当前有效性提示：{String(view.current_validity.reason)}。下方正文和历史检查保留当时结果。</InlineError>}
 {view.checks.some(c=>c.findings.length||c.limitations.length)&&<details><summary>检查发现与范围</summary>{view.checks.map(c=><section key={c.id}><h3>{c.name==='independent'?'独立复核':'内容检查'}</h3>{c.limitations.map((l,i)=><p key={i}>{l}</p>)}{c.findings.map((f,i)=><p key={i}>{String(f.message||JSON.stringify(f))}{f.correction?` · ${f.correction}`:''}</p>)}</section>)}</details>}
 {showDiff&&previous&&<Suspense fallback={<Loading/>}><ReportDiff before={previous} after={view}/></Suspense>}
 {edit?<Suspense fallback={<Loading/>}><Editor key={key(view.document)} report={view} onClose={()=>setEdit(false)} onSaved={()=>{setEdit(false);setRevision(null);client.invalidateQueries()}}/></Suspense>:<Report key={key(view.document)} report={view}/>}
 <Card className={s.followup}><h2>Word 交付</h2><div className={s.chips}><Select aria-label="Word 纸张" value={paper} onChange={e=>setPaper(e.target.value)}><option>Letter</option><option>A4</option></Select><Button disabled={busy} onClick={()=>action(()=>api('/exports',{operation_id:operation(),report:{id:view.document.id,revision:view.document.revision},paper}))}>导出 Word</Button></div>{view.exports.map(job=><div key={job.id}><Status value={job.status}/> <span>{job.paper} · 尝试 {job.attempts} 次</span>{job.artifact&&<><a href={'/api/v1/artifacts/'+job.artifact.id+'/download'}> 下载 Word</a> · <a href={'/api/v1/artifacts/'+job.artifact.id+'/render/pdf'} target="_blank" rel="noreferrer">查看逐页渲染</a></>}{job.error&&<p className="sub">{job.error}</p>}{job.status==='failed'&&<Button size="sm" disabled={busy} onClick={()=>action(()=>api('/exports/'+job.id+'/retry',{operation_id:operation()}))}>仅重试导出</Button>}</div>)}</Card></>}
 {!view&&!run&&<p className="sub">研究问题已保存，可随时开始。</p>}
 {!view&&run&&!viewError&&(run.report?<Loading>正在读取已保存报告…</Loading>:<EmptyState>{['queued','running'].includes(run.status)?'研究正在进行，报告会在这里形成。可以打开执行流程查看进展。':'本次尚未交付报告。已保存的输入和执行记录可查看，也可以补充后继续研究。'}</EmptyState>)}
 </>}
 <div className={s.continueBar}><span>补充资料、纠正对象或调整研究重点</span><span style={{flex:1}}/><Button size="sm" onClick={()=>setShowInput(v=>!v)}>补充 / 调整 ↓</Button></div>
 <div id="research-followup">{showInput&&<InputEditor record={record} onSaved={()=>{setShowInput(false);client.invalidateQueries()}}/>}</div>
 </div>
}
function InputEditor({record,onSaved}:{record:ResearchCase;onSaved:()=>void}){
 const [question,setQuestion]=useState(record.input.question),[selected,setSelected]=useState(record.input.sources),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const {data:sources,refetch}=useData<SourceVersion[]>('/sources?subject='+encodeURIComponent(record.input.scope.subjects.length===1?record.input.scope.subjects[0]:'')+(record.input.scope.mode==='historical'?'&mode=historical&as_of='+encodeURIComponent(record.input.scope.as_of||''):''))
 async function add(file:File){setBusy(true);try{const source=await upload('/sources/upload',file,record.input.scope.subjects[0]||'');setSelected(p=>[...p.filter(r=>r.id!==source.id),{id:source.id,revision:source.revision}]);await refetch()}catch(e){setError(String(e))}finally{setBusy(false)}}
 async function save(){setBusy(true);try{await api('/cases/'+record.id+'/inputs',{operation_id:operation(),expected_revision:record.input.revision,question,scope:record.input.scope,sources:selected,knowledge:record.input.knowledge,depth:record.input.depth,report_type:record.input.report_type,agent_provider:record.input.agent_provider,model:record.input.model,reasoning:record.input.reasoning});onSaved()}catch(e){setError(String(e))}finally{setBusy(false)}}
 return <Card className={s.followup}><Field label="补充后的研究问题"><Textarea rows={5} value={question} onChange={e=>setQuestion(e.target.value)}/></Field><label className={s.attach}>添加新原件<input type="file" disabled={busy} onChange={e=>{if(e.target.files?.[0])add(e.target.files[0])}}/></label><p>本次材料版本</p>{selected.filter(r=>sources&&!sources.some(src=>key(src)===key(r))).map(r=><p key={key(r)}>原选版本 {key(r)} 已不在当前可选范围。<Button size="sm" onClick={()=>setSelected(p=>p.filter(v=>key(v)!==key(r)))}>移除此旧版本</Button></p>)}{sources?.map(src=><label key={key(src)}><input type="checkbox" checked={selected.some(r=>key(r)===key(src))} onChange={e=>setSelected(p=>e.target.checked?[...p.filter(r=>r.id!==src.id),{id:src.id,revision:src.revision}]:p.filter(r=>key(r)!==key(src)))}/>{src.title} · 修订 {src.revision}</label>)}{error&&<InlineError>{error}</InlineError>}<Button disabled={busy||!question.trim()} onClick={save}>保存新输入修订</Button></Card>
}

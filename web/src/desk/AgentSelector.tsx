import {useState} from 'react'
import {NavLink} from 'react-router-dom'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {api,saveAgentSelection} from './api'

type Agent={id:string,name:string,status:string,version:string|null,install_url:string,login_command:string}
type Status={agents:Agent[],checking:boolean,selection:{agent_provider?:string,agent_models?:Record<string,string|null>}}
const labels:Record<string,string>={missing:'尚未安装',logged_in:'已登录',signed_out:'需要登录',incompatible:'请更新 CLI',check_failed:'检测失败'}
function useAgents(){return useQuery({queryKey:['agents'],queryFn:()=>api<Status>('/agents'),refetchInterval:query=>query.state.data?.checking?1500:30000,retry:false})}

export default function AgentSelector(){
 const {data,error}=useAgents(),client=useQueryClient()
 const [busy,setBusy]=useState(false),[message,setMessage]=useState('')
 const provider=data?.selection.agent_provider||'',model=data?.selection.agent_models?.[provider]||''
 const models=useQuery({queryKey:['agent-models',provider],queryFn:()=>api(`/agents/${provider}/models`),enabled:!!provider,retry:false,staleTime:60000})
 const options=models.data?.models||[{id:'',name:'沿用本机默认模型'}]
 const [custom,setCustom]=useState('')
 async function save(value:unknown){setBusy(true);setMessage('');try{await saveAgentSelection(value);await client.invalidateQueries({queryKey:['agents']});client.invalidateQueries({queryKey:['settings']})}catch(e){setMessage(String(e))}finally{setBusy(false)}}
 if(error)return <NavLink to="/settings">本机 Agent 状态暂不可用</NavLink>
 return <div className="d-agent-selector" title="此选择用于新任务；已有任务保留原 Agent 和模型">
  <small className="d-muted">新任务</small>
  <label>Agent<select aria-label="Agent" disabled={busy||data?.checking} value={provider} onChange={e=>save({agent_provider:e.target.value})}><option value="" disabled>{data?.checking?'检测中…':'选择本机 Agent'}</option>{data?.agents.map(agent=><option key={agent.id} value={agent.id} disabled={agent.status!=='logged_in'}>{agent.name}{agent.status==='logged_in'?'':` · ${labels[agent.status]}`}</option>)}</select></label>
  {provider&&<label>模型<select aria-label="模型" value={model} disabled={busy} onChange={e=>save({agent_models:{[provider]:e.target.value||null}})}>{options.map((option:{id:string,name:string})=><option key={option.id} value={option.id}>{option.name}</option>)}{model&&!options.some((option:{id:string})=>option.id===model)&&<option value={model}>{model}</option>}</select></label>}
  {provider==='claude'&&<details><summary>自定义模型</summary><form onSubmit={e=>{e.preventDefault();if(custom.trim())save({agent_models:{claude:custom.trim()}})}}><input aria-label="自定义 Claude 模型 ID" value={custom} onChange={e=>setCustom(e.target.value)} placeholder="模型 ID"/><button disabled={busy||!custom.trim()}>使用</button><small>候选模型的账号权限尚未验证。</small></form></details>}
  {(message||models.error)&&<span role="alert" className="d-warning">{message||String(models.error)}</span>}
  {!data?.checking&&!data?.agents.some(agent=>agent.status==='logged_in')&&<NavLink to="/settings">安装与登录指引</NavLink>}
 </div>
}

export function AgentSettings(){
 const {data,error}=useAgents(),client=useQueryClient(),[message,setMessage]=useState('')
 return <section className="d-agent-settings"><h2>本机 Agent</h2><p>安装并登录官方 CLI 后即可开始研究与使用 Wiki，无需填写模型 API Key。选择应用于新任务。</p>
  <button disabled={data?.checking} onClick={async()=>{try{await api('/agents/refresh',{});client.invalidateQueries({queryKey:['agents']});client.invalidateQueries({queryKey:['agent-models']})}catch(e){setMessage(String(e))}}}>{data?.checking?'正在检测…':'刷新检测'}</button>
  {(error||message)&&<p role="alert">{message||String(error)}</p>}
  {data?.agents.map(agent=><article key={agent.id}><h3>{agent.name} · {labels[agent.status]}</h3><p>{agent.version||'未发现本机安装'}</p>{agent.status!=='logged_in'&&<p><a href={agent.install_url} target="_blank" rel="noreferrer">安装／更新官方 CLI ↗</a> · 登录：<code>{agent.login_command}</code></p>}</article>)}
  <p>个人 skills、MCP、hooks 和指令不参与研究；登录与必要连接设置由官方 CLI 读取。</p>
 </section>
}

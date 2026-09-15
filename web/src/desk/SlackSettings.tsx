import {useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {api} from './api'

type Delivery={id:string;kind:string;channel_id:string;status:string;attempts:number;error:string|null;created:number}
type Attachment={id:string;name:string;file_id:string;status:string;size:number;error:string|null}
type Check={status:string;evidence:string;recorded_at:string}
type SlackStatus={state:string;connected:boolean;enabled:boolean;error:string|null;inbox:Record<string,number>;outbox:Record<string,number>;last_received_at:number|null;last_sent_at:number|null;connection_count:number;live_checks:Record<string,Check>}
const labels:Record<string,string>={not_configured:'尚未配置',connecting:'正在连接',connected:'已连接',disconnected:'已断开',reconnecting:'正在重连',failed:'失败',stopping:'正在停止',pending:'待发送',sending:'发送中',sent:'已发送',delivery_unknown:'发送结果待核对'}
const checks=[['dm','本人私信'],['mention','频道 @提及'],['command','/research 命令'],['attachment','文件接收'],['research_result','研究结果文件'],['approval','交互审批'],['reconnect','断线恢复']]
const fields=[['slack_app_token','App Token','xapp-…'],['slack_bot_token','Bot Token','xoxb-…'],['slack_team_id','工作区 ID','T…'],['slack_user_id','本人用户 ID','U…']]
const stamp=(value:number|null|undefined)=>value?new Date(value*1000).toLocaleString():'尚无记录'

export default function SlackSettings({notify}:{notify:(message:string)=>void}){
 const[values,setValues]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false),[diagnostic,setDiagnostic]=useState<string>(''),[check,setCheck]=useState('dm'),[evidence,setEvidence]=useState(''),[retry,setRetry]=useState<Delivery|null>(null),[testChannel,setTestChannel]=useState('')
 const{data:settings={},refetch:refreshSettings}=useQuery({queryKey:['settings'],queryFn:()=>api<Record<string,any>>('/settings')})
 const{data:slack,refetch:refreshSlack}=useQuery({queryKey:['slack'],queryFn:()=>api<SlackStatus>('/slack'),refetchInterval:3000})
 const{data:deliveries=[],refetch:refreshDeliveries}=useQuery({queryKey:['slack-deliveries'],queryFn:()=>api<Delivery[]>('/slack/deliveries'),refetchInterval:5000})
 const{data:attachments=[]}=useQuery({queryKey:['slack-attachments'],queryFn:()=>api<Attachment[]>('/slack/attachments'),refetchInterval:5000})
 const channels:string[]=settings.slack_channel_ids||[]
 async function run(work:()=>Promise<unknown>,message:string){setBusy(true);try{await work();await Promise.all([refreshSettings(),refreshSlack(),refreshDeliveries()]);notify(message)}catch(error){notify(String(error))}finally{setBusy(false)}}
 function save(){return run(async()=>{
  const body:Record<string,unknown>={...values}
  if(values.slack_channel_ids!==undefined)body.slack_channel_ids=values.slack_channel_ids.split(/[\s,，]+/).filter(Boolean)
  await api('/settings',body);setValues({});setDiagnostic('')
 },'Slack 配置已保存；变更连接配置后请重新连接')}
 async function checkConnection(){const result=await api('/slack/check',{});setDiagnostic(result.ok?'Bot 工作区验证通过。请继续连接并检查本人私信与测试频道。':result.missing?.length?'请先填写：'+result.missing.map((key:string)=>fields.find(f=>f[0]===key)?.[1]||key).join('、'):result.missing_scopes?.length?'应用缺少权限：'+result.missing_scopes.join('、')+'。更新应用并重新安装。':'检查未通过：'+(result.error||'请核对配置'))}
 const complete=checks.filter(([key])=>slack?.live_checks?.[key]?.status==='passed').length
 return <section className="d-slack-settings" aria-labelledby="slack-title">
  <div className="d-page-title"><h2 id="slack-title">Slack 接入</h2><span className="d-status-tag">{labels[slack?.state||'not_configured']||slack?.state}</span></div>
  <p>在 Slack 私信、指定频道 @提及或使用 /research，接收进度、报告和审核操作。只有本人账号可以触发本机任务。</p>
  <ol className="d-slack-setup">
   <li><a href="https://slack.com/get-started#/createnew" target="_blank" rel="noreferrer">创建个人 Slack 工作区 ↗</a><span>推荐使用专用测试频道，工作区和应用均可命名为 PITR Research。</span></li>
   <li><a href="https://api.slack.com/apps" target="_blank" rel="noreferrer">创建 Slack 应用 ↗</a><span>选择 From a manifest，导入下方文件并安装到自己的工作区。</span><a href="/api/desk/slack-manifest" download>下载应用配置文件 ↓</a></li>
   <li><strong>生成并填写凭据</strong><span>在 Basic Information → App-Level Tokens 创建带 connections:write 权限的 App Token；在 OAuth &amp; Permissions 获取 Bot Token。Token 只填写在本页。</span></li>
   <li><strong>邀请机器人并登记频道</strong><span>把机器人加入测试频道，在频道详情复制频道 ID；本人 ID 可从个人资料的“更多”菜单复制。频道白名单留空时仅允许私信。</span></li>
  </ol>
  <div className="d-settings-form">
   {fields.map(([key,label,hint])=><label key={key}>{label}<input autoComplete="off" type={key.includes('token')?'password':'text'} value={values[key]??''} placeholder={settings[key]?(key.includes('token')?'已保存；留空保留':settings[key]):hint} onChange={e=>setValues(v=>({...v,[key]:e.target.value}))}/></label>)}
   <label>允许操作的频道 ID<textarea rows={2} aria-label="允许操作的频道 ID" value={values.slack_channel_ids??channels.join('\n')} placeholder="C…，多个频道用换行或逗号分隔" onChange={e=>setValues(v=>({...v,slack_channel_ids:e.target.value}))}/></label>
   <div className="d-toolbar"><button disabled={busy||!Object.keys(values).length} className="primary" onClick={save}>保存 Slack 配置</button><button disabled={busy} onClick={()=>run(checkConnection,'配置检查已完成')}>检查配置</button><button disabled={busy} onClick={()=>run(()=>api(slack?.connected||slack?.state==='reconnecting'?'/slack/disconnect':'/slack/connect',{}),'Slack 连接状态已更新')}>{slack?.connected||slack?.state==='reconnecting'?'断开 Slack':'连接 Slack'}</button></div>
   {diagnostic&&<p className="d-inline-notice" role="status">{diagnostic}</p>}
   {slack?.error&&<p className="d-warning">{slack.error==='InstallationBusy'?'旧的本机连接还在退出，正在自动重试。':`连接或投递提示：${slack.error}。检查凭据、应用权限和网络后重试。`}</p>}
   <p className="d-muted">{slack?.enabled?'已启用：本机服务重启后会恢复连接。':'尚未启用自动恢复；连接成功后保持启用，主动断开会关闭。'} 本机服务运行期间可接收请求。</p>
  </div>
  <div className="d-slack-health"><span>最近接收<strong>{stamp(slack?.last_received_at)}</strong></span><span>最近发送<strong>{stamp(slack?.last_sent_at)}</strong></span><span>连接次数<strong>{slack?.connection_count||0}</strong></span></div>
  <div className="d-toolbar"><label>测试发送到<select aria-label="测试发送到" value={testChannel} onChange={e=>setTestChannel(e.target.value)}><option value="">本人私信</option>{channels.map(id=><option key={id} value={id}>{id}</option>)}</select></label><button disabled={busy||!slack?.connected} onClick={()=>run(()=>api('/slack/test',{channel_id:testChannel||undefined}),'测试消息已入队，请到 Slack 查看')}>发送测试消息</button></div>
  <h3>投递记录</h3><p className="d-muted">消息和文件分别记录。发送结果待核对时，请先查看 Slack，确认需要再次发送后再操作。</p>
  {!deliveries.length?<p className="d-empty">尚无投递记录</p>:<div className="d-slack-table"><table><thead><tr><th>时间 / 目标</th><th>内容</th><th>状态</th><th>发送次数</th><th>操作</th></tr></thead><tbody>{deliveries.slice(0,30).map(d=><tr key={d.id}><td>{stamp(d.created)}<br/>{d.channel_id}</td><td>{d.kind==='file'?'文件':'消息'}</td><td>{labels[d.status]||d.status}{d.error&&<small className="d-muted"> · {d.error}</small>}</td><td>{d.attempts}</td><td>{['failed','delivery_unknown'].includes(d.status)&&<button disabled={busy} onClick={()=>setRetry(d)}>重发</button>}</td></tr>)}</tbody></table></div>}
  {retry&&<div className="d-inline-notice" role="alert"><p>重发{retry.kind==='file'?'文件':'消息'}到 {retry.channel_id}。如果先前已送达，Slack 中会出现重复内容。</p><div className="d-toolbar"><button disabled={busy} onClick={()=>run(async()=>{await api('/slack/deliveries/'+encodeURIComponent(retry.id)+'/retry',{});setRetry(null)},'已重新排队')}>已核对，重新发送</button><button onClick={()=>setRetry(null)}>取消</button></div></div>}
  <h3>收到的附件</h3><p className="d-muted">文件接收后保存在本机。当前研究命令暂不自动解析附件；可下载后从“资料与输入”导入。</p>
  {!attachments.length?<p className="d-empty">尚无接收附件</p>:<div className="d-slack-table"><table><thead><tr><th>文件</th><th>大小</th><th>接收结果</th></tr></thead><tbody>{attachments.map(a=><tr key={a.id}><td>{a.status==='ready'?<a href={'/api/desk/slack/attachments/'+a.id+'/file'}>{a.name||a.file_id} ↓</a>:a.name||a.file_id}</td><td>{(a.size/1024).toFixed(1)} KB</td><td>{a.status==='ready'?'已接收':a.error||'等待接收'}</td></tr>)}</tbody></table></div>}
  <h3>真实联调记录 · {complete} / {checks.length}</h3><p className="d-muted">只有在实际 Slack 工作区操作成功后登记；自动测试结果单独记录。</p>
  <ul className="d-slack-checks">{checks.map(([key,label])=><li key={key}><span>{slack?.live_checks?.[key]?.status==='passed'?'✓':'○'} {label}</span>{slack?.live_checks?.[key]&&<small>{slack.live_checks[key].evidence}</small>}</li>)}</ul>
  <div className="d-toolbar"><label>验收项目<select value={check} onChange={e=>setCheck(e.target.value)}>{checks.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><label className="d-slack-evidence">实际操作证据<input aria-label="实际操作证据" value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="例如 Slack 消息链接、任务 ID 和操作结果"/></label><button disabled={busy||!evidence.trim()||!slack?.last_received_at} onClick={()=>run(async()=>{await api('/slack/live-checks',{check,evidence});setEvidence('')},'实际联调记录已保存')}>登记已通过</button></div>
 </section>
}

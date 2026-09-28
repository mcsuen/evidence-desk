import {useState} from 'react'
import {Link} from 'react-router-dom'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {api,operation} from '../../lib/api'
import {keys} from '../../lib/queryKeys'
import {dateTime} from '../../lib/format'
import {useCompany} from '../../app/company'
import {Badge,Button,Card,Field,IconButton,InlineError,Input,Loading,Select,useToast} from '../../ui'
import type {NewsStatus} from '../../types/lab_news_status'
import type {NewsSettings,NewsSource} from '../../types/lab_news_settings'
import {LabHeader} from './NewsPage'
import app from '../../app/app.module.css'
import s from './news.module.css'

export function NewsSettingsPage(){
  const {data,error}=useQuery({queryKey:keys.news.status,queryFn:()=>api<NewsStatus>('/lab/news/status'),refetchInterval:5000})
  return <div className={app.page} data-testid="news-settings"><LabHeader settings validation={String(data?.evaluation.status||'unvalidated')}/>{error&&<InlineError>{String(error)}</InlineError>}{data?<SettingsForm status={data}/>:<Loading/>}</div>
}

function SettingsForm({status}:{status:NewsStatus}){
  const client=useQueryClient(),{notify}=useToast(),{companies}=useCompany()
  const [edits,setEdits]=useState<NewsSettings|null>(null),[busy,setBusy]=useState(false)
  const settings=edits||status.settings
  const {data:adapters}=useQuery({queryKey:['source-adapters'],queryFn:()=>api<{items:{name:string;markets:string[]}[]}>('/source-adapters')})
  const change=(value:Partial<NewsSettings>)=>setEdits({...settings,...value})
  const sourceChange=(id:string,value:Partial<NewsSource>)=>change({sources:settings.sources.map(x=>x.id===id?{...x,...value}:x)} as NewsSettings)
  async function save(){setBusy(true);try{await api('/lab/news/settings',{operation_id:operation(),settings},'PUT');setEdits(null);await client.invalidateQueries({queryKey:keys.news.status});notify('新闻实验设置已保存','ok')}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
  async function run(kind:string){setBusy(true);try{await api('/lab/news/runs',{operation_id:operation(),kind});await client.invalidateQueries({queryKey:keys.news.status});notify(kind==='install'?'本地模型安装已排队':'任务已排队','ok')}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
  const active=status.runs.some(r=>['queued','running'].includes(String(r.status)))
  function addSource(kind:'rss'|'disclosure'){
    const item:NewsSource={id:'source-'+crypto.randomUUID().slice(0,12),name:kind==='rss'?'新的新闻来源':'公司公告',kind,url:'',enabled:true,company:kind==='disclosure'?companies[0]?.company||'':'',adapter:kind==='disclosure'?adapters?.items.find(a=>a.markets.length)?.name||'':'',terms:[]}
    change({sources:[...settings.sources,item]} as NewsSettings)
  }
  return <div className={s.settingsGrid}>
    <Card className={s.settingsPanel}><h2>采集范围</h2><form className={s.settingsForm} onSubmit={e=>{e.preventDefault();void save()}}>
      <label className={s.material}><input type="checkbox" checked={settings.enabled} onChange={e=>change({enabled:e.target.checked})}/>系统运行时自动收集新闻</label>
      <div className={s.fields}><Field label="采集间隔（分钟）"><Input aria-label="采集间隔" type="number" min={5} max={1440} value={settings.cadence_minutes} onChange={e=>change({cadence_minutes:Number(e.target.value)})}/></Field><Field label="每天最多处理"><Input aria-label="每日处理上限" type="number" min={1} max={10000} value={settings.daily_limit} onChange={e=>change({daily_limit:Number(e.target.value)})}/></Field></div>
      <div><b style={{fontSize:12}}>覆盖公司</b><p className="muted" style={{fontSize:12}}>未单独勾选时，使用全部覆盖公司的研究框架。</p><div className={s.coverage}>{companies.map(c=><label key={c.company}><input type="checkbox" checked={settings.companies.includes(c.company)} onChange={e=>change({companies:e.target.checked?[...settings.companies,c.company]:settings.companies.filter(x=>x!==c.company)})}/>{c.company}</label>)}</div></div>
      <div>{settings.sources.map(source=><section className={s.source} key={source.id}><div className={s.sourceTop}><input type="checkbox" aria-label={'启用 '+source.name} checked={source.enabled} onChange={e=>sourceChange(source.id,{enabled:e.target.checked})}/><Input aria-label={'来源名称 '+source.id} value={source.name} onChange={e=>sourceChange(source.id,{name:e.target.value})}/><IconButton icon="x" label={'移除 '+source.name} plain onClick={()=>change({sources:settings.sources.filter(x=>x.id!==source.id)} as NewsSettings)}/></div>
        {source.kind==='rss'&&<Input type="url" aria-label={'订阅地址 '+source.name} placeholder="https://…/rss.xml" value={source.url} onChange={e=>sourceChange(source.id,{url:e.target.value})} required/>}
        {source.kind==='disclosure'&&<div className={s.fields}><Select aria-label="公告公司" value={source.company} onChange={e=>sourceChange(source.id,{company:e.target.value})}>{companies.map(c=><option key={c.company} value={c.company}>{c.company} · {c.name}</option>)}</Select><Select aria-label="公告渠道" value={source.adapter} onChange={e=>sourceChange(source.id,{adapter:e.target.value})}>{adapters?.items.filter(a=>a.markets.length).map(a=><option value={a.name} key={a.name}>{a.name}</option>)}</Select></div>}
        {source.kind==='gdelt'&&<Field label="公开主题关键词（逗号分隔）"><Input value={source.terms.join(', ')} onChange={e=>sourceChange(source.id,{terms:e.target.value.split(',').map(x=>x.trim()).filter(Boolean) as NewsSource['terms']})}/></Field>}
      </section>)}</div>
      <div className={s.actions}><Button size="sm" onClick={()=>addSource('rss')}>添加 RSS</Button><Button size="sm" onClick={()=>addSource('disclosure')}>添加公司公告</Button><Button type="submit" variant="primary" disabled={busy}>保存设置</Button></div>
      <p className="muted" style={{fontSize:12}}>休眠期间暂停采集，恢复后合并补采。来源本身保留范围之外的新闻可能无法补齐。</p>
    </form></Card>
    <div className={s.settingsForm}>
      <Card className={s.settingsPanel}><h2>本地模型</h2><div className={s.actions}><Badge tone={status.runtime.installed?'ok':'default'}>{status.runtime.installed?'已安装':'尚未安装'}</Badge><span className="muted" style={{fontSize:12}}>{status.runtime.device==='mps'?'Mac GPU':status.runtime.device==='cpu'?'CPU · GPU 不可用时回退':String(status.runtime.device||'首次评分时加载')}</span></div><p style={{fontSize:13,margin:'12px 0'}}>Laya 多语言判断＋本地语义检索。新闻筛选在本机完成，研究框架随评分保存版本。</p>
        {!!status.runtime.error&&<InlineError>{String(status.runtime.error)}</InlineError>}
        <div className={s.actions}><Button disabled={busy||active} onClick={()=>run('install')}>{status.runtime.installed?'检查并修复安装':'安装本地模型'}</Button><Button disabled={busy||active} onClick={()=>run('rescore')}>重新评分</Button></div>
        <small className="muted">首次安装需要联网下载权重；日常推理使用本地文件。</small>
      </Card>
      <Card className={s.settingsPanel}><h2>实验效果</h2><Badge tone="warn">{status.evaluation.status==='passed'?'已通过本批样本评估':'尚待验证'}</Badge><p style={{fontSize:13,marginTop:10}}>{String(status.evaluation.note||'请查看评估结果中的样本范围。')}</p><p className="muted" style={{fontSize:12}}>已收录 {status.counts.articles||0} 篇报道 · {status.counts.events||0} 个事件 · {status.counts.feedback||0} 次反馈</p><details className={s.technical}><summary>评估明细</summary><pre>{JSON.stringify(status.evaluation,null,2)}</pre></details></Card>
      {Array.isArray(status.runtime.context_coverage)&&status.runtime.context_coverage.length>0&&<Card className={s.settingsPanel}><h2>公司框架覆盖</h2><p className="muted" style={{fontSize:12}}>缺少已采纳研究条目的公司，其新闻会保留待确认。</p>{status.runtime.context_coverage.map(item=><div key={String(item.company)} className={s.log}><Link to={'/companies/'+encodeURIComponent(String(item.company))+'?tab=knowledge'}>{String(item.company)} · {String(item.name)}</Link><p>{Number(item.items)>0?String(item.items)+' 个可用研究条目':'尚需补充公司认识'}</p></div>)}</Card>}
      <Card className={s.settingsPanel}><h2>来源覆盖</h2>{status.sources.map(source=><div className={s.log} key={String(source.id)}><b>{String(source.name)}</b><span className="muted"> · {source.enabled?'已启用':'已暂停'}</span><p className="muted">{source.last_success?'最近成功 '+dateTime(String(source.last_success)):'尚未成功采集'}</p>{!!source.truncated&&<p className={s.reason}>本次来源结果或处理额度达到上限，覆盖可能不完整。</p>}{Array.isArray(source.errors)&&source.errors.slice(0,3).map((error,i)=><p className={s.reason} key={i}>{String(error)}</p>)}{Array.isArray(source.history)&&source.history.length>0&&<details className={s.technical}><summary>最近采集记录</summary>{source.history.map((log,i)=><div className={s.log} key={i}>{dateTime(String(log.at))} · 新增 {String(log.acquired||0)} 篇{Array.isArray(log.errors)&&log.errors.map((error:unknown,j:number)=><p className={s.reason} key={j}>{String(error)}</p>)}</div>)}</details>}</div>)}</Card>
      <Card className={s.settingsPanel}><h2>运行记录</h2>{status.runs.length?status.runs.map(run=><div className={s.log} key={String(run.id)}><b>{{collect:'新闻采集',rescore:'重新评分',install:'模型安装'}[String(run.kind)]||String(run.kind)}</b> · {{queued:'排队中',running:'运行中',completed:'已完成',partial:'完成，有缺口',failed:'失败，可重试'}[String(run.status)]||String(run.status)}<p className="muted">{dateTime(String(run.created_at))}</p>{!!run.error&&<p className={s.reason}>{String(run.error)}</p>}<details className={s.technical}><summary>处理数量</summary><pre>{JSON.stringify(run.progress,null,2)}</pre></details>{['failed','partial'].includes(String(run.status))&&<Button size="sm" disabled={busy} onClick={()=>runRetry(String(run.kind))}>重试</Button>}</div>):<p className="muted">尚无运行记录。</p>}</Card>
    </div>
  </div>
  function runRetry(kind:string){void run(kind)}
}

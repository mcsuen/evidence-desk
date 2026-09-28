import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react'
import {Link,NavLink,useNavigate} from 'react-router-dom'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {api,operation} from '../../lib/api'
import {keys} from '../../lib/queryKeys'
import {useUrlState} from '../../lib/useUrlState'
import {dateTime,relativeTime} from '../../lib/format'
import {Badge,Button,Card,Drawer,EmptyState,IconButton,InlineError,Input,Loading,Seg,useToast} from '../../ui'
import type {NewsEvents,NewsScore} from '../../types/lab_news_events'
import type {NewsDetail} from '../../types/lab_news_detail'
import type {NewsResearchDraft} from '../../types/lab_news_research_draft'
import type {NewsStatus} from '../../types/lab_news_status'
import app from '../../app/app.module.css'
import s from './news.module.css'

const dimensions=[['relevance','公司相关',30],['materiality','业务重要',30],['research_impact','研究影响',25],['novelty','信息增量',10],['freshness','时效',5]] as const
export function LabHeader({settings=false,validation='unvalidated',children}:{settings?:boolean;validation?:string;children?:ReactNode}){
  const {get}=useUrlState();const scope=get('company');const suffix=scope?'?company='+encodeURIComponent(scope):''
  return <><div className={app.pageHead}><div><span className="kicker">LAB / NEWS RADAR</span><h1 className="display">{settings?'来源与运行':'新闻雷达'}</h1><p className="sub">把值得核对的变化，接到已有的公司认识上。</p></div><span className={app.spacer}/>{children}</div>
    <nav className={s.tabs} aria-label="新闻实验导航"><NavLink to={'/lab/news'+suffix} end>新闻</NavLink><NavLink to={'/lab/news/settings'+suffix}>来源与运行</NavLink><Badge tone="warn">实验评分 · {validation==='passed'?'本批评估达标':validation==='below_target'?'未达目标':'尚待验证'}</Badge></nav></>
}

function ScoreParts({score}:{score:NewsScore}){return <div className={s.parts}>{dimensions.slice(0,3).map(([key,label])=><span key={key}>{label} <b>{score.dimensions[key]==null?'—':Math.round(score.dimensions[key]*100)}</b></span>)}</div>}

export function NewsPage(){
  const {get,patch}=useUrlState(),client=useQueryClient(),{notify}=useToast()
  const company=get('company'),queue=get('queue','selected'),date=get('date'),event=get('event'),scoreId=get('score'),view=get('view','score'),offset=Number(get('offset','0'))||0
  const order=get('order','high'),query=new URLSearchParams({company,queue,date,order,offset:String(offset)})
  const {data,error,isLoading}=useQuery({queryKey:keys.news.events(query.toString()),queryFn:()=>api<NewsEvents>('/lab/news/events?'+query),refetchInterval:event?false:30000})
  const {data:status}=useQuery({queryKey:keys.news.status,queryFn:()=>api<NewsStatus>('/lab/news/status'),refetchInterval:15000})
  const {data:detail,error:detailError}=useQuery({queryKey:keys.news.detail(event,scoreId,company),queryFn:()=>api<NewsDetail>('/lab/news/events/'+encodeURIComponent(event)+'?'+new URLSearchParams({score_id:scoreId,company})),enabled:!!event,refetchInterval:15000})
  const trigger=useRef<HTMLElement|null>(null),closeRef=useRef<HTMLButtonElement>(null)
  const returnPosition=useRef<{x:number;y:number}|null>(null)
  const [narrow,setNarrow]=useState(()=>matchMedia('(max-width: 1100px)').matches),[busy,setBusy]=useState(false)
  useEffect(()=>{const media=matchMedia('(max-width: 1100px)');const change=()=>setNarrow(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[])
  const close=useCallback(()=>{patch({event:null,score:null,view:null})},[patch])
  useEffect(()=>{if(event){if(!narrow)closeRef.current?.focus({preventScroll:true})}else if(trigger.current?.isConnected){if(returnPosition.current)window.scrollTo({left:returnPosition.current.x,top:returnPosition.current.y});if(!narrow)trigger.current.focus({preventScroll:true})}},[event,narrow])
  const selectedScore=detail?.selected?.id
  useEffect(()=>{if(event&&!scoreId&&selectedScore)patch({score:selectedScore},{replace:true})},[event,scoreId,selectedScore,patch])
  useEffect(()=>{if(!event||narrow)return;const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')close()};document.addEventListener('keydown',onKey);return()=>document.removeEventListener('keydown',onKey)},[event,narrow,close])
  const open=(id:string,score:string|undefined,mode:string,node:HTMLElement)=>{trigger.current=node;returnPosition.current={x:window.scrollX,y:window.scrollY};patch({event:id,score:score||null,view:mode})}
  async function run(){setBusy(true);try{await api('/lab/news/runs',{operation_id:operation(),kind:'collect'});notify('采集已排队，可在来源与运行查看进度','ok');client.invalidateQueries({queryKey:keys.news.status})}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
  const content=detail?<EventDetail key={detail.selected?.id||detail.event.id} detail={detail} view={view} setView={v=>patch({view:v},{replace:true})}/>:detailError?<InlineError>{String(detailError)}</InlineError>:<Loading/>
  return <div className={app.page} data-testid="news-page">
    <LabHeader validation={String(status?.evaluation.status||'unvalidated')}><Button icon="clock" disabled={busy} onClick={run}>立即采集</Button></LabHeader>
    {status&&!status.runtime.installed&&<div className={s.notice}>先安装本地模型，新闻就可以结合公司研究框架打分。<Link to="/lab/news/settings">前往安装 →</Link></div>}
    {!!status?.evaluation.quality_observation&&<div className={s.notice}>{String(status.evaluation.quality_observation)}</div>}
    <div className={s.toolbar}><Seg label="新闻队列" value={queue} onChange={v=>patch({queue:v,offset:null,event:null,score:null})} options={[['selected','精选'],['uncertain','待确认'],['all','全部']].map(([value,label])=>({value,label:label+' '+(data?.counts[value]??'')}))}/>
      <label className={s.date}>日期<Input aria-label="新闻日期" type="date" value={date} onChange={e=>patch({date:e.target.value,offset:null,event:null,score:null})}/></label>{date&&<Button variant="ghost" size="sm" onClick={()=>patch({date:null,offset:null})}>最近 24 小时</Button>}
      <span className="muted">{queue==='selected'?'每天最多 20 个事件':'保留原始判断，便于核对漏选'}</span></div>
    {queue==='all'&&<div className={s.audit}><Button size="sm" variant={order==='low'?'primary':'default'} aria-pressed={order==='low'} onClick={()=>patch({order:order==='low'?null:'low',offset:null,event:null,score:null})}>低分抽查</Button><span className="muted">{order==='low'?'按关注分从低到高排列；未评分条目排在末尾。':'检查是否遗漏重要事件。'}</span></div>}
    <div className={s.layout} data-detail={event&&!narrow?'true':undefined}>
      <Card className={s.feed}>
        {error&&<InlineError>{String(error)}</InlineError>}{isLoading&&<Loading/>}
        {data&&!data.items.length&&<EmptyState><b>{queue==='selected'?'还没有进入精选的事件':'这里暂时没有新闻'}</b><p>{queue==='selected'?'可以查看待确认新闻，或添加与你覆盖公司相关的来源。':'立即采集公开来源；没有公司研究框架的新闻也会保留供抽查。'}</p><Button onClick={()=>patch({queue:queue==='selected'?'uncertain':'all',offset:null})}>查看{queue==='selected'?'待确认':'全部'}</Button></EmptyState>}
        {data?.items.map(item=><article key={item.id} className={s.event} data-selected={event===item.id?'true':undefined} data-testid="news-event">
          <button className={s.score} aria-label={'查看评分：'+item.title} onClick={e=>open(item.id,item.score?.id,'score',e.currentTarget)}><strong>{item.score?.priority==null?'—':Math.round(item.score.priority)}</strong><span>关注分 / 100</span></button>
          <div className={s.eventBody}><div className={s.meta}>{item.companies.map(c=><Badge key={c} tone="accent">{c}</Badge>)}<span>{item.article_count} 篇报道</span><span>{relativeTime(item.updated_at)}</span>{item.score?.queue==='uncertain'&&<Badge tone="warn">待确认</Badge>}</div>
            <button className={s.title} onClick={e=>open(item.id,item.score?.id,'article',e.currentTarget)}>{item.title}</button>
            {item.score&&<ScoreParts score={item.score}/>}
            {item.score?.references[0]&&<p className={s.connection}><span>关联研究</span>{String(item.score.references[0].title)}</p>}
            {!!item.score?.reasons.length&&<p className={s.reason}>{item.score.reasons[0]}</p>}
          </div></article>)}
        {data&&data.total>50&&<div className={s.pagination}><Button disabled={offset===0} onClick={()=>patch({offset:Math.max(0,offset-50)})}>上一页</Button><span>{offset+1}–{Math.min(offset+50,data.total)} / {data.total}</span><Button disabled={offset+50>=data.total} onClick={()=>patch({offset:offset+50})}>下一页</Button></div>}
      </Card>
      {event&&!narrow&&<Card className={s.rail} role="complementary" aria-label="新闻评分与原文" data-testid="news-detail"><div className={s.railHead}><b>事件与依据</b><IconButton ref={closeRef} icon="x" label="关闭新闻详情" plain onClick={close}/></div><div className={s.railBody}>{content}</div></Card>}
    </div>
    {narrow&&<Drawer open={!!event} onOpenChange={o=>{if(!o)close()}} side="bottom" title="事件与依据" testId="news-detail" returnFocusRef={trigger}>{content}</Drawer>}
  </div>
}

function EventDetail({detail,view,setView}:{detail:NewsDetail;view:string;setView:(v:string)=>void}){
  const {patch}=useUrlState(),client=useQueryClient(),navigate=useNavigate(),{notify}=useToast()
  const score=detail.selected
  const [chosen,setChosen]=useState<string[]>(score&&detail.articles.some(a=>a.id===score.article_id&&a.original_file)?[score.article_id]:[]),[busy,setBusy]=useState(false)
  const draftOperation=useRef(operation())
  async function feedback(verdict:string){if(!score)return;setBusy(true);try{await api('/lab/news/events/'+detail.event.id+'/feedback',{operation_id:operation(),score_id:score.id,verdict});notify('已记录你的判断，用于实验评估','ok');client.invalidateQueries({queryKey:['lab-news-detail']});client.invalidateQueries({queryKey:keys.news.status})}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
  async function research(){if(!score)return;setBusy(true);try{const draft=await api<NewsResearchDraft>('/lab/news/events/'+detail.event.id+'/research-draft',{operation_id:draftOperation.current,score_id:score.id,article_ids:chosen});navigate('/research?news_draft='+encodeURIComponent(draft.id))}catch(e){notify(String(e),'danger')}finally{setBusy(false)}}
  const latestByCompany=detail.scores.filter((item,i,all)=>all.findIndex(x=>x.company===item.company)===i)
  return <div className={s.detailContent}>
    <h2>{detail.event.title}</h2>
    {latestByCompany.length>1&&<div className={s.companyButtons}>{latestByCompany.map(item=><Button key={item.company} size="sm" variant={score?.company===item.company?'primary':'default'} onClick={()=>patch({score:item.id},{replace:true})}>{item.company||'未匹配公司'}</Button>)}</div>}
    {detail.latest_score_id&&score?.id!==detail.latest_score_id&&<div className={s.notice}>已有新评分；当前保留你打开的版本。<Button size="sm" onClick={()=>patch({score:detail.latest_score_id},{replace:true})}>查看新评分</Button></div>}
    <Seg label="新闻详情视图" value={view} onChange={setView} options={[{value:'score',label:'评分依据'},{value:'article',label:'原文与报道'}]}/>
    {view==='score'&&score&&<>
      <div className={s.scoreHeading}><strong>{score.priority==null?'—':score.priority.toFixed(1)}<small> / 100</small></strong><div>关注优先级<Badge tone="warn">实验评分</Badge></div></div>
      <p className="muted">关注分用于安排阅读顺序。模型置信度尚未经过本实验的人工样本校准。</p>
      <div className={s.dimensions}>{dimensions.map(([key,label,weight])=><div key={key}><div><b>{label}</b><span>{score.dimensions[key]==null?'—':Math.round(score.dimensions[key]*100)} / 100 · 权重 {weight}%</span></div><meter min="0" max="1" value={score.dimensions[key]||0} aria-label={label+'分数'}/>{score.confidence[key]!=null&&<small>模型置信度 {Math.round(score.confidence[key]*100)}% · {score.calibration}</small>}</div>)}</div>
      {score.reasons.map((reason,i)=><p key={i} className={s.reason}>{reason}</p>)}
      <h3>关联的公司研究</h3>{score.references.length?score.references.filter((r,i,a)=>a.findIndex(x=>x.ref===r.ref)===i).map((r,i)=><p key={i}><Link to={String(r.href||'/companies/'+score.company)}>{String(r.title)}</Link><small className={s.ref}>{String(r.ref)}</small></p>):<p className="muted">尚无可用的研究条目。</p>}
      <h3>本次使用的新闻片段</h3>{score.inputs.map((input,i)=><blockquote key={i} className={s.quote}>{String((input.passage as {text?:string})?.text||'')}</blockquote>)}
      <details className={s.technical}><summary>评分版本与模型原始输出</summary><p>{score.policy_version} · {dateTime(score.created_at)}</p><pre>{JSON.stringify({model:score.model,inputs:score.inputs,raw:score.raw},null,2)}</pre></details>
    </>}
    {view==='article'&&detail.articles.map(article=><section key={article.id} className={s.article}><label className={s.material}><input type="checkbox" checked={chosen.includes(article.id)} disabled={!article.original_file||busy} onChange={e=>{draftOperation.current=operation();setChosen(e.target.checked?[...chosen,article.id].slice(0,10):chosen.filter(id=>id!==article.id))}}/>带入研究</label><b>{article.title}</b><div className={s.meta}><Badge>{article.source_name}</Badge><span>{article.published_at?dateTime(article.published_at):'发布时间未知'}</span></div><small>收录于 {dateTime(article.observed_at)}</small>{article.issues.map((issue,i)=><p className={s.reason} key={i}>{issue}</p>)}<p className={s.articleText}>{article.text||article.excerpt||'尚无正文，请打开原文核对。'}</p><div className={s.actions}><a href={article.url} target="_blank" rel="noopener noreferrer">打开来源网站 ↗</a>{article.original_file&&<a href={'/api/v1/lab/news/articles/'+article.id+'/original'} target="_blank" rel="noopener noreferrer">查看已保存原件 ↗</a>}</div></section>)}
    <div className={s.feedback}><h3>这条新闻值得关注吗？</h3><div className={s.actions}>{[['useful','值得关注'],['irrelevant','不相关'],['duplicate','重复'],['raise','提高优先级']].map(([value,label])=><Button key={value} size="sm" disabled={busy||!score} onClick={()=>feedback(value)}>{label}</Button>)}</div><details className={s.technical}><summary>标注重要性，用于检查漏选</summary><p>即使分数很低，这个事件是否也应进入精选或待确认？</p><div className={s.actions}><Button size="sm" disabled={busy||!score} onClick={()=>feedback('important')}>重要事件</Button><Button size="sm" disabled={busy||!score} onClick={()=>feedback('not_important')}>非重要事件</Button></div></details>{detail.feedback.length>0&&<small className="muted">已记录 {detail.feedback.length} 次反馈；原始分数保留用于评估。</small>}</div>
    <Button variant="primary" icon="flask" disabled={busy||!score?.company||!chosen.length} onClick={research}>深入研究</Button><small className="muted">先打开研究草稿，提交后才调用研究 Agent。</small>
  </div>
}

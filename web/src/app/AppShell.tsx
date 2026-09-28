import {NavLink,Outlet,useLocation,useNavigate,useSearchParams} from 'react-router-dom'
import {useQuery} from '@tanstack/react-query'
import {useEffect,useState,type ReactNode} from 'react'
import s from './app.module.css'
import {useCompany} from './company'
import {CommandPalette,useCommandPalette} from './CommandPalette'
import {resolvedTheme,toggleTheme} from './theme'
import {api} from '../lib/api'
import {keys} from '../lib/queryKeys'
import {Icon,IconButton,ErrorBoundary,Drawer,type IconName} from '../ui'
type Attention={reviews?:unknown[];changes?:unknown[]}
const items:{to:string;label:string;icon:IconName;match:(p:string)=>boolean}[]=[
  {to:'/today',label:'今日',icon:'inbox',match:p=>p.startsWith('/today')},
  {to:'/companies',label:'公司',icon:'building',match:p=>p.startsWith('/companies')||p.startsWith('/company')||p.startsWith('/entities')||p.startsWith('/wiki')},
  {to:'/research',label:'研究',icon:'flask',match:p=>p.startsWith('/research')},
  {to:'/review',label:'审核',icon:'check',match:p=>p.startsWith('/review')},
  {to:'/maintenance',label:'维护',icon:'wrench',match:p=>p.startsWith('/maintenance')},
]
export function AppShell({actions}:{actions?:ReactNode}){
  const {pathname}=useLocation();const navigate=useNavigate();const {company,companies,setCompany}=useCompany()
  const [params,setParams]=useSearchParams();const lab=pathname.startsWith('/lab');const [more,setMore]=useState(false)
  const palette=useCommandPalette()
  const {data:attention}=useQuery({queryKey:keys.attention,queryFn:()=>api<Attention>('/today'),refetchInterval:30000,retry:0})
  const decide=attention?.changes?.length||0
  const review=attention?.reviews?.length||0
  const [theme,setTheme]=useState<'light'|'dark'>(()=>resolvedTheme())
  useEffect(()=>{const media=window.matchMedia('(prefers-color-scheme: dark)');const sync=()=>setTheme(resolvedTheme());media.addEventListener('change',sync);window.addEventListener('pitr:theme',sync);return()=>{media.removeEventListener('change',sync);window.removeEventListener('pitr:theme',sync)}},[])
  const current=companies.find(c=>c.company===company)
  return <div className={s.app}>
    <aside className={s.rail}>
      <div className={s.brand}><span className={s.logo}>研</span><b>PITR</b></div>
      <nav aria-label="主导航" className={s.nav}>
        {items.map(it=><NavLink key={it.to} to={it.to} className={s.item} aria-current={it.match(pathname)?'page':undefined} data-testid={'nav-'+it.to.slice(1)}><Icon name={it.icon}/><span>{it.label}</span>{it.to==='/today'&&decide>0&&<span className={s.count} aria-label={`${decide} 项需要你决定`}>{decide}</span>}{it.to==='/review'&&review>0&&<span className={s.count+' '+s.soft} aria-label={`${review} 项待采纳`}>{review}</span>}</NavLink>)}
      </nav>
      <div className={s.railBottom}>
        <NavLink to="/lab/news" className={s.item} aria-current={lab?'page':undefined} data-testid="nav-lab"><Icon name="flask"/><span>Lab</span></NavLink>
        <NavLink to="/settings" className={s.item} aria-current={pathname.startsWith('/settings')?'page':undefined} data-testid="nav-settings"><Icon name="gear"/><span>设置</span></NavLink>
        <div className={s.local}><span style={{width:8,height:8,borderRadius:4,background:'var(--ok)',display:'inline-block'}}/><span>本机私有 · 127.0.0.1</span></div>
      </div>
    </aside>
    <div className={s.main}>
      <header className={s.topbar}>
        <select aria-label={lab?'新闻公司范围':'当前公司'} className={s.switch} value={lab?params.get('company')||'':company} onChange={e=>{if(lab){setParams(prev=>{const next=new URLSearchParams(prev);if(e.target.value)next.set('company',e.target.value);else next.delete('company');for(const k of ['event','score','offset'])next.delete(k);return next});return}setCompany(e.target.value);if(pathname.startsWith('/companies/'))navigate('/companies/'+encodeURIComponent(e.target.value))}} data-testid="company-switch">
          {lab&&<option value="">全部覆盖公司</option>}
          {!current&&company&&<option value={company}>{company}</option>}
          {companies.map(c=><option key={c.company} value={c.company}>{c.company}{c.name?` · ${c.name}`:''}</option>)}
          {!companies.length&&!company&&<option value="">尚未登记公司</option>}
        </select>
        <button type="button" className={s.cmdk} onClick={()=>palette.setOpen(true)} data-testid="open-palette"><Icon name="search"/><span>跳转公司、打开知识页，或直接提问…</span><kbd>⌘K</kbd></button>
        <div className={s.spacer}/>
        {actions}
        <IconButton icon={theme==='dark'?'sun':'moon'} label={theme==='dark'?'切换到浅色':'切换到深色'} onClick={()=>{toggleTheme();setTheme(resolvedTheme())}} data-testid="theme-toggle"/>
      </header>
      <main className={s.content}><ErrorBoundary label="页面"><Outlet/></ErrorBoundary></main>
      <nav className={s.bottomnav} aria-label="底部导航">
        {items.slice(0,4).map(it=><NavLink key={it.to} to={it.to} aria-current={it.match(pathname)?'page':undefined}><Icon name={it.icon} size={20}/>{it.label}</NavLink>)}
        <button type="button" className={s.moreButton} onClick={()=>setMore(true)} aria-label="更多页面" aria-current={lab||pathname.startsWith('/settings')||pathname.startsWith('/maintenance')?'page':undefined}><Icon name="menu" size={20}/>更多</button>
      </nav>
    </div>
    <CommandPalette open={palette.open} onOpenChange={palette.setOpen}/>
    <Drawer open={more} onOpenChange={setMore} side="bottom" title="更多页面">{[{to:'/lab/news',label:'Lab · 新闻雷达'},{to:'/maintenance',label:'维护'},{to:'/settings',label:'设置'}].map(item=><NavLink key={item.to} to={item.to} onClick={()=>setMore(false)} className={s.item}>{item.label}<Icon name="arrow"/></NavLink>)}</Drawer>
  </div>
}

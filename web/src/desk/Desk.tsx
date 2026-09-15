import {useState} from 'react'
import {NavLink,Routes,Route,Navigate,useLocation} from 'react-router-dom'
import {useQuery} from '@tanstack/react-query'
import {api} from './api'
import NativeResearch from './NativeResearch'
import Wiki from './WikiWorkbench'
import {Settings} from './Settings'
import AgentSelector from './AgentSelector'
import './desk.css'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/500.css'
export default function Desk(){
 const {pathname}=useLocation()
 const researchPage=pathname.startsWith('/research')
 const[company,setCompany]=useState(localStorage.getItem('desk.company')||'PDD'),[notice,setNotice]=useState('')
 const{data:home}=useQuery({queryKey:['home'],queryFn:()=>api('/home')})
 return <div className={'d-app'+(researchPage?' d-research-shell':'')}>
  <aside className="d-nav"><div className="d-brand">PITR <small>RESEARCH DESK</small></div>
   <nav aria-label="主导航"><NavLink to="/research"><span aria-hidden="true">⌕</span>研究</NavLink><NavLink to="/wiki"><span aria-hidden="true">▥</span>LLM Wiki</NavLink></nav>
   <div className="d-nav-bottom"><NavLink to="/settings">本机设置</NavLink><span><i/> 本机私有工作区</span></div>
  </aside><div className="d-main"><header className="d-top">
   {researchPage?<span className="rx-top-title">研究工作区</span>:<label>研究对象<select aria-label="研究公司" value={company} onChange={e=>{setCompany(e.target.value);localStorage.setItem('desk.company',e.target.value)}}>{[...new Set(['PDD','BABA','JD','AMZN','MELI',...(home?.companies||[])])].map(c=><option key={String(c)}>{String(c)}</option>)}</select></label>}
   <span className="d-top-context">证据研究 / 知识积累</span><div className="d-spacer"/><AgentSelector/><span className="d-local-dot">LOCAL</span>
  </header><main><Routes>
   <Route path="/research" element={<NativeResearch company={company} notify={setNotice}/>}/>
   <Route path="/research/:rid" element={<NativeResearch company={company} notify={setNotice}/>}/>
   <Route path="/wiki" element={<Wiki company={company} notify={setNotice}/>}/>
   <Route path="/settings" element={<Settings notify={setNotice}/>}/>
   <Route path="*" element={<Navigate to="/research" replace/>}/>
  </Routes></main></div>{notice&&<div className="d-toast" role="status" onClick={()=>setNotice('')}>{notice}<button aria-label="关闭通知" onClick={()=>setNotice('')}>×</button></div>}
 </div>
}

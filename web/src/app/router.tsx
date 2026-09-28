import {lazy,Suspense} from 'react'
import {Navigate,Route,Routes} from 'react-router-dom'
import {AppShell} from './AppShell'
import {Loading} from '../ui'
const Research=lazy(()=>import('../features/research/ResearchHome').then(m=>({default:m.ResearchHome})))
const Record=lazy(()=>import('../features/research/ResearchRecord').then(m=>({default:m.ResearchRecordPage})))
const Today=lazy(()=>import('../workbench/Today'))
const Companies=lazy(()=>import('../features/companies/CompaniesPage'))
const Company=lazy(()=>import('../features/companies/CompanyShell'))
const Review=lazy(()=>import('../workbench/Review'))
const Maintenance=lazy(()=>import('../workbench/Maintenance'))
const Evaluation=lazy(()=>import('../workbench/Evaluation'))
const Settings=lazy(()=>import('../workbench/Settings'))
const News=lazy(()=>import('../features/lab/NewsPage').then(m=>({default:m.NewsPage})))
const NewsSettings=lazy(()=>import('../features/lab/NewsSettings').then(m=>({default:m.NewsSettingsPage})))
export function AppRoutes(){return <Suspense fallback={<Loading/>}><Routes><Route element={<AppShell/>}>
  <Route path="/evaluations" element={<Evaluation/>}/><Route path="/today" element={<Today/>}/><Route path="/research" element={<Research/>}/><Route path="/research/:rid" element={<Record/>}/>
  <Route path="/companies" element={<Companies/>}/><Route path="/companies/:company/*" element={<Company/>}/>
  <Route path="/review/*" element={<Review/>}/><Route path="/maintenance/*" element={<Maintenance/>}/><Route path="/settings/*" element={<Settings/>}/>
  <Route path="/maintenance" element={<Navigate to="/maintenance/jobs" replace/>}/><Route path="/settings" element={<Navigate to="/settings/agents" replace/>}/>
  <Route path="/lab/news" element={<News/>}/><Route path="/lab/news/settings" element={<NewsSettings/>}/>
  <Route path="*" element={<Navigate to="/today" replace/>}/>
</Route></Routes></Suspense>}

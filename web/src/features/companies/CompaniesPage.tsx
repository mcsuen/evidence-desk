import {useState} from 'react'
import {Link} from 'react-router-dom'
import {Badge,Button,Card,CardHeader,EmptyState,Input,Table} from '../../ui'
import {Pending,useData} from '../../workbench/shared'
import {Register} from '../../workbench/CompanyInputs'
import type {Subject} from '../../types/subject'
import app from '../../app/app.module.css'
export default function CompaniesPage(){
 const {data,error}=useData<Subject[]>('/subjects'),[search,setSearch]=useState(''),[adding,setAdding]=useState(false)
 if(!data)return <Pending error={error}/>
 const list=data.filter(c=>(c.name+' '+c.id+' '+c.aliases.join(' ')).toLowerCase().includes(search.toLowerCase()))
 return <div className={app.page}><header className={app.pageHead}><h1 className="display">公司</h1><span className="sub">持续积累的材料、判断与研究记录</span><span className={app.spacer}/><Button icon="plus" variant="primary" onClick={()=>setAdding(!adding)}>登记公司</Button></header>{adding&&<Register onSaved={()=>setAdding(false)}/>}<Card><CardHeader title="覆盖公司"><Input type="search" aria-label="搜索公司" placeholder="公司、代码或别名…" value={search} onChange={e=>setSearch(e.target.value)} style={{marginLeft:'auto',width:240}}/><span className="sub">{list.length} 家</span></CardHeader>{list.length?<Table><thead><tr><th>公司</th><th>名称与别名</th><th>主体身份</th><th>研究</th></tr></thead><tbody>{list.map(c=><tr key={c.id}><td><Link to={'/companies/'+encodeURIComponent(c.id)} className="mono"><b>{c.id}</b></Link></td><td><Link to={'/companies/'+encodeURIComponent(c.id)} style={{color:'var(--ink)'}}>{c.name}</Link><p className="sub">{c.aliases.join(' · ')}</p></td><td><Badge>{c.status==='verified'?'身份已核实':c.status==='manual'?'人工登记':'待识别'}</Badge></td><td><Link to={'/research?company='+encodeURIComponent(c.id)}>提出问题 →</Link></td></tr>)}</tbody></Table>:<EmptyState>没有符合条件的公司。登记主体后即可绑定研究材料。</EmptyState>}</Card></div>
}

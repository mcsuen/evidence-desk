import {useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {api} from './api'
import SlackSettings from './SlackSettings'
import {AgentSettings} from './AgentSelector'
export function Settings({notify}:{notify:(s:string)=>void}){
 const[values,setValues]=useState<Record<string,string>>({});const{data={},refetch}=useQuery({queryKey:['settings'],queryFn:()=>api('/settings')})
 const fields=[['sec_user_agent','SEC 应用名称与联系邮箱']]
 return <div className="d-settings"><div className="d-page-title"><h1>本机设置</h1><span className="d-muted">密钥只保存在本机私有配置中</span></div><AgentSettings/><h2>可选资料服务</h2><div className="d-settings-form">{fields.map(([key,label])=><label key={key}>{label}<input type={key.includes('token')?'password':'text'} autoComplete="off" value={values[key]??''} placeholder={data[key]?(key.includes('token')?'已保存；留空保留':data[key]):'未配置'} onChange={e=>setValues(v=>({...v,[key]:e.target.value}))}/></label>)}<button className="primary" onClick={async()=>{try{await api('/settings',Object.fromEntries(Object.entries(values).filter(([,v])=>v)));setValues({});refetch();notify('本机设置已保存')}catch(e){notify(String(e))}}}>保存本机设置</button></div><SlackSettings notify={notify}/></div>
}

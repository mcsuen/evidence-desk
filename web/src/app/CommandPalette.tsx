import {Command} from 'cmdk'
import * as Dialog from '@radix-ui/react-dialog'
import {useEffect,useState} from 'react'
import {useNavigate} from 'react-router-dom'
import s from './app.module.css'
import {useCompany} from './company'
import {Icon} from '../ui'
export function useCommandPalette(){
  const [open,setOpen]=useState(false)
  useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setOpen(o=>!o)}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[])
  return {open,setOpen}
}
export function CommandPalette({open,onOpenChange}:{open:boolean;onOpenChange:(o:boolean)=>void}){
  const navigate=useNavigate();const {companies,setCompany}=useCompany();const [query,setQuery]=useState('')
  const go=(path:string)=>{onOpenChange(false);setQuery('');navigate(path)}
  const ask=query.trim()
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className={s.paletteOverlay}/><Dialog.Content className={s.palette} aria-label="命令面板"><Dialog.Title className="sr-only">命令面板</Dialog.Title>
    <Command label="跳转或提问" loop><Command.Input value={query} onValueChange={setQuery} placeholder="跳转公司、打开页面，或直接输入问题…" autoFocus/>
    <Command.List><Command.Empty>没有匹配项。按回车把这句话作为研究问题。</Command.Empty>
      {ask&&<Command.Group heading="研究"><Command.Item value={'ask '+ask} onSelect={()=>go('/research?question='+encodeURIComponent(ask))}><Icon name="flask"/>就“{ask}”开始研究<small>回车</small></Command.Item></Command.Group>}
      <Command.Group heading="公司">{companies.map(c=><Command.Item key={c.company} value={`company ${c.company} ${c.name||''}`} onSelect={()=>{setCompany(c.company);go('/companies/'+encodeURIComponent(c.company))}}><Icon name="building"/>{c.company}{c.name?<span className="muted"> · {c.name}</span>:null}<small>公司主页</small></Command.Item>)}</Command.Group>
      <Command.Group heading="页面">
        <Command.Item value="lab 新闻 雷达 实验" onSelect={()=>go('/lab/news')}><Icon name="flask"/>Lab · 新闻雷达</Command.Item>
        <Command.Item value="today 今日 收件箱" onSelect={()=>go('/today')}><Icon name="inbox"/>今日</Command.Item>
        <Command.Item value="research 研究 提问" onSelect={()=>go('/research')}><Icon name="flask"/>研究 · 提问</Command.Item>
        <Command.Item value="review 审核 待采纳" onSelect={()=>go('/review')}><Icon name="check"/>审核</Command.Item>
        <Command.Item value="maintenance 维护 任务 计划" onSelect={()=>go('/maintenance')}><Icon name="wrench"/>维护</Command.Item>
        <Command.Item value="settings 设置" onSelect={()=>go('/settings')}><Icon name="gear"/>设置</Command.Item>
      </Command.Group>
    </Command.List></Command>
  </Dialog.Content></Dialog.Portal></Dialog.Root>
}

import * as RadixToast from '@radix-ui/react-toast'
import {createContext,useCallback,useContext,useMemo,useState,type ReactNode} from 'react'
import s from './ui.module.css'
import {Icon} from './icons'
type Item={id:number;text:string;tone:'info'|'ok'|'danger'}
type Api={notify:(text:string,tone?:Item['tone'])=>void}
const Ctx=createContext<Api>({notify:()=>{}})
export function ToastProvider({children}:{children:ReactNode}){
  const [items,setItems]=useState<Item[]>([])
  const notify=useCallback((text:string,tone:Item['tone']='info')=>{if(!text)return;setItems(list=>[...list.slice(-3),{id:Date.now()+Math.random(),text,tone}])},[])
  const api=useMemo(()=>({notify}),[notify])
  return <Ctx.Provider value={api}><RadixToast.Provider swipeDirection="down" duration={5000}>
    {children}
    {items.map(item=><RadixToast.Root key={item.id} className={s.toast} onOpenChange={open=>{if(!open)setItems(list=>list.filter(x=>x.id!==item.id))}}>
      <Icon name={item.tone==='danger'?'alert':item.tone==='ok'?'tick':'clock'} size={14} strokeWidth={2.2}/>
      <RadixToast.Description>{item.text}</RadixToast.Description>
      <RadixToast.Close aria-label="关闭通知"><Icon name="x" size={14}/></RadixToast.Close>
    </RadixToast.Root>)}
    <RadixToast.Viewport className={s.toastViewport}/>
  </RadixToast.Provider></Ctx.Provider>
}
export const useToast=()=>useContext(Ctx)

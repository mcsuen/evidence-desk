import {useCallback,useEffect,useRef,useState,type ReactNode,type RefObject} from 'react'
import {Card,Drawer,IconButton} from '../../ui'
import s from './research.module.css'
export function useNarrow(query='(max-width: 1100px)'){
  const [value,setValue]=useState(()=>window.matchMedia(query).matches)
  useEffect(()=>{const media=window.matchMedia(query);const changed=()=>setValue(media.matches);media.addEventListener('change',changed);changed();return()=>media.removeEventListener('change',changed)},[query]);return value
}
export function EvidenceRail({open,onClose,title,children,returnTo}:{open:boolean;onClose:()=>void;title:ReactNode;children:ReactNode;returnTo?:RefObject<HTMLElement|null>}){
  const narrow=useNarrow(),closeRef=useRef<HTMLButtonElement>(null)
  const restore=useCallback(()=>{onClose();setTimeout(()=>returnTo?.current?.focus({preventScroll:true}),0)},[onClose,returnTo])
  useEffect(()=>{if(open&&!narrow)closeRef.current?.focus({preventScroll:true})},[open,narrow])
  useEffect(()=>{if(!open||narrow)return;const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();restore()}};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key)},[open,narrow,restore])
  if(narrow)return <Drawer open={open} onOpenChange={o=>{if(!o)restore()}} side="bottom" title={title} testId="evidence-rail" returnFocusRef={returnTo}>{children}</Drawer>
  if(!open)return null
  return <Card className={s.rail} role="complementary" aria-label="原文与数值依据" data-testid="evidence-rail"><div className={s.railHeader}><span className="kicker">依据</span><b>{title}</b><IconButton ref={closeRef} icon="x" label="关闭依据" plain onClick={restore}/></div><div className={s.railBody}>{children}</div></Card>
}

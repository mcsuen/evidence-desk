import * as Dialog from '@radix-ui/react-dialog'
import type {ReactNode,RefObject} from 'react'
import s from './ui.module.css'
import {IconButton} from './Button'
export type DrawerSide='right'|'left'|'bottom'
/**
 * Drawer / side rail. `modal=false` keeps the page interactive (desktop evidence rail);
 * `modal` traps focus and shows a scrim (narrow screens). Focus returns to the trigger on close.
 */
export function Drawer({open,onOpenChange,side='right',modal=true,title,eyebrow,children,width,className='',actions,testId,returnFocusRef}:{open:boolean;onOpenChange:(open:boolean)=>void;side?:DrawerSide;modal?:boolean;title:ReactNode;eyebrow?:ReactNode;children:ReactNode;width?:number|string;className?:string;actions?:ReactNode;testId?:string;returnFocusRef?:RefObject<HTMLElement|null>}){
  const sideClass=side==='right'?s.right:side==='left'?s.left:s.bottom
  return <Dialog.Root open={open} onOpenChange={onOpenChange} modal={modal}>
    <Dialog.Portal>
      {modal&&<Dialog.Overlay className={s.overlay}/>}
      <Dialog.Content className={[s.drawer,sideClass,className].filter(Boolean).join(' ')} style={width?{width}:undefined} data-testid={testId} onInteractOutside={e=>{if(!modal)e.preventDefault()}} onCloseAutoFocus={e=>{if(returnFocusRef?.current){e.preventDefault();returnFocusRef.current.focus({preventScroll:true})}}}>
        {side==='bottom'&&<div className={s.handle} aria-hidden="true"/>}
        <div className={s.drawerH}>{eyebrow&&<span className="kicker">{eyebrow}</span>}<Dialog.Title asChild><h2>{title}</h2></Dialog.Title>{actions}<Dialog.Close asChild><IconButton icon="x" label="关闭" plain style={{marginLeft:'auto',width:28,height:28}}/></Dialog.Close></div>
        <div className={s.drawerBody}>{children}</div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

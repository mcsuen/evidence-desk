import type {CSSProperties,ReactNode} from 'react'
import s from './ui.module.css'
import {Icon} from './icons'
export function EmptyState({children,action}:{children:ReactNode;action?:ReactNode}){return <div className={s.empty}><div>{children}</div>{action}</div>}
export function Skeleton({width,height=14,style}:{width?:number|string;height?:number|string;style?:CSSProperties}){return <div className={s.skeleton} style={{width,height,...style}} aria-hidden="true"/>}
export function Loading({children='正在读取…'}:{children?:ReactNode}){return <p role="status" className="muted" style={{fontSize:13,padding:'12px 0'}}>{children}</p>}
export function InlineError({children}:{children:ReactNode}){return <div role="alert" className={s.inlineError}><Icon name="alert" size={14}/><div>{children}</div></div>}

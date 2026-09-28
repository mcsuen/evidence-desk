import type {HTMLAttributes,ReactNode} from 'react'
import s from './ui.module.css'
import {Icon,type IconName} from './icons'
export type Tone='default'|'ok'|'warn'|'danger'|'accent'
const toneClass:Record<Tone,string>={default:'',ok:s.ok,warn:s.warn,danger:s.dangerBadge,accent:s.accent}
export function Badge({tone='default',icon,children,className='',...rest}:{tone?:Tone;icon?:IconName;children:ReactNode}&HTMLAttributes<HTMLSpanElement>){
  return <span className={[s.badge,toneClass[tone],className].filter(Boolean).join(' ')} {...rest}>{icon&&<Icon name={icon} size={13} strokeWidth={2.2}/>}{children}</span>
}
export type DotTone='pending'|'ok'|'warn'|'danger'|'accent'
const dotClass:Record<DotTone,string>={pending:'',ok:s.dotOk,warn:s.dotWarn,danger:s.dotDanger,accent:s.dotAccent}
export function Dot({tone='pending',label,className=''}:{tone?:DotTone;label?:string;className?:string}){
  return <span className={[s.dot,dotClass[tone],className].filter(Boolean).join(' ')} role={label?'img':undefined} aria-label={label}/>
}
export type EvidenceKind='official'|'author'|'infer'
export const evidenceLabel:Record<EvidenceKind,string>={official:'官方披露',author:'附件作者观点',infer:'研究推断'}
export function EvidenceTag({kind,children,className=''}:{kind:EvidenceKind;children?:ReactNode;className?:string}){
  return <span className={[s.ev,s[kind],className].filter(Boolean).join(' ')}>{children??evidenceLabel[kind]}</span>
}
/** Map an evidence/claim role string from the API to a tag kind. */
export function evidenceKind(role:string|null|undefined):EvidenceKind{
  const r=(role||'').toLowerCase()
  if(r.includes('author')||r.includes('attachment')||r==='opinion')return 'author'
  if(r.includes('infer')||r.includes('interpret')||r==='analysis'||r==='derived')return 'infer'
  return 'official'
}

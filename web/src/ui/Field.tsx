import {forwardRef,type InputHTMLAttributes,type ReactNode,type SelectHTMLAttributes,type TextareaHTMLAttributes} from 'react'
import s from './ui.module.css'
export const Input=forwardRef<HTMLInputElement,InputHTMLAttributes<HTMLInputElement>>(function Input({className='',...rest},ref){return <input ref={ref} className={[s.input,className].filter(Boolean).join(' ')} {...rest}/>})
export const Select=forwardRef<HTMLSelectElement,SelectHTMLAttributes<HTMLSelectElement>>(function Select({className='',...rest},ref){return <select ref={ref} className={[s.input,className].filter(Boolean).join(' ')} {...rest}/>})
export const Textarea=forwardRef<HTMLTextAreaElement,TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({className='',...rest},ref){return <textarea ref={ref} className={[s.input,className].filter(Boolean).join(' ')} {...rest}/>})
export function Field({label,children,hint}:{label:ReactNode;children:ReactNode;hint?:ReactNode}){return <label className={s.field}><span>{label}</span>{children}{hint&&<span className="muted">{hint}</span>}</label>}

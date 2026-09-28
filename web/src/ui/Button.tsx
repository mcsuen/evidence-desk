import {forwardRef,type ButtonHTMLAttributes,type ReactNode} from 'react'
import s from './ui.module.css'
import {Icon,type IconName} from './icons'
type Variant='default'|'primary'|'ghost'|'danger'
export type ButtonProps=ButtonHTMLAttributes<HTMLButtonElement>&{variant?:Variant;size?:'md'|'sm';icon?:IconName;children?:ReactNode}
export const Button=forwardRef<HTMLButtonElement,ButtonProps>(function Button({variant='default',size='md',icon,className='',children,type='button',...rest},ref){
  const cls=[s.btn,variant==='primary'&&s.primary,variant==='ghost'&&s.ghost,variant==='danger'&&s.danger,size==='sm'&&s.sm,className].filter(Boolean).join(' ')
  return <button ref={ref} type={type} className={cls} {...rest}>{icon&&<Icon name={icon} size={size==='sm'?13:14}/>}{children}</button>
})
export const IconButton=forwardRef<HTMLButtonElement,ButtonHTMLAttributes<HTMLButtonElement>&{icon:IconName;label:string;plain?:boolean;size?:number}>(function IconButton({icon,label,plain,size=16,className='',type='button',...rest},ref){
  return <button ref={ref} type={type} aria-label={label} title={label} className={[s.btn,s.iconbtn,plain&&s.plain,className].filter(Boolean).join(' ')} {...rest}><Icon name={icon} size={size}/></button>
})

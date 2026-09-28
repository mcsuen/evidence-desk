import {forwardRef,type ButtonHTMLAttributes} from 'react'
import s from './ui.module.css'
/** A bound number in prose: the evidence entry point. */
export const NumberChip=forwardRef<HTMLButtonElement,ButtonHTMLAttributes<HTMLButtonElement>&{active?:boolean}>(function NumberChip({active,className='',type='button',...rest},ref){
  return <button ref={ref} type={type} className={[s.num,className].filter(Boolean).join(' ')} data-active={active?'true':undefined} {...rest}/>
})

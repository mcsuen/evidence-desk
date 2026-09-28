import type {HTMLAttributes,ReactNode} from 'react'
import s from './ui.module.css'
export function Card({className='',children,...rest}:HTMLAttributes<HTMLElement>&{children:ReactNode}){
  return <section className={[s.card,className].filter(Boolean).join(' ')} {...rest}>{children}</section>
}
export function CardHeader({title,children,className='',...rest}:{title:ReactNode;children?:ReactNode}&Omit<HTMLAttributes<HTMLDivElement>,'title'>){
  return <div className={[s.cardH,className].filter(Boolean).join(' ')} {...rest}><h2>{title}</h2>{children}</div>
}
export function Row({className='',children,...rest}:HTMLAttributes<HTMLDivElement>&{children:ReactNode}){
  return <div className={[s.row,className].filter(Boolean).join(' ')} {...rest}>{children}</div>
}
export function Table({className='',children,...rest}:HTMLAttributes<HTMLTableElement>&{children:ReactNode}){
  return <table className={[s.tbl,className].filter(Boolean).join(' ')} {...rest}>{children}</table>
}
export const numCell=s.n

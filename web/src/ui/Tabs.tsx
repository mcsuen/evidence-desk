import * as RadixTabs from '@radix-ui/react-tabs'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import type {ReactNode} from 'react'
import s from './ui.module.css'
export const Tabs=RadixTabs.Root
export const TabPanel=RadixTabs.Content
export function TabList({label,className='',children}:{label:string;className?:string;children:ReactNode}){
  return <RadixTabs.List aria-label={label} className={[s.tabs,className].filter(Boolean).join(' ')}>{children}</RadixTabs.List>
}
export function Tab({value,children,...rest}:{value:string;children:ReactNode}&RadixTabs.TabsTriggerProps){
  return <RadixTabs.Trigger value={value} className={s.tab} {...rest}>{children}</RadixTabs.Trigger>
}
/** Single-select segmented control. */
export function Seg({value,onChange,options,label}:{value:string;onChange:(v:string)=>void;options:{value:string;label:ReactNode}[];label:string}){
  return <ToggleGroup.Root type="single" value={value} onValueChange={v=>{if(v)onChange(v)}} aria-label={label} className={s.seg}>
    {options.map(o=><ToggleGroup.Item key={o.value} value={o.value} className={s.segItem}>{o.label}</ToggleGroup.Item>)}
  </ToggleGroup.Root>
}

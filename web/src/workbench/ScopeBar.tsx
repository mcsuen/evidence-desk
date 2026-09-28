import {Input,Field} from '../ui'
export function localDateTime(value:string){if(!value)return '';const date=new Date(value);return Number.isNaN(date.valueOf())?'':new Date(date.valueOf()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)}
export function scopeQuery(subject:string,asOf:string){const p=new URLSearchParams({subject});if(asOf){p.set('mode','historical');p.set('as_of',new Date(asOf).toISOString())}return p.toString()}
export default function ScopeBar({asOf,onChange}:{asOf:string;onChange:(value:string)=>void}){return <Field label="资料截止时间（留空查看当前）"><Input aria-label="资料截止时间" type="datetime-local" value={localDateTime(asOf)} onChange={e=>onChange(e.target.value)}/><small>{asOf?'当前显示在此时点前可得的材料与已采纳判断。':'来源更正和撤回会显示当前有效性提示，历史正文保留。'}</small></Field>}

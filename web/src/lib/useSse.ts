import {useEffect,useRef,useState} from 'react'
export type SseState='connecting'|'live'|'reconnecting'|'closed'
/** Subscribe to a server-sent event stream. `onEvent` receives (eventName, data, lastEventId). */
export function useSse(url:string|null,onEvent:(name:string,data:string,id:string)=>void,options:{events?:string[];enabled?:boolean}={}){
  const [state,setState]=useState<SseState>(url&&options.enabled!==false?'connecting':'closed')
  const handler=useRef(onEvent);handler.current=onEvent
  const names=(options.events||['message']).join(',')
  useEffect(()=>{
    if(!url||options.enabled===false){setState('closed');return}
    const stream=new EventSource(url)
    setState('connecting')
    stream.onopen=()=>setState('live')
    stream.onerror=()=>setState('reconnecting')
    const listeners=names.split(',').map(name=>{const fn=(e:Event)=>{const m=e as MessageEvent;handler.current(name,m.data,m.lastEventId)};stream.addEventListener(name,fn);return [name,fn] as const})
    return()=>{listeners.forEach(([n,fn])=>stream.removeEventListener(n,fn));stream.close();setState('closed')}
  },[url,names,options.enabled])
  return state
}

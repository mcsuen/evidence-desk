import {useCallback} from 'react'
import {useSearchParams} from 'react-router-dom'
/** Typed patch helper over URL search params: null/'' removes a key, other values set it. */
export function useUrlState(){
  const [params,setParams]=useSearchParams()
  const patch=useCallback((changes:Record<string,string|number|null|undefined>,options:{replace?:boolean}={})=>{
    setParams(prev=>{const next=new URLSearchParams(prev);for(const [k,v] of Object.entries(changes)){if(v==null||v==='')next.delete(k);else next.set(k,String(v))}return next},{replace:options.replace??false})
  },[setParams])
  const get=useCallback((key:string,fallback='')=>params.get(key)??fallback,[params])
  return {params,get,patch}
}

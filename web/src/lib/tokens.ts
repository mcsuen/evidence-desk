import {useEffect,useState} from 'react'
/** Read a CSS custom property from the document root (for ECharts / xyflow colours). */
export function token(name:string):string{
  if(typeof window==='undefined')return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name.startsWith('--')?name:'--'+name).trim()
}
export const series=()=>[token('s1'),token('s2'),token('s3'),token('s4')]
/** Re-render when the theme attribute or OS colour scheme changes. */
export function useThemeVersion(){
  const [version,setVersion]=useState(0)
  useEffect(()=>{
    const bump=()=>setVersion(v=>v+1)
    const observer=new MutationObserver(bump);observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','data-density']})
    const media=window.matchMedia('(prefers-color-scheme: dark)');media.addEventListener('change',bump)
    return()=>{observer.disconnect();media.removeEventListener('change',bump)}
  },[])
  return version
}

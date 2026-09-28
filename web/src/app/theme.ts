export type Theme='light'|'dark'|'system'
export type Density='compact'|'comfortable'
const THEME='pitr.theme',DENSITY='pitr.density'
const read=(k:string)=>{try{return localStorage.getItem(k)}catch{return null}}
const write=(k:string,v:string|null)=>{try{v==null?localStorage.removeItem(k):localStorage.setItem(k,v)}catch{}}
export function getTheme():Theme{const v=read(THEME);return v==='light'||v==='dark'?v:'system'}
export function applyTheme(theme:Theme){const root=document.documentElement;if(theme==='system')root.removeAttribute('data-theme');else root.setAttribute('data-theme',theme);write(THEME,theme==='system'?null:theme);window.dispatchEvent(new Event('pitr:theme'))}
export function resolvedTheme():'light'|'dark'{const t=getTheme();if(t!=='system')return t;return window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
export function toggleTheme(){applyTheme(resolvedTheme()==='dark'?'light':'dark')}
export function getDensity():Density{return read(DENSITY)==='comfortable'?'comfortable':'compact'}
export function applyDensity(d:Density){document.documentElement.setAttribute('data-density',d);write(DENSITY,d)}
export function bootTheme(){applyTheme(getTheme());applyDensity(getDensity())}

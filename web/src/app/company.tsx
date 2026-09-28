import {createContext,useCallback,useContext,useEffect,useMemo,useState,type ReactNode} from 'react'
import {useQuery} from '@tanstack/react-query'
import {api} from '../lib/api'
import {keys} from '../lib/queryKeys'
export type CompanyRow={company:string;name:string}
type Ctx={company:string;setCompany:(c:string)=>void;companies:CompanyRow[];loading:boolean}
const Context=createContext<Ctx>({company:'',setCompany:()=>{},companies:[],loading:false})
const KEY='pitr.company'
export function CompanyProvider({children}:{children:ReactNode}){
  const [company,set]=useState(()=>{try{return localStorage.getItem(KEY)||''}catch{return ''}})
  const {data,isLoading}=useQuery({queryKey:keys.companies,queryFn:async()=>{
    const rows=await api<{id:string;name:string}[]>('/subjects');return rows.map(c=>({company:c.id,name:c.name}))
  },staleTime:30000})
  const companies=useMemo(()=>data||[],[data])
  useEffect(()=>{if(companies.length)set(current=>current||companies[0].company)},[companies])
  const setCompany=useCallback((c:string)=>{set(c);try{localStorage.setItem(KEY,c)}catch{}},[])
  const value=useMemo(()=>({company,setCompany,companies,loading:isLoading}),[company,setCompany,companies,isLoading])
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export const useCompany=()=>useContext(Context)

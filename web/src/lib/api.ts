import {localFetch} from './localSession'
let selectionPending:Promise<unknown>|null=null
export function saveAgentSelection(body:unknown){
  const request=api('/settings',body)
  selectionPending=request
  return request.finally(()=>{if(selectionPending===request)selectionPending=null})
}
export async function api<T=any>(path:string, body?:unknown, method?:string):Promise<T>{
  if(body!==undefined&&path!=='/settings'&&selectionPending)await selectionPending
  const response=await localFetch('/api/v1'+path,body===undefined?(method?{method}:{}):{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  if(!response.ok){let message=`请求失败 (${response.status})`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)}catch{}throw new Error(message)}
  return response.json()
}
export async function upload(path:string,file:File,company=''){
  const body=new FormData();body.set('file',file);body.set('subjects',JSON.stringify(company?[company]:[]));body.set('operation_id',operation())
  const r=await localFetch('/api/v1'+path,{method:'POST',body});const result=await r.json();if(!r.ok)throw new Error(result.detail);return result
}
export const operation=()=>crypto.randomUUID()

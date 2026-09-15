import {localFetch} from './localSession'
let selectionPending:Promise<unknown>|null=null
export function saveAgentSelection(body:unknown){
  const request=api('/settings',body)
  selectionPending=request
  return request.finally(()=>{if(selectionPending===request)selectionPending=null})
}
export async function api<T=any>(path:string, body?:unknown, method?:string):Promise<T>{
  if(body!==undefined&&path!=='/settings'&&selectionPending)await selectionPending
  const response=await localFetch('/api/desk'+path,body===undefined?{}:{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  if(!response.ok){let message=`请求失败 (${response.status})`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)}catch{}throw new Error(message)}
  return response.json()
}
export async function upload(path:string,file:File,company='PDD'){
  const body=new FormData();body.set('file',file);body.set('company',company)
  const r=await localFetch('/api/desk'+path,{method:'POST',body});const result=await r.json();if(!r.ok)throw new Error(result.detail);return result
}
export const operation=()=>crypto.randomUUID()
export const number=(v:number|null|undefined,digits=1)=>v==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(v)
export const signed=(v:number|null|undefined,digits=1)=>v==null?'—':(v>0?'+':'')+number(v,digits)
export const state=(v:string)=>({pending:'待审核',adopted:'已采纳',rejected:'已驳回',invalidated:'依据失效',queued:'排队中',running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消',exploratory:'探索性',user_forecast:'自己的预测',consensus:'市场一致预期',guidance:'公司指引',vendor_placeholder:'供应商占位预测'}[v]||v)

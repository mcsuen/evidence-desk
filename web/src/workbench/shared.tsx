import {useQuery} from '@tanstack/react-query'
import {api} from '../lib/api'
import {Badge,EvidenceTag,InlineError,Loading,type Tone} from '../ui'
export const key=(ref:{id:string;revision:number})=>`${ref.id}@${ref.revision}`
export const labels:Record<string,string>={researching:'研究中',reviewing:'独立复核中',queued:'排队中',running:'研究中',waiting_user:'等待补充',budget_exhausted:'预算已用完',completed:'已结束',cancelled:'已取消',failed:'失败',
  ready:'可交付',draft:'待核验草稿',partial:'部分成果',not_run:'未执行',passed:'通过',unavailable:'不可用',skipped:'未执行',error:'错误',not_applicable:'不适用',
  available:'当前有效',needs_review:'依赖有变化',withdrawn:'已撤回',superseded:'已有新版本',pending:'待决定',adopt:'已采纳',reject:'未采纳',manual:'人工登记',verified:'原件核验',unverified:'未核验'}
export function Status({value}:{value:string}){const tone:Tone=['ready','passed','adopt','available'].includes(value)?'ok':['failed','error','withdrawn'].includes(value)?'danger':['partial','needs_review','budget_exhausted'].includes(value)?'warn':'default';return <Badge tone={tone}>{labels[value]||value}</Badge>}
export function useData<T=any>(path:string,interval?:number){return useQuery({queryKey:['v1',path],queryFn:()=>api<T>(path),refetchInterval:interval})}
export function Pending({error}:{error?:Error|null}){return error?<InlineError>{error.message}</InlineError>:<Loading/>}

export function SourceIdentity({role}:{role:string}){return role==='official'?<EvidenceTag kind="official">登记的披露域名</EvidenceTag>:role==='third_party'?<EvidenceTag kind="author">第三方来源</EvidenceTag>:<Badge icon="file">上传材料</Badge>}

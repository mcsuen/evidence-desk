import type {EvidenceAnchor,Paragraph,Ref,SourceVersion} from '../../types/report_view'

const key=(ref:Ref)=>`${ref.id}@${ref.revision}`

export type Inline = Paragraph['inlines'][number]
export type ReadingSelection = {refs:Ref[];title:string;literal?:string}
export type SelectEvidence = (selection:ReadingSelection,trigger:HTMLElement)=>void

export function uniqueRefs(refs:Ref[]):Ref[]{
  return [...new Map(refs.map(ref=>[key(ref),ref])).values()]
}

export function citations(inlines:Inline[]):Ref[]{
  return uniqueRefs(inlines.flatMap(span=>span.type==='citation'?[span.ref]:[]))
}

export function sourceGroups(refs:Ref[],evidence:EvidenceAnchor[],sources:SourceVersion[]){
  const groups=new Map<string,{source:SourceVersion;anchors:EvidenceAnchor[]}>()
  for(const ref of uniqueRefs(refs)){
    const anchor=evidence.find(item=>key(item)===key(ref))
    const source=anchor&&sources.find(item=>key(item)===key(anchor.source))
    if(!anchor||!source)continue
    const group=groups.get(key(source))||{source,anchors:[]}
    group.anchors.push(anchor)
    groups.set(key(source),group)
  }
  return [...groups.values()]
}

export function pageLabel(anchors:EvidenceAnchor[]){
  const pages=[...new Set(anchors.flatMap(e=>e.page?[e.page]:[]))].sort((a,b)=>a-b)
  return pages.length?`第 ${pages.join('、')} 页`:`${anchors.length} 处原文`
}

export function originalUrl(source:Ref,page?:number|null){
  return `/api/v1/sources/${encodeURIComponent(source.id)}/revisions/${source.revision}/original${page?'#page='+page:''}`
}

/** Only literal matches inside the text's explicitly cited anchors become source links.
 * This is a reading aid, never a Value binding or a numerical verification. Do not
 * round, scale units, search other paragraphs, or pick between ambiguous matches.
 */
function numberTokens(text:string){
  const pattern=/(?<![A-Za-z0-9_.])[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?![A-Za-z0-9_.])/g
  return [...text.matchAll(pattern)].flatMap(match=>{
    let start=match.index!,literal=match[0],end=start+literal.length
    const prefix=text.slice(0,start)
    if(/[A-Za-z][A-Za-z0-9_.]*[-/]$/.test(prefix)||/(?:GPT|GLM|Kimi|Claude(?:\s+[A-Za-z]+)?|Bench|DeepSWE|GDPval|version|版本|港股|港交所|股份代号)[ \t-]*$/i.test(prefix))return []
    // Dates, years, model versions and small standalone counts are not data links.
    if(/^(?:19|20|21)\d{2}$/.test(literal)||!/[.,%％]/.test(literal)&&literal.replace(/\D/g,'').length<4)return []
    if((text[start-1]==='('&&text[end]===')')||(text[start-1]==='（'&&text[end]==='）')){
      start--;end++;literal=text.slice(start,end)
    }
    return [{start,end,literal}]
  })
}

export function linkedText(text:string,refs:Ref[],evidence:EvidenceAnchor[]){
  const allowed=new Set(refs.map(key))
  const anchors=evidence.filter(e=>allowed.has(key(e))).map(e=>({ref:e,literals:new Set(numberTokens(e.quote).map(n=>n.literal))}))
  const parts:Array<{text:string;ref?:Ref}>=[]
  let cursor=0
  for(const token of numberTokens(text)){
    const matches=anchors.filter(e=>e.literals.has(token.literal))
    if(matches.length!==1)continue
    if(token.start>cursor)parts.push({text:text.slice(cursor,token.start)})
    parts.push({text:token.literal,ref:matches[0].ref})
    cursor=token.end
  }
  if(cursor<text.length)parts.push({text:text.slice(cursor)})
  return parts
}

export function followingCitations(inlines:Inline[],index:number){
  const refs:Ref[]=[]
  for(const span of inlines.slice(index+1)){
    if(span.type==='text')break
    if(span.type==='citation')refs.push(span.ref)
  }
  return uniqueRefs(refs)
}

export const keys={
  news:{status:['lab-news-status'] as const,events:(scope:string)=>['lab-news-events',scope] as const,detail:(id:string,score:string,company:string)=>['lab-news-detail',id,score,company] as const,draft:(id:string)=>['lab-news-draft',id] as const},
  home:['home'] as const,
  settings:['settings'] as const,
  agents:['agents'] as const,
  attention:['attention'] as const,
  companies:['companies'] as const,
  research:{list:(company?:string)=>['research-requests',company||''] as const,one:(rid:string)=>['research',rid] as const,report:(rid:string,version:string|null)=>['research-report',rid,version||''] as const,trace:(rid:string,at:number|null)=>['research-trace',rid,at] as const},
  wiki:{workspace:(company:string,asOf:string)=>['wiki-workspace',company,asOf] as const,page:(id:string,version:string,asOf:string)=>['wiki-page',id,version,asOf] as const,proposals:(status:string,company:string)=>['wiki-proposals',status,company] as const},
  graph:{overview:(entity:string)=>['graph-overview',entity] as const,proposals:['graph-proposals'] as const,signals:['graph-signals'] as const},
}

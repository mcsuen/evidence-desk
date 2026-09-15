import {useEffect,useRef,useState} from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
pdfjs.GlobalWorkerOptions.workerSrc=workerUrl

export function PdfPage({sourceId,page,bbox,url}:{sourceId:string,page:number,bbox:number[]|null,url?:string}){
 const ref=useRef<HTMLCanvasElement>(null);const[error,setError]=useState('')
 useEffect(()=>{let cancelled=false;let render:any;const loading=pdfjs.getDocument(url||'/api/desk/documents/'+sourceId+'/file');loading.promise.then(async pdf=>{const p=await pdf.getPage(page);if(cancelled)return;const viewport=p.getViewport({scale:1.15});const c=ref.current;if(!c)return;c.width=viewport.width;c.height=viewport.height;render=p.render({canvas:c,viewport});await render.promise;if(cancelled)return;if(bbox){const ctx=c.getContext('2d')!;ctx.fillStyle='rgba(204,160,0,.2)';ctx.fillRect(bbox[0]*c.width,bbox[1]*c.height,(bbox[2]-bbox[0])*c.width,(bbox[3]-bbox[1])*c.height)}}).catch(e=>{if(!cancelled)setError(String(e))});return()=>{cancelled=true;render?.cancel();loading.destroy()}},[sourceId,page,bbox,url])
 return error?<p role="alert">原件预览失败，可在新窗口查看。</p>:<canvas className="d-pdf" ref={ref}/>
}

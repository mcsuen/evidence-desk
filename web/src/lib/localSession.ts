let csrf=''

export async function establishSession(){
  const params=new URLSearchParams(location.hash.slice(1))
  const ticket=params.get('bootstrap')
  if(ticket)history.replaceState(null,'',location.pathname+location.search)
  const response=await fetch('/api/local/session',ticket?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket}),credentials:'same-origin'}:{credentials:'same-origin'})
  // Existing development/test servers do not install the daemon boundary.
  if(response.status===404)return
  if(!response.ok){const value=await response.json();throw new Error(value.detail||'请再次运行 ./start 打开工作台')}
  csrf=(await response.json()).csrf
}

export async function localFetch(path:string,options:RequestInit={}){
  const write=!['GET','HEAD','OPTIONS'].includes(options.method||'GET')
  const send=()=>fetch(path,{...options,credentials:'same-origin',headers:{...options.headers,...(write&&csrf?{'X-PITR-CSRF':csrf}:{})}})
  let response=await send()
  if(response.status===403&&write&&csrf){
    // Another ./start may have renewed the shared cookie in a second tab.
    // The rejected write has had no effects and may be retried once.
    await establishSession();response=await send()
  }
  return response
}

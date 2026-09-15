import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {establishSession} from './desk/localSession'

const queryClient=new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:false}}})
const root=createRoot(document.getElementById('root')!)
root.render(<p role="status">正在连接本机工作台…</p>)
establishSession().then(()=>root.render(
  <StrictMode>
    <QueryClientProvider client={queryClient}><BrowserRouter>
      <App />
    </BrowserRouter></QueryClientProvider>
  </StrictMode>,
)).catch(error=>root.render(<main style={{maxWidth:560,margin:'12vh auto',fontFamily:'sans-serif'}}><h1>连接本机 PITR</h1><p role="alert">{String(error.message||error)}</p><p>在项目目录运行 <code>./start</code>。研究记录仍保存在本机。</p></main>))

import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/500.css'
import '@fontsource/noto-sans-sc/700.css'
import '@fontsource/noto-serif-sc/600.css'
import '@fontsource/noto-serif-sc/700.css'
import './styles/tokens.css'
import './styles/base.css'
import App from './App'
import {Providers} from './app/providers'
import {establishSession} from './lib/localSession'
import {bootTheme} from './app/theme'
bootTheme()
const root=createRoot(document.getElementById('root')!)
root.render(<p role="status" style={{padding:24,color:'var(--ink-3)'}}>正在连接本机工作台…</p>)
establishSession().then(()=>root.render(
  <StrictMode><Providers><App/></Providers></StrictMode>,
)).catch(error=>root.render(<main style={{maxWidth:560,margin:'12vh auto',padding:'0 16px'}}><h1 className="display" style={{fontSize:24,marginBottom:12}}>连接本机 PITR</h1><p role="alert">{String(error.message||error)}</p><p className="sub">在项目目录运行 <code>./start</code>。研究记录仍保存在本机。</p></main>))

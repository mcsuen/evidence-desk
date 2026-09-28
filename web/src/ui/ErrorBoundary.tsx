import {Component,type ErrorInfo,type ReactNode} from 'react'
import s from './ui.module.css'
/** Keeps a failing panel from blanking the whole page. */
export class ErrorBoundary extends Component<{children:ReactNode;label?:string;onReset?:()=>void},{error:Error|null}>{
  state={error:null as Error|null}
  static getDerivedStateFromError(error:Error){return {error}}
  componentDidCatch(error:Error,info:ErrorInfo){console.error('[pitr] render failure in',this.props.label||'panel',error,info.componentStack)}
  render(){
    if(!this.state.error)return this.props.children
    return <div role="alert" className={s.inlineError} data-testid="panel-error"><div><b>{this.props.label||'这一块'}暂时无法显示。</b><div>{String(this.state.error.message||this.state.error)}</div><button type="button" className={s.btn} style={{marginTop:8}} onClick={()=>{this.setState({error:null});this.props.onReset?.()}}>重试</button></div></div>
  }
}

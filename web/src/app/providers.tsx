import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import * as Tooltip from '@radix-ui/react-tooltip'
import {BrowserRouter} from 'react-router-dom'
import type {ReactNode} from 'react'
import {ToastProvider} from '../ui'
import {CompanyProvider} from './company'
const queryClient=new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:false}}})
export function Providers({children}:{children:ReactNode}){
  return <QueryClientProvider client={queryClient}><BrowserRouter><Tooltip.Provider delayDuration={300}><ToastProvider><CompanyProvider>{children}</CompanyProvider></ToastProvider></Tooltip.Provider></BrowserRouter></QueryClientProvider>
}

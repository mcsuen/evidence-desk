import {chromium} from '@playwright/test'
import fs from 'node:fs/promises'
const base=process.env.PITR_CAPTURE_URL||'http://127.0.0.1:18881',reference=process.env.PITR_CAPTURE_REFERENCE==='1',out=new URL('../../output/ui-restoration/'+(reference?'reference':'restored')+'/',import.meta.url).pathname
await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}})
const issues=[];page.on('pageerror',e=>issues.push(e.message));page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=500)issues.push(r.url()+' '+r.status())})
const rows=await (await page.request.get(base+(reference?'/api/desk/research/requests?limit=500':'/api/v1/cases'))).json(),rid=rows.find(r=>r.title?.includes('离线')||r.input?.question?.includes('离线'))?.id||rows[0]?.id
const routes={today:'/today',research:'/research',report:'/research/'+rid,flow:'/research/'+rid+'?tab=flow',waterfall:'/research/'+rid+'?tab=trace',companies:'/companies',company:'/companies/PDD',knowledge:'/companies/PDD/knowledge',sources:'/companies/PDD/sources',numbers:'/companies/PDD/numbers',map:'/companies/PDD/map',theses:'/companies/PDD/theses',questions:'/companies/PDD/questions',history:'/companies/PDD/history',review:'/review',maintenance:'/maintenance/jobs',settings:'/settings/agents',news:'/lab/news'}
for(const theme of ['light','dark'])for(const width of [1440,390]){
 await page.setViewportSize({width,height:width===390?844:1000})
 await page.goto(base+'/today');await page.evaluate(t=>{localStorage.setItem('pitr.theme',t);document.documentElement.setAttribute('data-theme',t)},theme)
 for(const [name,route] of Object.entries(routes)){
  await page.goto(base+route);await page.locator('h1').first().waitFor({timeout:15000});await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(name==='flow'||name==='map'||name==='numbers'?1600:450)
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)
  if(overflow)issues.push(`${theme}-${width}-${name}: page overflow`)
  await page.screenshot({path:out+`${theme}-${width}-${name}.png`,fullPage:false})
 }
}
await fs.writeFile(out+'issues.json',JSON.stringify(issues,null,2));await browser.close();console.log(JSON.stringify({out,count:Object.keys(routes).length*4,issues},null,2))

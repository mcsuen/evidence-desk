import {test,expect,type Page,type APIRequestContext} from '@playwright/test'
import type {EvidenceAnchor,Ref,ReportView,SourceVersion} from '../src/types/report_view'
import {linkedText,sourceGroups} from '../src/features/research/reportReading'

const ref=(id:string,revision=1):Ref=>({id,revision})
const anchor=(id:string,quote:string,source=ref('original')):EvidenceAnchor=>({id,revision:1,created_at:'2026-09-23T00:00:00Z',source,block_id:'p1',start:0,end:Array.from(quote).length,quote,page:1,bbox:[]})

test('literal links respect citation scope, signs, exact digits and ambiguity',()=>{
  const original=anchor('first','Revenue 724,334; loss (20.000); margin 28.3; GPT 5.6 Sol; Terminal Bench 3.0; 2025; 2513')
  const different=anchor('other','Another company reports 724,334 and 99.2',ref('other-source'))
  const text='收入724,334，亏损(20.000)，比例28.3；GPT 5.6 Sol、Terminal Bench 3.0、2025、港交所2513。'
  const parts=linkedText(text,[original],[original,different])
  expect(parts.map(p=>p.text).join('')).toBe(text)
  expect(parts.filter(p=>p.ref).map(p=>p.text)).toEqual(['724,334','(20.000)','28.3'])
  expect(linkedText('724,334',[original,different],[original,different]).some(p=>p.ref)).toBeFalsy()
  expect(linkedText('7.24亿、20.000、28.30、99.2',[original],[original,different]).some(p=>p.ref)).toBeFalsy()
  expect(linkedText('724,334',[],[original]).some(p=>p.ref)).toBeFalsy()
  expect(linkedText('724,334',[ref(original.id,2)],[original]).some(p=>p.ref)).toBeFalsy()
})

test('repeated citations collapse by source version, never by title or current head',()=>{
  const a=anchor('a','First original'),b=anchor('b','Another excerpt'),c=anchor('c','Corrected original',ref('original',2))
  const sources=[{...ref('original'),title:'同名原件'},{...ref('original',2),title:'同名原件'}] as SourceVersion[]
  const groups=sourceGroups([a,b,a,c],[a,b,c],sources)
  expect(groups.map(g=>({revision:g.source.revision,count:g.anchors.length}))).toEqual([{revision:1,count:2},{revision:2,count:1}])
})

async function readingFixture(page:Page,request:APIRequestContext){
  const cases=await(await request.get('/api/v1/cases')).json()
  const c=cases.find((c:{title:string})=>c.title==='离线界面验收：季度研究')
  const [run]=await(await request.get('/api/v1/runs?case_id='+c.id)).json()
  const view:ReportView=await(await request.get(`/api/v1/reports/${run.report.id}/revisions/1`)).json()
  const sourceBase=view.sources[0]
  const quote='Revenue 724,334; baseline 312,414; year-on-year 131.9.'
  const context='🧾 本页按人民币千元披露，经营口径与审计年度见表头。\n'
  const a={...anchor('reading-a',quote),start:Array.from(context).length,end:Array.from(context+quote).length}
  const b=anchor('reading-b','Operating income (20.000).')
  const d=anchor('reading-d','第三方注明客户结构尚未单独披露。',ref('third-party'))
  const e=anchor('reading-e','媒体转述管理层的经营解释。',ref('press'))
  const f=anchor('reading-f','年报对资本开支另有披露。',ref('annual'))
  const sources=[
    {...sourceBase,...ref('original'),title:'离线演示 · 年度经营披露',blocks:[{id:'p1',text:context+quote+'\n期后事项列在下一段，不能计入本期收入。',page:1,bbox:[]}]},
    {...sourceBase,...ref('third-party'),title:'离线演示 · 第三方行业观察',source_role:'third_party'},
    {...sourceBase,...ref('press'),title:'离线演示 · 经营说明'},
    {...sourceBase,...ref('annual'),title:'离线演示 · 年度报告'},
  ] as SourceVersion[]
  const citation=(r:Ref)=>({type:'citation' as const,ref:r})
  view.document.summary=[
    view.document.summary[0],
    {id:'source-only',type:'paragraph',assertions:[],inlines:[{type:'text',text:'来源记载收入724,334，基期为312,414。这里保留原文表述；业务结构仍需补充材料，不能把媒体转述视为已核验的经营判断。'},...[a,b,d,e,f,a].map(citation)]},
    {id:'rounded',type:'paragraph',assertions:[],inlines:[{type:'text',text:'约7.24亿只是这份旧报告的文字表述，没有独立的数值口径；保持原样并从本段来源继续核对。'},citation(a)]},
  ]
  view.document.sections=[{id:'table',title:'经营数据与原件对照',blocks:[{id:'table-data',type:'table',title:'财务披露摘录',columns:['项目','本期','基期','来源'],note:'独立界面夹具，不是公司研究结论。',rows:[[[{type:'text',text:'收入'}],[{type:'text',text:'724,334'}],[{type:'text',text:'312,414'}],[citation(a),citation(b)]]]}]}]
  view.evidence.push(a,b,d,e,f);view.sources.push(...sources)
  await page.route(`**/api/v1/reports/${view.document.id}/revisions/1`,route=>route.fulfill({json:view}))
  for(const source of sources)await page.route(`**/api/v1/objects/${source.id}/revisions/${source.revision}`,route=>route.fulfill({json:{object:source,dependencies:[source],current_validity:source.id==='original'?{status:'withdrawn',reason:'离线验收：原件已撤回'}:{status:'available'}}}))
  await page.goto('/research/'+c.id+'?version=1')
  await expect(page.getByTestId('research-answer')).toBeVisible()
  return view
}

test('report numbers open the exact original and group citations without changing prose',async({page,request})=>{
  const view=await readingFixture(page,request),answer=page.getByTestId('research-answer')
  await expect(answer.locator('ol>li')).toHaveCount(3)
  await expect(page.locator('button.citation')).toHaveCount(0)
  const paragraph=answer.locator('ol>li').nth(1)
  await expect(paragraph.getByTestId('report-sources').getByRole('button')).toHaveCount(3)
  await expect(paragraph.getByRole('button',{name:'查看全部 4 份来源'})).toBeVisible()
  await expect(answer.getByRole('button',{name:'查看原文中的数字：7.24'})).toHaveCount(0)
  const number=paragraph.getByRole('button',{name:'查看原文中的数字：724,334'})
  await number.click()
  const rail=page.getByTestId('evidence-rail')
  await expect(rail).toContainText('具体单位与口径请结合上下文核对')
  await expect(rail).toContainText('离线验收：原件已撤回')
  await expect(rail.locator('mark')).toHaveText('724,334')
  await expect(rail.getByRole('link',{name:'打开原件第 1 页'})).toHaveAttribute('href','/api/v1/sources/original/revisions/1/original#page=1')
  await rail.getByRole('button',{name:'查看前后文'}).click()
  await expect(rail).toContainText('🧾 本页按人民币千元披露')
  await expect(rail).toContainText('不能计入本期收入')
  await page.keyboard.press('Escape');await expect(number).toBeFocused()
  await paragraph.getByRole('button',{name:'查看全部 4 份来源'}).click()
  await expect(rail.getByTestId('evidence-source')).toHaveCount(4)
  await expect(rail.getByTestId('evidence-excerpt')).toHaveCount(5)
  await page.keyboard.press('Escape')
  const table=page.getByRole('table').first()
  await table.getByRole('button',{name:'查看原文中的数字：312,414'}).click()
  await expect(rail.locator('mark')).toHaveText('312,414')
  await page.keyboard.press('Escape')
  const typed=answer.getByRole('button',{name:/查看数值依据/})
  await typed.click();await expect(rail.getByTestId('value-detail')).toContainText('GAAP')
  await expect(rail.locator('mark')).toContainText(['100.000'])
  await page.keyboard.press('Escape');await expect(typed).toBeFocused()
  // The renderer never writes a new report or changes its canonical text.
  expect(await paragraph.locator('p').first().textContent()).toBe(view.document.summary[1].inlines.filter(s=>s.type==='text').map(s=>s.text).join(''))
})

for(const theme of ['light','dark'])for(const width of [1440,390])test(`report reading appearance ${theme} ${width}`,async({page,request})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
  await page.setViewportSize({width,height:width===390?844:1000})
  await page.addInitScript(theme=>localStorage.setItem('pitr.theme',theme),theme)
  await readingFixture(page,request)
  await page.evaluate(()=>document.fonts.ready)
  const answer=page.getByTestId('research-answer')
  await answer.evaluate(element=>element.scrollIntoView({block:'start'}))
  await expect(answer).toHaveScreenshot(`answer-${theme}-${width}.png`)
  const number=answer.getByRole('button',{name:'查看原文中的数字：724,334'})
  await number.click()
  const rail=page.getByTestId('evidence-rail')
  await expect(rail).toContainText('离线验收：原件已撤回')
  await expect(rail).toHaveScreenshot(`original-${theme}-${width}.png`)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy()
  await page.getByRole('button',{name:width===390?'关闭':'关闭依据',exact:true}).click()
  await expect(number).toBeFocused()
  expect(errors).toEqual([])
})

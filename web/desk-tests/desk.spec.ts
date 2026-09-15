import {test,expect} from '@playwright/test'
async function wikiCitation(page:any){
 await page.getByRole('combobox',{name:'引用来源',exact:true}).selectOption({index:1})
 await page.getByRole('combobox',{name:'原文段落',exact:true}).selectOption({index:1})
 await page.getByRole('button',{name:'加入证据',exact:true}).click()
}
test('Wiki source-linked draft, atomic publish and correction lifecycle',async({page})=>{
 await page.goto('/wiki?tab=index');await page.getByRole('button',{name:'新建知识页',exact:true}).click()
 await page.getByLabel('这次变更为什么需要一起发布').fill('记录利润率口径与未知事项')
 await page.getByLabel('标题',{exact:true}).fill('利润率口径与待解决问题')
 await page.getByLabel('正文',{exact:true}).fill('合并财务指标无法单独辨认业务组合影响，需保留未决问题。')
 await page.getByLabel('这项修改的理由').fill('原始披露尚未给出单独口径')
 await wikiCitation(page)
 await page.getByRole('button',{name:'校验并提交完整变更'}).click()
 await expect(page.locator('.ww-review')).toContainText('拟发布')
 await page.getByLabel('采纳或驳回理由').fill('页面保留未知，引用已检查')
 await page.getByLabel('我已核对完整变更、原始证据和关联影响').check()
 await page.getByRole('button',{name:'采纳并发布整批'}).click()
 await expect(page.locator('.ww-review')).toContainText('已采纳')
 await page.getByRole('button',{name:'公司概览',exact:true}).click()
 await expect(page.locator('.ww-navigation')).toContainText('利润率口径与待解决问题')
 await page.locator('.ww-navigation button').filter({hasText:'利润率口径与待解决问题'}).click()
 await page.getByRole('button',{name:'报告问题',exact:true}).click()
 await page.getByLabel('具体段落').fill('无法单独辨认')
 await page.getByLabel('疑点、依据与上下文').fill('检查是否遗漏独立披露')
 await page.getByRole('button',{name:'登记问题',exact:true}).click()
 await expect(page.locator('.w-issue').filter({hasText:'检查是否遗漏独立披露'})).toBeVisible()
 await page.locator('.w-issue').filter({hasText:'检查是否遗漏独立披露'}).getByLabel('处理理由',{exact:true}).fill('重新阅读原文后，确认这是一条误报')
 await page.getByRole('button',{name:'确认为误报',exact:true}).click()
 await expect(page.locator('.w-issue').filter({hasText:'检查是否遗漏独立披露'})).toContainText('已关闭')
})
test('Wiki method keeps applicability, failure cases and readable review',async({page})=>{
 await page.goto('/wiki?tab=index');await page.getByRole('button',{name:'新建知识页',exact:true}).click()
 await page.getByLabel('这次变更为什么需要一起发布').fill('维护可复用的应计分析方法')
 await page.getByLabel('标题',{exact:true}).fill('应计分析适用条件')
 await page.getByLabel('页面用途').selectOption('concept')
 await page.getByLabel('知识性质').selectOption('method')
 await page.getByLabel('正文',{exact:true}).fill('结合现金流和利润，调查差异的经济解释。')
 await page.getByLabel('适用条件',{exact:true}).fill('财务口径和期间相同')
 await page.getByLabel('公式',{exact:true}).fill('(net_income - operating_cash_flow) / average_assets')
 await page.getByLabel('失败情形',{exact:true}).fill('并购导致资产口径发生变化')
 await page.getByLabel('案例',{exact:true}).fill('先核对营运资本，再解释现金利润差异')
 await page.getByLabel('这项修改的理由').fill('保存适用边界与失败案例')
 await wikiCitation(page)
 await page.getByRole('button',{name:'校验并提交完整变更'}).click()
 await expect(page.locator('.ww-review')).toContainText('应计分析适用条件')
 await page.getByRole('button',{name:'编辑并重新校验',exact:true}).click()
 await expect(page.getByRole('textbox',{name:'失败情形',exact:true})).toHaveValue('并购导致资产口径发生变化')
})
test('Wiki three layers, stable page addresses and narrow reading drawer',async({page})=>{
 await page.goto('/wiki');await expect(page.getByRole('navigation',{name:'资料、知识与规范'})).toContainText('原始资料')
 await expect(page.getByRole('navigation',{name:'资料、知识与规范'})).toContainText('知识 Wiki')
 await expect(page.getByRole('navigation',{name:'资料、知识与规范'})).toContainText('维护规范')
 await page.locator('.ww-navigation button').filter({hasText:'利润率口径与待解决问题'}).click()
 await expect(page.locator('.ww-document h2').first()).toHaveText('利润率口径与待解决问题')
 expect(page.url()).toContain('page=');expect(page.url()).toContain('version=')
 await page.reload();await expect(page.locator('.ww-document h2').first()).toHaveText('利润率口径与待解决问题')
 const wikiUrl=page.url();await page.getByRole('link',{name:'带着此问题与版本继续研究 →'}).click()
 await expect(page).toHaveURL(/\/research\?company=PDD/);await expect(page.getByRole('textbox',{name:'研究问题',exact:true})).toHaveValue('利润率口径与待解决问题')
 expect(page.url()).toContain('wiki_ref=');await page.goBack();await expect(page).toHaveURL(wikiUrl)
 await page.screenshot({path:'/tmp/pitr-wiki-reading-desktop.png',fullPage:true})
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'展开三层目录'}).click()
 await expect(page.getByRole('navigation',{name:'资料、知识与规范'})).toBeVisible()
 await page.getByRole('button',{name:'公司概览',exact:true}).click()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.screenshot({path:'/tmp/pitr-wiki-reading-phone.png',fullPage:true})
})

test('Wiki answer keeps human edits, actual evidence and existing-topic writeback',async({page})=>{
 let release!:()=>void;const finished=new Promise<void>(resolve=>{release=resolve});let reading:any
 await page.route('**/api/desk/wiki/query/*/answer',route=>route.fulfill({json:{id:'wiki-answer-fixture',status:'queued'}}))
 await page.route('**/api/desk/tasks/wiki-answer-fixture',async route=>{await finished;const used=reading.items.filter((r:any)=>r.page_type==='topic').slice(0,1);await route.fulfill({json:{id:'wiki-answer-fixture',status:'completed',result:{answer:{title:'模型标题',content:'综合已有证据，继续保留业务组合影响的研究缺口。',used:used.map((r:any)=>({id:r.id,version:r.version})),citations:used.flatMap((r:any)=>r.citations),numeric_assertions:[]}}}})})
 await page.goto('/wiki?tab=query');await page.getByRole('textbox',{name:'研究问题',exact:true}).fill('利润率口径还有什么研究缺口？')
 const result=page.waitForResponse(r=>r.url().endsWith('/api/desk/wiki/query')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'查阅 Wiki 并回答'}).click();reading=await(await result).json();expect(reading.items.length).toBeGreaterThan(0)
 await page.getByText('编辑分析草稿',{exact:true}).click();await page.getByRole('textbox',{name:'分析标题',exact:true}).fill('人工编辑保留的研究标题');release()
 await expect(page.getByRole('textbox',{name:'新认识、比较与未解决问题'})).toHaveValue('综合已有证据，继续保留业务组合影响的研究缺口。')
 await expect(page.getByRole('textbox',{name:'分析标题',exact:true})).toHaveValue('人工编辑保留的研究标题')
 await page.getByRole('button',{name:'保存分析并提交审核'}).click()
 await expect(page.locator('.ww-review')).toContainText('人工编辑保留的研究标题')
 await expect(page.locator('.ww-review')).toContainText('利润率口径与待解决问题')
 await expect(page.locator('.ww-review')).toContainText('合并财务指标无法单独辨认业务组合影响')
})

async function numberFixture(page:any,id:string){
 const data=await(await page.request.get('/api/desk/wiki?company=PDD')).json();const metrics=await(await page.request.get('/api/desk/wiki/observations?company=PDD')).json();const metric=metrics.find((m:any)=>m.name==='revenue'&&m.period==='2025Q2')
 let hash=2166136261;for(const byte of new TextEncoder().encode(metric.citation.source_id+':'+metric.citation.block_id))hash=Math.imul(hash^byte,16777619)>>>0
 const anchor='evidence-'+hash.toString(16).padStart(8,'0').split('').map(c=>String.fromCharCode(97+parseInt(c,16))).join('')
 const content='## 经营规模\n\n原始收入为 ['+metric.value+'](#'+anchor+') 人民币百万元。\n\n'+('继续阅读并保留原始研究语境。\n\n'.repeat(30)),start=content.indexOf('[')+1
 const change={id,kind:'page',page_type:'topic',title:id==='page:PDD:historical-links'?'历史数字及独立原文定位':'公司季度业绩：费用与利润的原始依据',content,reason:'展示可追溯数值',citations:[metric.citation],numeric_assertions:[{field:'content',start,end:start+String(metric.value).length,observation_id:metric.id,name:metric.name,value:metric.value,unit:metric.unit,period:metric.period,basis:metric.basis}]}
 const base={company:'PDD',policy:{id:data.policy.id,version:data.policy.version},reason:'数值查证 '+id}
 const response=await page.request.post('/api/desk/wiki/proposals',{data:{...base,operation_id:'browser-'+id,changes:[change]}});expect(response.ok()).toBeTruthy()
 return {data,metric,change,base,proposal:await response.json()}
}
async function adoptFixture(page:any,p:any){const r=await page.request.post('/api/desk/wiki/proposals/'+p.id+'/review',{data:{operation_id:'adopt-'+p.id,digest:p.digest,action:'adopt',reason:'仅审核浏览器测试夹具'}});expect(r.ok()).toBeTruthy()}

test('Wiki quantitative preview opens a side panel, PDF/original link and keyboard return',async({page})=>{
 const{metric,proposal}=await numberFixture(page,'page:PDD:browser-numbers')
 await page.goto('/wiki?tab=review&proposal='+proposal.id)
 const link=page.locator('.ww-review-page').getByRole('link',{name:String(metric.value),exact:true});await link.click()
 const panel=page.getByRole('dialog',{name:'原文与数值依据'});await expect(panel).toBeVisible();await expect(panel.locator('blockquote')).toHaveText(metric.citation.quote)
 const url=await panel.getByRole('link',{name:'打开保存的原件 ↗'}).getAttribute('href');expect((await page.request.get(url!)).ok()).toBeTruthy()
 await page.keyboard.press('Escape');await expect(panel).toHaveCount(0);await expect(link).toBeFocused();await expect(link).toBeInViewport()
 await link.click();await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await panel.getByRole('button',{name:'返回原阅读位置'}).click()
})

test('Wiki exact-version historical evidence and refresh preserve provenance',async({page})=>{
 const{metric,proposal:first,change,base,data}=await numberFixture(page,'page:PDD:historical-links');await adoptFixture(page,first)
 await page.goto('/wiki?tab=page&page='+encodeURIComponent(change.id)+'&version=1&company=PDD')
 const link=page.locator('.ww-document > .w-prose, .ww-document > div > div > .w-prose').getByRole('link',{name:String(metric.value),exact:true})
 await link.click();const panel=page.getByRole('dialog',{name:'原文与数值依据'});await expect(panel.locator('blockquote')).toHaveText(metric.citation.quote);expect(page.url()).toContain('citation=')
 await page.reload();await expect(page.getByRole('dialog',{name:'原文与数值依据'})).toBeVisible();await page.keyboard.press('Escape')
 const source=data.sources.find((s:any)=>s.id===metric.citation.source_id),other=source.blocks.find((b:any)=>b.id!==metric.citation.block_id)
 const response=await page.request.post('/api/desk/wiki/proposals',{data:{...base,operation_id:'historical-links-second',changes:[{...change,expected_version:1,content:'新版本讨论证据范围，旧数字保留于原版本。',numeric_assertions:[],citations:[{source_id:source.id,block_id:other.id,quote:other.text}]}]}});expect(response.ok()).toBeTruthy();const second=await response.json()
 await page.goto('/wiki?tab=review&proposal='+second.id);await page.getByRole('button',{name:'对照修改前后'}).click();const before=page.locator('.w-diff > section').first();await before.getByRole('link',{name:String(metric.value),exact:true}).click();await expect(page.getByRole('dialog',{name:'原文与数值依据'}).locator('blockquote')).toHaveText(metric.citation.quote);await page.keyboard.press('Escape');await adoptFixture(page,second)
 await page.goto('/wiki?tab=page&page='+encodeURIComponent(change.id)+'&version=1&company=PDD');await expect(page.locator('.ww-document')).toContainText('原始收入为');await expect(page.locator('.ww-document')).toContainText('当前不可用于有效引用')
 await page.locator('.ww-document').getByRole('link',{name:String(metric.value),exact:true}).first().click();await expect(page.getByRole('dialog',{name:'原文与数值依据'}).locator('blockquote')).toHaveText(metric.citation.quote)
})

test('Wiki build request and update schedule are concrete and reversible',async({page})=>{
 let submitted:any
 await page.route('**/api/desk/wiki/jobs',async route=>{submitted=route.request().postDataJSON();await route.fulfill({json:{id:'fixture-job'}})})
 await page.route('**/api/desk/wiki/jobs/fixture-job',route=>route.fulfill({json:{id:'fixture-job',company:'PDD',request:{intent:'build',research_focus:submitted.research_focus},stage:'wiki_acquiring',execution_status:'running',publication_status:'not_published',materials:[],failures:[],skipped:[],checks:[],coverage:[{id:'media',label:'媒体与访谈',status:'gap'}],policy:{version:1}}}))
 await page.goto('/wiki');await page.getByRole('button',{name:'构建公司 Wiki',exact:true}).click();await page.getByRole('textbox',{name:'研究重点',exact:true}).fill('利润率与现金转化');await page.getByRole('button',{name:'开始搜集并构建'}).click();await expect(page.locator('.ww-job-detail')).toContainText('获取与处理原件');expect(submitted.budget_seconds).toBe(1200);expect(submitted.company).toBe('PDD');await expect(page.locator('.ww-job-detail')).toContainText('尚未发布')
 await page.goto('/wiki');await page.getByRole('button',{name:'更新设置',exact:true}).click();await page.getByLabel('时区',{exact:true}).fill('Asia/Shanghai');const saved=page.waitForResponse(r=>r.url().endsWith('/api/desk/wiki/schedules')&&r.request().method()==='POST');await page.getByRole('button',{name:'保存更新设置'}).click();expect((await saved).ok()).toBeTruthy();const schedule=await(await page.request.get('/api/desk/wiki/schedules?company=PDD')).json();expect(schedule.weekdays).toEqual([0]);expect(schedule.local_time).toBe('09:00');expect(schedule.enabled).toBe(true)
 await page.getByRole('button',{name:'更新设置',exact:true}).click();const cancelled=page.waitForResponse(r=>r.url().endsWith('/api/desk/wiki/schedules/PDD/cancel')&&r.request().method()==='POST');await page.getByRole('button',{name:'取消此计划'}).click();expect((await cancelled).ok()).toBeTruthy();expect((await(await page.request.get('/api/desk/wiki/schedules?company=PDD')).json()).cancelled).toBe(true)
})

test('Wiki acquisition failures, alternate originals and recovery remain distinct',async({page})=>{
 const record:any={id:'acquisition-fixture',company:'PDD',request:{intent:'build',research_focus:'获取真实公开资料'},stage:'finished',execution_status:'partial',publication_status:'waiting_review',policy:{version:1},checks:[],skipped:[],
  materials:[
   {url:'https://www.sec.gov/example',title:'监管申报',publisher:'SEC',status:'failed',error_type:'configuration_required',error:'需要真实联系邮箱',receipts:[{status:null,elapsed_seconds:0,phase:'configuration'}]},
   {url:'https://ec.europa.eu/example.pdf',alternative_of:'https://ec.europa.eu/example',title:'监管原件',publisher:'European Commission',provider:'regulatory',status:'acquired',acquisition_result:'alternative_acquired',source_id:'test-source',receipts:[{status:200,elapsed_seconds:1.8,bytes:81748}]},
   {url:'https://www.stats.gov.cn/example',title:'行业统计',publisher:'统计机构',status:'failed',error_type:'tls_error',error:'TLS handshake failed',receipts:[{status:null,error_type:'tls_error',elapsed_seconds:1}]}],
  coverage:[{id:'industry',label:'行业资料',status:'gap'}],failures:[{url:'https://www.stats.gov.cn/example',reason:'加密连接失败'}],previous_failures:[{job_id:'previous',url:'https://issuer.example/report',reason:'上次下载超时'}],supplemental_discovery:{search_log:['查找公开同源版本'],gaps:['行业统计仍需补查']}}
 await page.route('**/api/desk/wiki/jobs/acquisition-fixture',route=>route.fulfill({json:record}))
 await page.route('**/api/desk/wiki/jobs/acquisition-fixture/resume',route=>route.fulfill({json:{id:'recovered-fixture'}}))
 await page.route('**/api/desk/wiki/jobs/recovered-fixture',route=>route.fulfill({json:{...record,id:'recovered-fixture'}}))
 await page.goto('/wiki?job=acquisition-fixture&company=PDD')
 const detail=page.locator('.ww-job-detail');await expect(detail).toContainText('已通过替代入口取得');await expect(detail).toContainText('等待人工采纳');await expect(detail).toContainText('需要配置联系信息');await expect(detail.getByRole('link',{name:'前往本机设置'})).toHaveAttribute('href','/settings')
 await detail.getByRole('row').filter({hasText:'监管原件'}).getByText('获取记录',{exact:true}).click();await expect(detail).toContainText('HTTP 200');await expect(detail).toContainText('1.8 秒')
 await detail.getByText('上次任务的失败记录（1）',{exact:true}).click();await expect(detail).toContainText('上次下载超时')
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.getByRole('button',{name:'继续补查',exact:true}).click();await expect(page).toHaveURL(/job=recovered-fixture/)
})

import {test,expect} from '@playwright/test'
test('Research report uses metrics and shared evidence; narrow desktop remains operable',async({page},testInfo)=>{
 await page.goto('/research')
 await page.getByRole('link',{name:/离线研究验收/}).click()
 await page.getByText('完整观点与审核交接',{exact:true}).click()
 await page.getByText('查看核验状态',{exact:true}).click()
 await expect(page.getByText('引用 / 数值完整性：已核验',{exact:true})).toBeVisible()
 await expect(page.getByRole('columnheader',{name:'原预测',exact:true})).toBeVisible()
 await page.getByRole('button',{name:'1 支持 / 0 反证',exact:true}).first().click()
 await expect(page.locator('.d-research-evidence blockquote')).toHaveCount(1)
 await expect(page.locator('.d-research-evidence blockquote')).toContainText('Investment')
 await page.screenshot({path:testInfo.outputPath('report-1440.png'),fullPage:true})
 await page.setViewportSize({width:1280,height:800})
 await expect(page.getByRole('link',{name:'下载报告 ↓'})).toBeVisible()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy()
 await page.screenshot({path:testInfo.outputPath('report-1280.png'),fullPage:true})
})
test('Bare attachment saves first, asks intent, and cancellation is persistent',async({page})=>{
 await page.goto('/research')
 await page.getByLabel('研究附件',{exact:true}).setInputFiles({name:'author-note.md',mimeType:'text/markdown',buffer:Buffer.from('PDD author opinion: investment could affect margins.')})
 await page.getByRole('button',{name:/开始研究/}).click()
 await expect(page.getByText('希望我如何处理这些材料？',{exact:true})).toBeVisible()
 await expect(page.getByLabel('澄清回答')).toBeVisible()
 await page.getByRole('button',{name:'取消研究',exact:true}).click()
 await expect(page.getByText('已停止',{exact:true})).toBeVisible()
 await page.reload()
 await expect(page.getByText('已停止',{exact:true})).toBeVisible()
})

test('Current report binds original pages, calculations and independent review; prose is not evidence',async({page,request})=>{
 const requests=await (await request.get('/api/desk/research/requests')).json()
 const fixture=requests.find((r:any)=>r.input.question==='离线界面验收：利润率变化核对')
 const report=await (await request.get('/api/desk/research/requests/'+fixture.id+'/report')).json()
 const claim=report.claims[0]
 claim.original_claim='作者预期盈利拐点';claim.original_evidence=[report.evidence[0].id];report.evidence[0].page=3
 claim.alternative='';claim.next_check='取得完整模型后复核估值假设。'
 claim.evidence=[] // Calculation dependencies still supply valid supporting originals.
 claim.counterevidence=['这段说明不是证据编号'];claim.counterevidence_notes='尚无独立反证。';claim.temporal_scope='subsequent'
 claim.calculations=[report.calculations[0].id];report.calculations[0].limitations=['共识原始快照尚未核实']
 report.verification.independent_review='passed';report.delivery={status:'partial',reason:'独立复核已完成，保留有依据的资料缺口'}
 report.reviews=[{id:'review_pending',verdict:'pass',summary:'新增依据仍待补齐。',findings:[],feedback:[{message:'新取得的原件尚未绑定到判断。'}]},{id:'review_a',verdict:'pass',summary:'关键页面已自行读取。',findings:[]}]
 await page.route('**/api/desk/research/requests/'+fixture.id+'/report',route=>route.fulfill({json:report}))
 await page.goto('/research/'+fixture.id)
 await page.getByText('完整观点与审核交接',{exact:true}).click()
 await page.getByText('查看核验状态',{exact:true}).click()
 await expect(page.getByText('独立复核：已通过',{exact:true})).toBeVisible()
 await expect(page.getByText('作者预期盈利拐点',{exact:true})).toBeVisible()
 await page.getByText('替代解释与后续检验',{exact:true}).first().click()
 await expect(page.getByText('取得完整模型后复核估值假设。',{exact:true}).last()).toBeVisible()
 await expect(page.getByText('第 3 页',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'1 支持 / 0 反证',exact:true}).first().click()
 await expect(page.locator('.d-research-evidence blockquote')).toContainText('Investment')
 await page.getByText('定量检查 · 1 项',{exact:true}).first().click()
 await expect(page.getByText('共识原始快照尚未核实',{exact:true}).first()).toBeVisible()
 await expect(page.getByText('后续信息：不能倒推报告发布时的因果解释',{exact:true})).toBeVisible()
 await page.getByText('独立复核记录 · 2 轮',{exact:true}).click()
 await expect(page.getByText('仍有待处理项',{exact:true})).toBeVisible()
 await expect(page.getByText('新取得的原件尚未绑定到判断。',{exact:true})).toBeVisible()
})

import {test, expect} from '@playwright/test'

test('focused navigation, settings, history and narrow layouts remain usable', async ({page}, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page).toHaveURL(/\/research$/)
  const nav = page.getByRole('navigation', {name: '主导航'})
  await expect(nav.getByRole('link')).toHaveCount(2)
  await expect(nav.getByRole('link', {name: '研究', exact: true})).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.d-nav-bottom').getByRole('link', {name: '本机设置'})).toBeVisible()
  await expect(page.locator('.d-top a:not([href="/settings"])')).toHaveCount(0)
  await page.screenshot({path: testInfo.outputPath('research-desktop.png'), fullPage: true})

  await nav.getByRole('link', {name: 'LLM Wiki'}).click()
  await expect(page).toHaveURL(/\/wiki$/)
  await expect(nav.getByRole('link', {name: 'LLM Wiki'})).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.d-top a:not([href="/settings"])')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/research$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/wiki$/)
  await page.screenshot({path: testInfo.outputPath('wiki-desktop.png'), fullPage: true})

  for (const path of ['/research', '/wiki']) {
    await page.setViewportSize({width: 390, height: 844})
    await page.goto(path)
    await expect(page.locator('h1').first()).toBeVisible()
    await expect(nav.getByRole('link', {name: '研究', exact: true})).toBeVisible()
    await expect(nav.getByRole('link', {name: 'LLM Wiki'})).toBeVisible()
    await expect(page.locator('.d-nav-bottom').getByRole('link', {name: '本机设置'})).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({path: testInfo.outputPath(path.slice(1) + '-phone.png'), fullPage: true})
  }
  await page.locator('.d-nav-bottom').getByRole('link', {name: '本机设置'}).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(page.locator('h1').first()).toBeVisible()
  for (const path of ['/workbench','/analyst','/thesis','/quant','/pm','/model']) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/research$/)
  }
  expect(errors).toEqual([])
})

test('research keeps Wiki handoff and model evidence while hiding other workspace actions', async ({page, request}) => {
  const records = await (await request.get('/api/desk/research/requests')).json()
  const fixture = records.find((r: any) => r.input.question === '离线界面验收：利润率变化核对')
  const report = await (await request.get('/api/desk/research/requests/' + fixture.id + '/report')).json()
  const claim = report.claims[0]
  claim.validation = 'integrity_checked'
  claim.evidence = [report.evidence[0].id]
  claim.alternative = '投入时点可能影响利润。'
  claim.next_check = '核对下一期投入与现金。'
  report.handoffs = [{claim_id: claim.id, kinds: ['wiki']}]
  report.calculations[0].dependencies.push('model_focus_fixture')
  report.calculations[0].metric = '保留模型计算依据'
  await page.route('**/api/desk/research/requests/' + fixture.id + '/report', route => route.fulfill({json: report}))
  let handoff: any
  await page.route('**/api/desk/research/requests/' + fixture.id + '/proposals', async route => {
    handoff = route.request().postDataJSON()
    await route.fulfill({json: {id: 'focus-wiki-proposal'}})
  })
  await page.goto('/research/' + fixture.id)
  await page.getByText('完整观点与审核交接',{exact:true}).click()
  await expect(page.getByRole('button', {name: '论点提案', exact: true})).toHaveCount(0)
  await expect(page.getByRole('button', {name: '生成模型待审提案'})).toHaveCount(0)
  await expect(page.getByRole('link', {name: '打开预测模型 →'})).toHaveCount(0)
  await page.getByRole('button', {name: 'Wiki 提案', exact: true}).first().click()
  await expect(page.getByRole('status')).toContainText('已生成待审变更')
  expect(handoff.kind).toBe('wiki')
  expect(handoff.claim_id).toBe(claim.id)
  await page.getByText('计算与情景依赖', {exact: true}).click()
  await expect(page.getByText('保留模型计算依据', {exact: true})).toBeVisible()
  await page.getByRole('tab', {name: '执行流程', exact: true}).click()
  await expect(page).toHaveURL(/tab=flow/)
  await page.getByRole('tab', {name: 'Trace', exact: true}).click()
  await expect(page).toHaveURL(/tab=trace/)
})

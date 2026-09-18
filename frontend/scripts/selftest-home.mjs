import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'
import { mockRoutes } from './selftest-ui.mjs'

const baseUrl = process.env.MNEMOX_E2E_BASE_URL || 'http://127.0.0.1:5173'
const artifactDir = process.env.MNEMOX_E2E_ARTIFACT_DIR || 'output/homepage'
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
const chatQuestion = '用一个生活中的例子解释间隔复习。'
const chatAnswer = '间隔复习就像给植物浇水：把练习分散在几天里，比一次记很久更容易保持印象。\n\n例如，今天学会一个单词，明天先试着回忆，三天后再练习一次。每次先回忆，再核对答案。\n\n你可以试着用自己的话解释：为什么“先回忆”比直接重读更有帮助？'

// Synthetic learning data. Every API request is intercepted by this and the shared fixture.
const dashboard = {
  today: '2026-09-11', today_task_count: 3, today_completed_count: 1, today_pending_count: 2,
  due_review_count: 4, today_pomodoro_count: 2, today_study_minutes: 50,
  today_mission: {
    kind: 'review', title: '复习昨天的高频错词',
    reason: '根据昨天的错题与到期复习记录，先巩固容易混淆的词，再开始今天的阅读练习。',
    cta: '开始复习', route: '/review', estimated_minutes: 15,
    active_recall_prompt: '不看笔记，试着解释 affect 和 effect 的区别，并分别造一个句子。',
  },
  today_tasks: [
    { id: 1, title: '复习昨天的高频错词', status: 'in_progress', task_type: 'review' },
    { id: 2, title: '完成一篇英语阅读', status: 'pending', task_type: 'practice' },
    { id: 3, title: '整理第三章的学习笔记', status: 'completed', task_type: 'output' },
  ],
  recommended_actions: [],
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'light' })
const errors = []
const results = []
let dashboardMode = 'ready'
page.on('pageerror', error => errors.push(String(error)))

async function setupPage(page) {
  await mockRoutes(page)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/learning/dashboard') {
      if (dashboardMode === 'error') return route.fulfill(json({ detail: 'fixture unavailable' }, 503))
      return route.fulfill(json(dashboardMode === 'empty' ? { today_tasks: [], recommended_actions: [] } : dashboard))
    }
    if (['/api/materials/', '/api/wrong-questions/', '/api/review/tasks'].includes(path)) return route.fulfill(json([]))
    if (path === '/api/review/due-count') return route.fulfill(json({ due_count: 4 }))
    if (path === '/api/rag/health') return route.fulfill(json({ enabled: true, rag_online: true, embedding_enabled: true, total_chunks: 36 }))
    if (path === '/api/chat/send') return route.fulfill({
      status: 200, contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ content: chatAnswer })}\n\ndata: [DONE]\n\n`,
    })
    return route.fallback()
  })
  await page.addInitScript(() => {
    localStorage.setItem('study_assistant_token', 'selftest-token')
    localStorage.setItem('theme_mode', 'system')
  })
}

try {
  await setupPage(page)
  const goHome = async () => {
    await page.goto(baseUrl, { waitUntil: 'networkidle' })
    await page.locator('.mnemox-next-step[aria-busy="false"]').waitFor()
  }
  const noOverflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await goHome()
  // Native and library controls must share the same neutral hierarchy.
  assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)')
  const primary = page.getByRole('button', { name: '开始复习', exact: true })
  const primaryColors = await primary.evaluate(el => ({ bg: getComputedStyle(el).backgroundColor, fg: getComputedStyle(el).color }))
  assert.deepEqual(primaryColors, { bg: 'rgb(33, 33, 33)', fg: 'rgb(255, 255, 255)' })
  assert.equal(await page.locator('.mnemox-new-chat-button').evaluate(el => el.classList.contains('ant-btn-primary')), false)
  assert.equal(await page.getByRole('button', { name: '发送', exact: true }).isDisabled(), true)
  await primary.hover()
  await page.waitForTimeout(220)
  const hoverColor = await primary.evaluate(el => getComputedStyle(el).backgroundColor)
  assert.equal(hoverColor, 'rgb(58, 58, 58)')
  await page.locator('h1').hover()
  results.push('neutral-theme-and-button-states')
  assert.equal(await page.locator('#home-today').evaluate(el => Math.round(el.getBoundingClientRect().width)), 304)
  const recall = page.getByRole('button', { name: '开始前，先想一想' })
  await recall.focus()
  await page.keyboard.press('Enter')
  assert.equal(await recall.getAttribute('aria-expanded'), 'true')
  // Reverse an in-flight transition. Closed content must be inert immediately.
  await recall.click({ force: true })
  assert.equal(await page.locator('.mnemox-recall-panel .mnemox-fold-grid').evaluate(el => el.inert), true)
  await page.locator('.mnemox-prompt-chip').filter({ hasText: '费曼解释' }).click()
  assert.equal(await page.locator('#mnemox-chat-input').inputValue(), '费曼解释')
  assert.equal(await page.locator('#mnemox-chat-input').evaluate(el => el === document.activeElement), true)
  await page.locator('#mnemox-chat-input').fill('')
  results.push('keyboard-disclosure-and-prompt-focus')

  const currentPanel = page.locator('#home-today .mnemox-fold-panel').filter({ hasText: '今日任务' }).first()
  await currentPanel.locator('.mnemox-fold-trigger').click()
  assert.equal(await currentPanel.locator('.mnemox-fold-grid').evaluate(el => el.inert), true)
  await goHome()
  assert.equal(await currentPanel.locator('.mnemox-fold-trigger').getAttribute('aria-expanded'), 'false')
  await currentPanel.locator('.mnemox-fold-trigger').click()
  results.push('panel-state-persists-across-reload')

  // Calendar can be enabled and folded independently; customization is dismissible.
  await page.getByRole('button', { name: '自定义面板' }).click()
  const calendarOption = page.locator('.mnemox-widget-options > div').filter({ hasText: '今天与计划' })
  await calendarOption.getByRole('switch').click()
  await page.locator('h1').click()
  await page.locator('.ant-popover:not(.ant-popover-hidden)').waitFor({ state: 'hidden' })
  const calendar = page.locator('#home-today .mnemox-fold-panel').filter({ has: page.locator('.compact-calendar') })
  await calendar.locator('.mnemox-fold-trigger').click()
  assert.equal(await calendar.locator('.mnemox-fold-trigger').getAttribute('aria-expanded'), 'true')
  await calendar.locator('.mnemox-fold-trigger').click()
  await page.getByRole('button', { name: '自定义面板' }).click()
  await calendarOption.getByRole('switch').click()
  await page.locator('h1').click()
  results.push('calendar-and-widget-customization')

  // A collapsed sidebar remains mounted but cannot receive keyboard focus.
  await page.getByRole('button', { name: '收起今日安排' }).click()
  assert.equal(await page.locator('.mnemox-right-sidebar-content').evaluate(el => el.inert), true)
  await page.getByRole('button', { name: '展开今日安排' }).click()
  results.push('sidebar-keyboard-isolation')

  // Full collapse frees all sidebar space; immersion preserves independent preferences.
  await page.getByRole('button', { name: '收起对话与资料' }).click()
  await page.waitForFunction(() => document.querySelector('#home-conversations').getBoundingClientRect().width === 0)
  assert.equal(await page.locator('#home-conversations').evaluate(el => el.inert), true)
  const layoutPreferences = () => page.evaluate(() => ['layout_left_collapsed', 'layout_right_collapsed', 'layout_left_width', 'layout_right_width'].map(key => localStorage.getItem(key)))
  const savedLayout = await layoutPreferences()
  const input = page.locator('#mnemox-chat-input')
  await input.fill('保留这段还没有发送的学习问题')
  await page.getByRole('button', { name: '进入沉浸模式' }).focus()
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.mnemox-main-layout')).marginLeft === '0px')
  assert.equal(await page.locator('.mnemox-home-navigation').evaluate(el => el.inert), true)
  assert.equal(await page.locator('.mnemox-right-sidebar-content').evaluate(el => el.inert), true)
  assert.equal(await input.inputValue(), '保留这段还没有发送的学习问题')
  assert.equal(await page.locator('.mnemox-home-welcome').count(), 0)
  assert.deepEqual(await layoutPreferences(), savedLayout)
  // A picker consumes Escape without leaving immersion.
  await page.getByRole('combobox', { name: '聊天模型' }).focus()
  await page.keyboard.press('ArrowDown')
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').waitFor()
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('button', { name: '退出沉浸模式' }).getAttribute('aria-pressed'), 'true')
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').waitFor({ state: 'hidden' })
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('button', { name: '进入沉浸模式' }).evaluate(el => el === document.activeElement), true)
  assert.equal(await page.getByRole('button', { name: '展开对话与资料' }).getAttribute('aria-expanded'), 'false')
  assert.equal(await page.getByRole('button', { name: '收起今日安排' }).getAttribute('aria-expanded'), 'true')
  assert.equal(await input.inputValue(), '保留这段还没有发送的学习问题')
  await input.fill('')
  await page.getByRole('button', { name: '进入沉浸模式' }).click()
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '退出沉浸模式' }).waitFor()
  assert.equal(await page.locator('.mnemox-home-navigation').evaluate(el => el.inert), true)
  await page.getByRole('button', { name: '退出沉浸模式' }).click()
  await page.getByRole('button', { name: '展开对话与资料' }).click()
  results.push('complete-collapse-immersion-and-preference-restore')

  await page.setViewportSize({ width: 390, height: 844 })
  await noOverflow()
  const desktopPreference = await page.evaluate(() => localStorage.getItem('layout_right_collapsed'))
  await page.getByRole('button', { name: '展开今日安排' }).click()
  assert.equal(await page.locator('.mnemox-right-sidebar-content').evaluate(el => el.inert), false)
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('button', { name: '展开今日安排' }).getAttribute('aria-expanded'), 'false')
  assert.equal(await page.evaluate(() => localStorage.getItem('layout_right_collapsed')), desktopPreference)
  await page.getByRole('button', { name: '展开对话与资料' }).click()
  await page.getByRole('button', { name: '进入沉浸模式' }).click()
  assert.equal(await page.locator('.mnemox-panel-backdrop').count(), 0)
  assert.equal(await page.locator('#home-conversations').evaluate(el => el.inert), true)
  await page.waitForFunction(() => document.querySelector('.mnemox-main-layout').getBoundingClientRect().width === innerWidth)
  await noOverflow()
  await page.getByRole('button', { name: '退出沉浸模式' }).click()
  assert.equal(await page.getByRole('button', { name: '展开对话与资料' }).getAttribute('aria-expanded'), 'false')
  await noOverflow()
  results.push('mobile-drawers-and-desktop-preferences')

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await recall.click()
  assert.equal(await page.locator('.mnemox-recall-panel .mnemox-fold-grid').evaluate(el => getComputedStyle(el).transitionDuration), '0s')
  assert.equal(await page.locator('.mnemox-click-spark-canvas').evaluate(el => getComputedStyle(el).display), 'none')
  await recall.click()
  await page.getByRole('button', { name: '进入沉浸模式' }).click()
  for (const selector of ['.mnemox-left-sidebar', '.mnemox-right-sidebar', '.mnemox-main-layout']) {
    assert.deepEqual(await page.locator(selector).evaluate(el => ({ duration: getComputedStyle(el).transitionDuration, delay: getComputedStyle(el).transitionDelay })), { duration: '0s', delay: '0s' })
  }
  await page.getByRole('button', { name: '退出沉浸模式' }).click()
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  results.push('reduced-motion')

  // Fresh contexts give each capture its actual viewport and theme from first paint.
  if (process.env.MNEMOX_HOME_CAPTURE !== '0') {
    await mkdir(artifactDir, { recursive: true })
    for (const [name, width, height, colorScheme, panel, immersiveCapture] of [
      ['desktop-light', 1440, 1000, 'light', false],
      ['desktop-dark', 1440, 1000, 'dark', false],
      ['mobile', 390, 844, 'light', false],
      ['mobile-panel', 390, 844, 'light', true],
      ['immersive-desktop', 1440, 1000, 'light', false, 'chat'],
      ['immersive-mobile', 390, 844, 'light', false, 'chat'],
      ['immersive-empty', 1440, 1000, 'light', false, 'empty'],
    ]) {
      const capture = await browser.newPage({ viewport: { width, height }, colorScheme, reducedMotion: 'reduce' })
      await setupPage(capture)
      await capture.goto(baseUrl, { waitUntil: 'networkidle' })
      await capture.locator('.mnemox-next-step[aria-busy="false"]').waitFor()
      await capture.evaluate(() => document.fonts.ready)
      if (panel) await capture.getByRole('button', { name: '展开今日安排' }).click()
      if (immersiveCapture) await capture.getByRole('button', { name: '进入沉浸模式' }).click()
      if (immersiveCapture === 'chat') {
        await capture.locator('#mnemox-chat-input').fill(chatQuestion)
        await capture.getByRole('button', { name: '发送', exact: true }).click()
        await capture.locator('.msg-bubble-assistant').filter({ hasText: '间隔复习就像给植物浇水' }).waitFor()
        await capture.locator('#mnemox-chat-input').fill('所以，我可以先合上笔记试着回忆，对吗？')
        // Switching mode must keep the mounted conversation and unsent draft intact.
        const conversationUrl = capture.url()
        await capture.locator('.msg-bubble-assistant').evaluate(el => { el.dataset.immersionCheck = 'mounted' })
        await capture.getByRole('button', { name: '退出沉浸模式' }).click()
        await capture.getByRole('button', { name: '进入沉浸模式' }).click()
        assert.equal(capture.url(), conversationUrl)
        assert.equal(await capture.locator('.msg-bubble-assistant').getAttribute('data-immersion-check'), 'mounted')
        assert.equal(await capture.locator('#mnemox-chat-input').inputValue(), '所以，我可以先合上笔记试着回忆，对吗？')
        assert.equal(await capture.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      }
      // Wait for ResizeObserver-driven textarea autosizing after fonts settle.
      await capture.waitForTimeout(200)
      await capture.screenshot({ path: `${artifactDir}/${name}.png`, fullPage: true })
      await capture.close()
    }
  }

  // Route and empty/error paths are checked after captures to keep the visual pass bounded.
  await page.getByRole('button', { name: '开始复习', exact: true }).click()
  await page.waitForURL('**/review')
  dashboardMode = 'error'
  await goHome()
  await page.getByRole('heading', { name: '学习安排暂时未能加载' }).waitFor()
  dashboardMode = 'ready'
  await page.getByRole('button', { name: '重新加载' }).click()
  await page.getByRole('heading', { name: dashboard.today_mission.title }).waitFor()
  dashboardMode = 'empty'
  await goHome()
  await page.getByRole('button', { name: '导入资料', exact: true }).click()
  assert.equal(await page.getByRole('button', { name: '收起对话与资料' }).getAttribute('aria-expanded'), 'true')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '安排今天的学习', exact: true }).click()
  await page.waitForURL('**/plans?date=*')
  results.push('mission-route-error-retry-and-first-use')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, results, artifactDir }, null, 2))
} finally {
  await browser.close()
}

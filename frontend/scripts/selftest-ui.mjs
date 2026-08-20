import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const BASE_URL = process.env.MNEMOX_E2E_BASE_URL || 'http://127.0.0.1:5173'
const ARTIFACT_DIR = process.env.MNEMOX_E2E_ARTIFACT_DIR || 'output/playwright'

const today = '2026-06-02'
const yesterday = '2026-06-01'

const plans = {
  [today]: '# 2026-06-02\n\n- [ ] 优化 Mnemox 右侧今日任务\n- [x] 番茄工作法做独立页面\n\n今晚复盘：把计划页改成文档工作台。',
  [yesterday]: '# 2026-06-01\n\n- [ ] 复习错题\n- [ ] 梳理笔记结构',
}

const notes = [
  {
    _localId: 'note-1',
    _serverId: null,
    _syncStatus: 'synced',
    title: 'AI 科研',
    content: '# AI 科研\n\n记录实验方案。',
    note_type: 'general',
    material_id: null,
    chapter_id: null,
    tags: JSON.stringify(['科研', '项目']),
    links: '[]',
    created_at: '2026-06-02T08:00:00.000Z',
    _updatedAt: '2026-06-02T08:00:00.000Z',
  },
  {
    _localId: 'note-2',
    _serverId: null,
    _syncStatus: 'pending_update',
    title: '临时想法',
    content: '一个还没分类的记录。',
    note_type: 'general',
    material_id: null,
    chapter_id: null,
    tags: JSON.stringify([]),
    links: '[]',
    created_at: '2026-06-01T08:00:00.000Z',
    _updatedAt: '2026-06-01T08:00:00.000Z',
  },
]

function json(body, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }
}

async function seedOfflineNotes(page) {
  await page.addInitScript((seedNotes) => {
    localStorage.setItem('study_assistant_token', 'selftest-token')
    const dbName = 'StudyAssistantDB'
    const request = indexedDB.open(dbName)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('notes')) {
        db.createObjectStore('notes', { keyPath: '_localId' })
      }
      if (!db.objectStoreNames.contains('syncQueue')) {
        db.createObjectStore('syncQueue', { keyPath: 'id', autoIncrement: true })
      }
    }
    request.onsuccess = () => {
      const db = request.result
      const tx = db.transaction(['notes'], 'readwrite')
      const store = tx.objectStore('notes')
      store.clear()
      for (const note of seedNotes) {
        store.put(note)
      }
    }
  }, notes)
}

async function mockRoutes(page) {
  const state = {
    agentExecuteCount: 0,
    nextConversationId: 41,
    conversations: [],
    messagesByConversation: new Map(),
  }

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const { pathname, searchParams } = url
    const method = request.method()

    if (pathname === '/api/auth/me') {
      await route.fulfill(json({
        id: 1,
        username: 'selftest',
        email: 'selftest@example.com',
        is_active: true,
        created_at: '2026-06-01T00:00:00.000Z',
      }))
      return
    }

    if (pathname === '/api/motivation/current') {
      await route.fulfill(json({
        id: 1,
        content: '如果一个人不知道他要驶向哪个码头，那么任何风都不会是顺风。',
        author: '塞涅卡',
        source_type: 'preset',
        created_at: null,
      }))
      return
    }

    if (pathname === '/api/pomodoro/recent') {
      await route.fulfill(json([]))
      return
    }

    if (pathname === '/api/pomodoro/start' || pathname === '/api/pomodoro/batch' || pathname.includes('/api/pomodoro/') || pathname === '/api/pomodoro') {
      await route.fulfill(json({ id: 1, completed: true, duration: 25, task_name: '测试任务', task_id: null, ended_at: new Date().toISOString() }))
      return
    }

    if (pathname === '/api/plans/' && method === 'GET') {
      const start = searchParams.get('start') || '0000-00-00'
      const end = searchParams.get('end') || '9999-99-99'
      const list = Object.entries(plans)
        .filter(([date]) => date >= start && date <= end)
        .map(([date, content]) => ({ date, content }))
      await route.fulfill(json(list))
      return
    }

    const planMatch = pathname.match(/^\/api\/plans\/(\d{4}-\d{2}-\d{2})$/)
    if (planMatch && method === 'PUT') {
      const date = planMatch[1]
      const payload = JSON.parse(request.postData() || '{}')
      plans[date] = payload.content || ''
      await route.fulfill(json({ date, content: plans[date] }))
      return
    }

    if (pathname === `/api/plans/generate/${today}` && method === 'POST') {
      plans[today] = '# 2026-06-02\n\n- [ ] AI 生成的第一项任务\n- [ ] AI 生成的第二项任务'
      await route.fulfill(json({
        date: today,
        content: plans[today],
        item_count: 2,
        items: [
          { type: 'task', emoji: '📝', label: 'AI 生成的第一项任务', priority: 1, id: 1 },
          { type: 'task', emoji: '📝', label: 'AI 生成的第二项任务', priority: 1, id: 2 },
        ],
      }))
      return
    }

    const probeMatch = pathname.match(/^\/api\/plans\/(\d{4}-\d{2}-\d{2})\/feynman-probe$/)
    if (probeMatch && method === 'POST') {
      await route.fulfill(json({
        name: '明镜追问',
        tagline: '从小白视角追问你是否真的讲清楚了',
        date: probeMatch[1],
        source_excerpt: '',
        strongest_part: '任务拆分比较清楚',
        questions: [
          { type: '概念', question: '为什么今天先做这个任务？', why: '检查优先级理解' },
        ],
        next_focus: '补一段关于选择依据的解释。',
        fallback: false,
      }))
      return
    }

    if (pathname === '/api/learning/dashboard') {
      await route.fulfill(json({
        today_tasks: [
          { title: '优化 Mnemox 右侧今日任务', status: 'in_progress', task_type: 'plan', priority: 'high' },
        ],
        today_minutes: 90,
        week_minutes: 320,
      }))
      return
    }

    if (pathname === '/api/system/onboarding-status') {
      await route.fulfill(json({
        has_content: true,
        demo_seeded: true,
        auto_show_seen: true,
        counts: { materials: 1, goals: 1, notes: 1, pomodoros: 1 },
        suggested_next_steps: [],
        stage: 'loop_ready',
        stage_label: '已完成引导',
        completed_steps: ['materials', 'plan', 'review'],
      }))
      return
    }

    if (pathname === '/api/system/onboarding-dismissed' || pathname === '/api/system/demo-seed') {
      await route.fulfill(json({ ok: true, already_seeded: true, message: 'ok', created: {} }))
      return
    }

    if (pathname === '/api/rag/health' || pathname === '/api/wrong-questions/' || pathname === '/api/review/tasks' || pathname === '/api/review/due-count' || pathname === '/api/materials/' || pathname.startsWith('/api/materials/search') || pathname === '/api/motivation/quotes' || pathname === '/api/motivation/settings') {
      await route.fulfill(json(pathname === '/api/review/due-count' ? { due_count: 0 } : pathname === '/api/rag/health' ? { healthy: true } : []))
      return
    }

    if (pathname === '/api/goals/' || pathname === '/api/goals/tasks' || pathname === '/api/goals/tasks/daily') {
      await route.fulfill(json([]))
      return
    }

    if (pathname === '/api/agent/write/draft' && method === 'POST') {
      await route.fulfill(json({
        intent: 'create_note',
        confidence: 0.96,
        summary: '将创建一条可审核的验收笔记。',
        requires_confirmation: true,
        duplicate_warnings: [],
        draft: {
          title: 'Agent 草案确认验收',
          note_type: 'general',
          tags: ['验收'],
          content: '只有用户确认后才允许写入。',
        },
      }))
      return
    }

    if (pathname === '/api/agent/write/execute' && method === 'POST') {
      state.agentExecuteCount += 1
      await route.fulfill(json({
        status: 'completed',
        intent: 'create_note',
        created: { id: 99 },
        message: '已创建验收笔记',
      }))
      return
    }

    if (pathname === '/api/conversations') {
      if (method === 'POST') {
        const payload = JSON.parse(request.postData() || '{}')
        const conversation = {
          id: state.nextConversationId++,
          title: payload.title || '新对话',
          project_id: payload.project_id ?? null,
          is_pinned: false,
          summary: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        state.conversations.unshift(conversation)
        state.messagesByConversation.set(conversation.id, [])
        await route.fulfill(json(conversation))
      } else {
        await route.fulfill(json(state.conversations))
      }
      return
    }

    const conversationMessagesMatch = pathname.match(/^\/api\/conversations\/(\d+)\/messages$/)
    if (conversationMessagesMatch && method === 'POST') {
      const conversationId = Number(conversationMessagesMatch[1])
      const payload = JSON.parse(request.postData() || '{}')
      const existing = state.messagesByConversation.get(conversationId) || []
      const created = (payload.messages || []).map((message, index) => ({
        id: existing.length + index + 1,
        role: message.role,
        content: message.content,
        image_data: message.image_data || null,
        created_at: new Date().toISOString(),
      }))
      state.messagesByConversation.set(conversationId, [...existing, ...created])
      await route.fulfill(json({ messages: created }))
      return
    }

    const conversationMatch = pathname.match(/^\/api\/conversations\/(\d+)$/)
    if (conversationMatch && method === 'GET') {
      const conversationId = Number(conversationMatch[1])
      const conversation = state.conversations.find(item => item.id === conversationId)
      if (!conversation) {
        await route.fulfill(json({ detail: 'not found' }, 404))
        return
      }
      await route.fulfill(json({
        ...conversation,
        messages: state.messagesByConversation.get(conversationId) || [],
      }))
      return
    }

    if (pathname === '/api/chat-projects' || pathname.startsWith('/api/chat-projects/')) {
      await route.fulfill(json([]))
      return
    }

    if (pathname === '/api/system/version' || pathname === '/api/system/check-update') {
      await route.fulfill(json({}))
      return
    }

    if (pathname === '/api/ai-settings/providers' || pathname === '/api/ai-settings/routing' || pathname === '/api/rag/settings') {
      await route.fulfill(json([]))
      return
    }

    await route.fulfill(json({ ok: true }))
  })

  await page.route('**/health', async (route) => {
    await route.fulfill({ status: 200, body: 'ok' })
  })

  return {
    getAgentExecuteCount: () => state.agentExecuteCount,
  }
}

async function assertText(locator, expected) {
  const text = await locator.textContent()
  if (!text || !text.includes(expected)) {
    throw new Error(`Expected text "${expected}", got "${text}"`)
  }
}

async function run() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  try {
    await page.clock.setFixedTime(new Date(`${today}T12:00:00.000Z`))
    await seedOfflineNotes(page)
    const mockState = await mockRoutes(page)
    const results = []

    await page.goto(`${BASE_URL}/pomodoro`, { waitUntil: 'networkidle' })
    await assertText(page.locator('.mnemox-pomodoro-quote'), '如果一个人不知道他要驶向哪个码头')
    await page.getByPlaceholder('临时专注任务').fill('自测番茄')
    await page.getByRole('button', { name: '开始专注' }).click()
    await assertText(page.locator('.mnemox-pomodoro-task'), '自测番茄')
    results.push('pomodoro-page-ok')

    await page.goto(`${BASE_URL}/plans?date=${today}`, { waitUntil: 'networkidle' })
    await assertText(page.locator('.mnemox-doc-header'), today)
    await assertText(page.locator('.mnemox-task-list'), '优化 Mnemox 右侧今日任务')
    await page.locator('.mnemox-doc-toolbar').getByRole('button', { name: 'AI 生成' }).click()
    await assertText(page.locator('.mnemox-task-list'), 'AI 生成的第一项任务')
    results.push('plans-workbench-ok')

    await page.goto(`${BASE_URL}/notes`, { waitUntil: 'networkidle' })
    await assertText(page.locator('.mnemox-folder-list'), '全部笔记')
    await assertText(page.locator('.mnemox-file-list'), 'AI 科研')
    await page.getByRole('button', { name: '未分类 1' }).click()
    await assertText(page.locator('.mnemox-file-list'), '临时想法')
    await page.getByRole('button', { name: '项目 1' }).click()
    await assertText(page.locator('.mnemox-file-list'), 'AI 科研')
    results.push('notes-workbench-ok')

    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' })
    await assertText(page.locator('.mnemox-right-sidebar-content'), '今日任务')
    await assertText(page.locator('.mnemox-right-sidebar-content'), '优化 Mnemox 右侧今日任务')
    await page.locator('button').filter({ hasText: '编辑' }).first().click()
    await page.waitForURL(`**/plans?date=${today}`)
    results.push('sidebar-task-link-ok')

    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' })
    const composer = page.getByPlaceholder('输入问题，或让 AI 基于当前资料生成计划...')
    await composer.fill('帮我记个笔记：验收草案')
    await page.getByRole('button', { name: '发送' }).click()
    let confirmation = page.locator('.ant-modal').filter({ hasText: '确认创建笔记' })
    await confirmation.waitFor()
    await assertText(confirmation, '只有用户确认后才允许写入。')
    if (mockState.getAgentExecuteCount() !== 0) {
      throw new Error('Agent execute endpoint was called before confirmation')
    }
    await confirmation.getByRole('button', { name: /取\s*消/ }).click()
    await confirmation.waitFor({ state: 'hidden' })
    if (mockState.getAgentExecuteCount() !== 0) {
      throw new Error('Cancelling an Agent draft caused a write side effect')
    }

    await composer.fill('帮我记个笔记：验收草案')
    await page.getByRole('button', { name: '发送' }).click()
    confirmation = page.locator('.ant-modal').filter({ hasText: '确认创建笔记' })
    await confirmation.waitFor()
    if (mockState.getAgentExecuteCount() !== 0) {
      throw new Error('Agent execute endpoint was called while the draft was pending')
    }
    const executeResponse = page.waitForResponse(response => (
      new URL(response.url()).pathname === '/api/agent/write/execute'
      && response.request().method() === 'POST'
    ))
    await confirmation.getByRole('button', { name: '确认写入' }).click()
    await executeResponse
    await confirmation.waitFor({ state: 'hidden' })
    if (mockState.getAgentExecuteCount() !== 1) {
      throw new Error(`Expected exactly one confirmed Agent write, got ${mockState.getAgentExecuteCount()}`)
    }
    await assertText(page.locator('.ant-message-notice-content').last(), '已创建验收笔记')
    results.push('agent-draft-confirmation-ok')

    console.log(JSON.stringify({ ok: true, results }, null, 2))
  } catch (error) {
    await mkdir(ARTIFACT_DIR, { recursive: true })
    await page.screenshot({
      path: `${ARTIFACT_DIR}/browser-acceptance-failure.png`,
      fullPage: true,
    })
    throw error
  } finally {
    await browser.close()
  }
}

run().catch(async (error) => {
  console.error(JSON.stringify({ ok: false, error: String(error) }, null, 2))
  process.exitCode = 1
})

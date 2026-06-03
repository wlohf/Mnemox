import { createRequire } from 'module'

const require = createRequire(import.meta.url)
const { chromium } = require('C:/Users/xyleisure/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.60.0/node_modules/playwright')

const BASE_URL = 'http://127.0.0.1:5173'

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

    if (pathname === '/api/conversations' || pathname === '/api/chat-projects' || pathname.startsWith('/api/conversations/') || pathname.startsWith('/api/chat-projects/')) {
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
  await seedOfflineNotes(page)
  await mockRoutes(page)

  const results = []

  await page.goto(`${BASE_URL}/pomodoro`, { waitUntil: 'networkidle' })
  await assertText(page.locator('.mnemox-pomodoro-quote'), '如果一个人不知道他要驶向哪个码头')
  await page.getByPlaceholder('本轮专注任务').fill('自测番茄')
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

  console.log(JSON.stringify({ ok: true, results }, null, 2))
  await browser.close()
}

run().catch(async (error) => {
  console.error(JSON.stringify({ ok: false, error: String(error) }, null, 2))
  process.exitCode = 1
})

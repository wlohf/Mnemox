// Static mock data for the home prototype. Shapes loosely mirror the real APIs
// (goals, review queue, evidence sources, agent drafts) so wiring is direct later.

export type SourceKind = 'wrong' | 'review' | 'note' | 'memory' | 'material'

export interface EvidenceSource {
  id: number
  kind: SourceKind
  title: string
  meta: string
  excerpt: string
  highlight?: string
}

export const goal = {
  title: '考研数学一 · 线性代数',
  progress: 0.62,
  daysLeft: 87,
  weekMinutes: 412,
  weekTarget: 600,
}

export const nextAction = {
  title: '先把「相似对角化」补稳，再清今天的到期卡片',
  steps: [
    { label: '重做 2 道相似对角化错题', minutes: 20, cite: [1] },
    { label: '复习「特征值与特征向量」12 张到期卡片', minutes: 15, cite: [2] },
    { label: '用费曼法口述一次判定条件', minutes: 10, cite: [3] },
  ],
  reason: '这个知识点过去两周错了 3 次，保持率掉到 71%，而下周的计划要用到它。晚上 8 点后你做推导题的完成率最高。',
  reasonCites: [1, 2, 4],
}

export const sources: EvidenceSource[] = [
  {
    id: 1,
    kind: 'wrong',
    title: '错题本 · 相似对角化判定',
    meta: '3 次错误 · 最近 9月21日',
    excerpt: '误把「有 n 个不同特征值」当作可对角化的必要条件，忽略了重根时几何重数等于代数重数的情形。',
    highlight: '几何重数等于代数重数',
  },
  {
    id: 2,
    kind: 'review',
    title: 'FSRS 复习队列 · 第五章',
    meta: '12 张到期 · 预测保持率 71%',
    excerpt: '其中 5 张已逾期超过 2 天，最难的一张是「实对称矩阵正交相似对角化的步骤」。',
    highlight: '5 张已逾期',
  },
  {
    id: 3,
    kind: 'note',
    title: '笔记《第五章 特征值与特征向量》',
    meta: '你在 9月18日 编辑',
    excerpt: 'A 可对角化 ⇔ A 有 n 个线性无关的特征向量 ⇔ 每个特征值的几何重数等于代数重数。',
    highlight: '⇔ 每个特征值的几何重数等于代数重数',
  },
  {
    id: 4,
    kind: 'memory',
    title: '长期记忆 · 学习时段偏好',
    meta: '由 34 次番茄记录推断 · 已确认',
    excerpt: '晚上 20:00–22:00 推导类任务完成率 86%，明显高于下午的 58%。',
    highlight: '86%',
  },
]

export type QueueKind = 'review' | 'wrong' | 'task' | 'focus'

export interface QueueItem {
  id: string
  kind: QueueKind
  title: string
  detail: string
  time?: string
  done?: boolean
}

export const queue: QueueItem[] = [
  { id: 'q1', kind: 'focus', title: '上午专注 · 高数极限综合题', detail: '2 个番茄 · 50 分钟', time: '09:10', done: true },
  { id: 'q2', kind: 'task', title: '整理「第四章 线性方程组」笔记', detail: '学习计划 · 第 3 周', time: '14:00', done: true },
  { id: 'q3', kind: 'wrong', title: '错题重做 · 相似对角化', detail: '2 道 · 预计 20 分钟', time: '20:00' },
  { id: 'q4', kind: 'review', title: '到期复习 · 第五章卡片', detail: '12 张 · 5 张逾期', time: '20:25' },
  { id: 'q5', kind: 'task', title: '真题 2019 · 第 20 题', detail: '学习计划 · 第 3 周', time: '21:00' },
]

export const stats = [
  { key: 'focus', label: '今日专注', value: 50, unit: '分钟', delta: '目标 120' },
  { key: 'retention', label: '复习保持率', value: 91, unit: '%', delta: '较上周 +3' },
  { key: 'week', label: '本周学习', value: 5, unit: '/ 7 天', delta: '6 小时 52 分' },
]

export const mastery = [
  { chapter: '行列式', topics: [5, 5, 4, 5] },
  { chapter: '矩阵', topics: [4, 5, 4, 3, 4] },
  { chapter: '向量组', topics: [3, 4, 3, 4] },
  { chapter: '线性方程组', topics: [4, 3, 4] },
  { chapter: '特征值', topics: [3, 2, 1, 2] },
  { chapter: '二次型', topics: [1, 1, 0, 0] },
]

export interface Draft {
  id: string
  kind: '任务' | '笔记' | '记忆'
  title: string
  body: string
  cite: number[]
}

export const drafts: Draft[] = [
  {
    id: 'd1',
    kind: '任务',
    title: '周四加一节「重根情形」专项练习',
    body: '45 分钟，选 4 道含重根特征值的判定题，放在周四 20:00。',
    cite: [1, 4],
  },
  {
    id: 'd2',
    kind: '记忆',
    title: '记住：你更习惯先看例题再看定理',
    body: '来自最近 6 次对话中你的主动要求，确认后教练讲解会先给例子。',
    cite: [],
  },
]

export const recentChats = [
  '为什么实对称矩阵一定能正交对角化',
  '帮我把第四章错题归类',
  '这周计划是不是排得太满',
]

export const userName = 'Kin'

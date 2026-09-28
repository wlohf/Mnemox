import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Check, Compass, Library, Sparkles } from 'lucide-react'
import { Button, Dialog, toast } from '../../ui'
import { getOnboardingStatus, seedDemoWorkspace } from '../../services/systemApi'
import { qk } from '../../app/queryClient'
import { useShell } from '../../app/shell/shellStore'
import s from './onboarding.module.css'

const LOOP = [
  { key: '资料', title: '放进一份资料', body: '上传 PDF / Word / Markdown，或从笔记开始。' },
  { key: '计划', title: '定下今天的一件事', body: '教练把目标拆成当天能完成的最小行动。' },
  { key: '专注', title: '专注一段时间', body: '番茄钟记录你的节奏，也记录走神的原因。' },
  { key: '复盘', title: '用自己的话讲一遍', body: '讲不顺的地方会变成明天的复习与卡片。' },
]

export function OnboardingDialog() {
  const open = useShell(st => st.onboardingOpen)
  const setOpen = useShell(st => st.setOnboardingOpen)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const status = useQuery({ queryKey: qk.onboarding, queryFn: getOnboardingStatus, staleTime: 30_000 })
  const [seeding, setSeeding] = useState(false)
  const done = new Set(status.data?.completed_steps ?? [])
  const counts = status.data?.counts ?? {}

  const close = () => setOpen(false)
  const go = (path: string) => {
    close()
    navigate(path)
  }

  const seed = async () => {
    setSeeding(true)
    try {
      const res = await seedDemoWorkspace()
      toast.success(res.already_seeded ? '示例数据已经在你的工作台里了' : '示例学习闭环已准备好', {
        description: '从「今天」开始，按复习、任务、专注、复盘的顺序走一遍。',
      })
      await qc.invalidateQueries()
      go('/today')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导入示例数据失败，请稍后重试')
    } finally {
      setSeeding(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      width={44}
      title={<span className="mx-serif">先跑通一个学习闭环</span>}
      description="Mnemox 不是一个聊天框。它把资料、计划、专注和复盘连起来，每条建议都能追溯到你自己的学习记录。"
    >
      <ol className={s.loop} role="list">
        {LOOP.map((step, i) => (
          <li key={step.key} className={s.step} data-done={isDone(step.key, done, counts) || undefined}>
            <span className={s.stepIdx} aria-hidden>
              {isDone(step.key, done, counts) ? <Check /> : i + 1}
            </span>
            <span className={s.stepText}>
              <span className={s.stepTitle}>{step.title}</span>
              <span className={s.stepBody}>{step.body}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className={s.paths}>
        <button type="button" className={s.path} data-primary onClick={() => void seed()} disabled={seeding}>
          <span className={s.pathIcon}>
            <Sparkles />
          </span>
          <span className={s.pathText}>
            <span className={s.pathTitle}>{seeding ? '正在准备示例…' : '用示例数据体验一遍'}</span>
            <span className={s.pathBody}>约 1 分钟。自动创建资料、目标、今日计划、错题、卡片和专注记录。</span>
          </span>
          <ArrowRight className={s.pathArrow} />
        </button>
        <button type="button" className={s.path} onClick={() => go('/materials?upload=1')}>
          <span className={s.pathIcon}>
            <Library />
          </span>
          <span className={s.pathText}>
            <span className={s.pathTitle}>从自己的资料开始</span>
            <span className={s.pathBody}>上传后可以生成大纲、目标和每日任务。</span>
          </span>
          <ArrowRight className={s.pathArrow} />
        </button>
        <button type="button" className={s.path} onClick={() => go('/today')}>
          <span className={s.pathIcon}>
            <Compass />
          </span>
          <span className={s.pathText}>
            <span className={s.pathTitle}>直接看今天该做什么</span>
            <span className={s.pathBody}>已有学习数据时，从今日建议和证据开始。</span>
          </span>
          <ArrowRight className={s.pathArrow} />
        </button>
      </div>

      <div className={s.foot}>
        <BookOpen aria-hidden />
        <span>
          费曼复述与苏格拉底追问已经融进日常流程：普通提问时教练会适度追问，每天的计划里固定留一段复盘。
        </span>
        <Button variant="ghost" size="sm" onClick={close}>
          稍后再说
        </Button>
      </div>
    </Dialog>
  )
}

function isDone(key: string, done: Set<string>, counts: Record<string, number>): boolean {
  if (key === '资料') return done.has('已有学习资料') || (counts.materials ?? 0) > 0
  if (key === '计划') return done.has('已有目标或任务') || (counts.goals ?? 0) > 0
  if (key === '专注') return done.has('完成过专注记录') || (counts.pomodoros ?? 0) > 0
  if (key === '复盘') return done.has('已有笔记或复盘') || (counts.notes ?? 0) > 0
  return false
}

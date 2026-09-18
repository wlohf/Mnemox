import { useRef } from 'react'
import { ArrowRightOutlined, BookOutlined, ClockCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import type { DashboardData } from '../../services/learningApi'
import { ActionButton } from '../ui/ActionButton'
import { FoldPanel } from '../ui/FoldPanel'

gsap.registerPlugin(useGSAP)

interface HomeWelcomeProps {
  dashboard: DashboardData | null
  status: 'loading' | 'ready' | 'error'
  onNavigate: (path: string) => void
  onOpenPlan: () => void
  onOpenMaterials: () => void
  onRetry: () => void
}

export function HomeWelcome({ dashboard, status, onNavigate, onOpenPlan, onOpenMaterials, onRetry }: HomeWelcomeProps) {
  const root = useRef<HTMLDivElement>(null)
  const mission = dashboard?.today_mission

  useGSAP(() => {
    const media = gsap.matchMedia()
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.timeline({ defaults: { ease: 'power3.out', clearProps: 'transform,opacity' } })
        .from('.mnemox-welcome-heading', { y: 12, opacity: 0, duration: 0.45 })
        .from('.mnemox-next-step', { y: 16, opacity: 0, duration: 0.4 }, 0.08)
    })
    return () => media.revert()
  }, { scope: root })

  return (
    <div ref={root} className="mnemox-home-welcome">
      <div className="mnemox-welcome-heading">
        <h1>今天，专注一件事。</h1>
        <p>从一个小行动开始，把学习慢慢变成积累。</p>
      </div>
      <section className="mnemox-next-step" aria-label="下一步学习" aria-busy={status === 'loading'}>
        {status === 'loading' ? (
          <div className="mnemox-mission-loading" role="status">
            <span className="mnemox-loading-line" />
            <span className="mnemox-loading-line is-short" />
            <span>正在整理你的学习安排…</span>
          </div>
        ) : status === 'error' ? (
          <>
            <h2>学习安排暂时未能加载</h2>
            <p>可以重试，也可以直接向教练提问。</p>
            <ActionButton icon={<ReloadOutlined aria-hidden />} onClick={onRetry}>重新加载</ActionButton>
          </>
        ) : mission ? (
          <>
            <div className="mnemox-mission-title">
              <h2>{mission.title}</h2>
              {mission.estimated_minutes > 0 && (
                <span className="mnemox-mission-duration"><ClockCircleOutlined />约 {mission.estimated_minutes} 分钟</span>
              )}
            </div>
            <p className="mnemox-mission-reason">{mission.reason}</p>
            <div className="mnemox-mission-actions">
              <ActionButton type="primary" size="large" onClick={() => onNavigate(mission.route)}>
                {mission.cta}<ArrowRightOutlined aria-hidden className="mnemox-action-arrow" />
              </ActionButton>
              <ActionButton type="text" onClick={onOpenPlan}>调整安排</ActionButton>
            </div>
            {mission.active_recall_prompt && (
              <FoldPanel title="开始前，先想一想" className="mnemox-recall-panel">
                <p>{mission.active_recall_prompt}</p>
              </FoldPanel>
            )}
          </>
        ) : (
          <>
            <h2>从今天想完成的事开始</h2>
            <p>写下一个学习目标，或导入正在读的资料，让教练陪你梳理下一步。</p>
            <div className="mnemox-mission-actions">
              <ActionButton type="primary" size="large" onClick={onOpenPlan}>
                安排今天的学习<ArrowRightOutlined aria-hidden className="mnemox-action-arrow" />
              </ActionButton>
              <ActionButton type="text" icon={<BookOutlined aria-hidden />} onClick={onOpenMaterials}>导入资料</ActionButton>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

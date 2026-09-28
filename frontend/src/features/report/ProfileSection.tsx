import type { CSSProperties } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { CircleX, Flame, Moon, RefreshCw, Sun, Sunrise, TrendingUp } from 'lucide-react'
import { Badge, Button, Skeleton, toast } from '../../ui'
import { refreshProfile, type UserProfile } from '../../services/profileApi'
import type { EDAReport } from '../../services/analyticsApi'
import { qk } from '../../app/queryClient'
import { formatStamp, parseServerTime } from '../../lib/dates'
import { abilityRows, weakPointsOf } from './reportModel'
import s from './report.module.css'

/*
 * 学习画像 — merged from the former /profile page. Only abilities the backend
 * actually measures are drawn (专注度, 坚持度); 自控力 mirrors 专注度 and
 * 计划执行 is a fixed placeholder today, so they are named, not plotted.
 */

function typeIcon(type: string) {
  if (/夜/.test(type)) return <Moon />
  if (/早|晨/.test(type)) return <Sunrise />
  if (/白天|日间/.test(type)) return <Sun />
  return <TrendingUp />
}

interface ProfileSectionProps {
  report: EDAReport | undefined
  profile: UserProfile | null | undefined
  loading: boolean
  flash?: boolean
}

export function ProfileSection({ report, profile: p, loading, flash = false }: ProfileSectionProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  const recompute = async () => {
    setRefreshing(true)
    try {
      const next = await refreshProfile()
      if (!next) throw new Error('refresh failed')
      qc.setQueryData(qk.profile, next)
      toast.success('画像已按最新记录重新计算')
    } catch {
      toast.error('重新计算失败，请稍后重试')
    } finally {
      setRefreshing(false)
    }
  }

  const type = report?.profile?.profile_type
  const updated = parseServerTime(p?.last_updated)

  return (
    <section
      id="report-profile"
      className={flash ? `${s.profile} ${s.flash}` : s.profile}
      aria-labelledby="report-profile-title"
      tabIndex={-1}
    >
      <div className={s.profileHead}>
        {type && (
          <span className={s.profileGlyph} aria-hidden>
            {typeIcon(type)}
          </span>
        )}
        <div className={s.profileHeadText}>
          <h2 id="report-profile-title" className={s.profileTitle}>
            {type ? `学习画像 · ${type}` : '学习画像'}
            {p?.data_insufficient && <Badge tone="neutral">记录还少，仅供参考</Badge>}
          </h2>
          <p className={s.profileBody}>
            {report?.profile?.best_study_window && `高效窗口在 ${report.profile.best_study_window}。`}
            {(report?.profile?.evidence ?? []).length > 0 && `依据：${report!.profile.evidence.join('；')}。`}
            {!type && '根据你全部的专注、复习和错题记录计算，不受上面的时间范围影响。'}
          </p>
        </div>
        <Button size="sm" variant="ghost" icon={<RefreshCw />} loading={refreshing} onClick={() => void recompute()}>
          重新计算
        </Button>
      </div>

      {loading ? (
        <Skeleton height={120} radius={12} />
      ) : !p ? (
        <p className={s.figCaption}>画像暂时读不到。完成 3 个以上番茄钟后会自动生成。</p>
      ) : (
        <ProfileBody profile={p} onWeakPoint={kp => navigate(`/wrong-questions?q=${encodeURIComponent(kp)}`)} />
      )}

      {updated && <p className={s.note}>画像更新于 {formatStamp(updated)}，按全部记录计算，每小时自动刷新一次。</p>}
    </section>
  )
}

function ProfileBody({ profile: p, onWeakPoint }: { profile: UserProfile; onWeakPoint: (kp: string) => void }) {
  const rows = abilityRows(p)
  const weak = weakPointsOf(p.weak_points)
  return (
    <div className={s.profileGrid}>
      <div>
        <p className={s.colTitle}>学习能力</p>
        <ul className={s.meters}>
          {rows.map(r => (
            <li key={r.key} className={s.meterRow}>
              <span className={s.meterLabel}>{r.label}</span>
              <span
                className={s.meter}
                role="meter"
                aria-label={r.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={r.value}
                style={{ '--v': `${r.value}%` } as CSSProperties}
              >
                <i />
              </span>
              <b className={s.meterValue}>{r.value}</b>
              <span className={s.meterFoot}>{r.foot}</span>
            </li>
          ))}
        </ul>
        <p className={s.meterNote}>自控力与计划执行还在接入更多数据，暂不单独打分。</p>
      </div>

      <div className={s.profileFacts}>
        <div className={s.fact}>
          <Flame aria-hidden />
          <span>
            <b>{p.streak_days}</b> 天连续学习
          </span>
        </div>
        <p className={s.factLine}>
          完整完成 {p.total_pomodoros} 个番茄钟，共 {Number(p.total_study_hours.toFixed(1))} 小时，分布在 {p.total_study_days} 天
          {p.avg_session_duration > 0 && `，平均每个 ${p.avg_session_duration} 分钟`}。中途停下的不计入。
        </p>

        <p className={s.colTitle} style={{ marginTop: '1rem' }}>
          薄弱知识点
        </p>
        {weak.length === 0 ? (
          <p className={s.figCaption}>还没有。做错的题标上知识点后，这里会按错题数量排出来。</p>
        ) : (
          <ol className={s.weak} aria-label="薄弱知识点，按错题数量从多到少">
            {weak.map((kp, i) => (
              <li key={kp}>
                <button type="button" className={s.weakItem} data-top={i < 3 || undefined} onClick={() => onWeakPoint(kp)}>
                  <CircleX aria-hidden />
                  {kp}
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}

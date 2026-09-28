import { useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { formatMinutes, heatLevel, labelledDays, niceTicks, shortMD, type HeatGrid, type Outcome } from './reportModel'
import s from './charts.module.css'

/*
 * Hand-drawn SVG charts. Values are always reachable without hover: the
 * crosshair tooltip enhances, and every chart has a table twin in the page.
 */

/* ============================================================================
   Daily trend: minutes per day (bars) + 7-day rolling mean (line), one axis
   ========================================================================== */
export interface DayPoint {
  date: string
  minutes: number
  mean: number
  sessions: number
}

const W = 720
const H = 220
const PAD = { top: 12, right: 12, bottom: 26, left: 34 }

export function TrendChart({ points, label }: { points: DayPoint[]; label: string }) {
  const [active, setActive] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const n = points.length
  const max = Math.max(1, ...points.map(p => Math.max(p.minutes, p.mean)))
  const ticks = niceTicks(max)
  const top = ticks[ticks.length - 1]
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const band = innerW / Math.max(1, n)
  const barW = Math.max(2, Math.min(24, band * 0.62))
  const x = (i: number) => PAD.left + band * i + band / 2
  const y = (v: number) => PAD.top + innerH - (v / top) * innerH
  const labels = useMemo(() => labelledDays(n), [n])

  const linePath = useMemo(
    () =>
      points
        .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.mean).toFixed(1)}`)
        .join(' '),
    [points, top],
  )

  const pick = (e: PointerEvent<SVGRectElement>) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const i = Math.round((px - PAD.left - band / 2) / band)
    setActive(Math.max(0, Math.min(n - 1, i)))
  }

  const onKey = (e: KeyboardEvent<SVGRectElement>) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      setActive(i => {
        const cur = i ?? n - 1
        return Math.max(0, Math.min(n - 1, cur + (e.key === 'ArrowRight' ? 1 : -1)))
      })
    } else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(n - 1)
  }

  const a = active != null ? points[active] : null
  return (
    <div className={s.viz}>
      <ul className={s.legend} aria-hidden>
        <li>
          <i className={s.key} style={{ '--k': 'var(--v2)' } as CSSProperties} />
          每日学习分钟
        </li>
        <li>
          <i className={s.key} data-shape="line" style={{ '--k': 'var(--v5)' } as CSSProperties} />7 日平均
        </li>
      </ul>
      <svg ref={svgRef} className={s.svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map(t => (
          <g key={t}>
            <line className={t === 0 ? s.axis : s.grid} x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
            <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          const h = Math.max(0, y(0) - y(p.minutes))
          const bx = x(i) - barW / 2
          const r = Math.min(4, barW / 2, h)
          return p.minutes > 0 ? (
            <path
              key={p.date}
              className={s.bar}
              data-active={active === i || undefined}
              d={`M${bx},${y(0)} V${y(0) - h + r} Q${bx},${y(0) - h} ${bx + r},${y(0) - h} H${bx + barW - r} Q${bx + barW},${y(0) - h} ${bx + barW},${y(0) - h + r} V${y(0)} Z`}
            />
          ) : (
            <rect key={p.date} className={s.bar} data-zero x={bx} y={y(0) - 2} width={barW} height={2} rx={1} />
          )
        })}
        <path className={s.meanLine} d={linePath} />
        {points.map((p, i) =>
          labels.has(i) ? (
            <text key={`l${p.date}`} x={x(i)} y={H - 8} textAnchor="middle">
              {shortMD(p.date)}
            </text>
          ) : null,
        )}
        {a && active != null && (
          <>
            <line className={s.crosshair} x1={x(active)} x2={x(active)} y1={PAD.top} y2={y(0)} />
            <circle className={s.meanDot} cx={x(active)} cy={y(a.mean)} r={4} />
          </>
        )}
        <rect
          className={s.hit}
          x={PAD.left}
          y={PAD.top}
          width={innerW}
          height={innerH}
          tabIndex={0}
          aria-label="逐日查看：用左右方向键移动"
          onPointerMove={pick}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive(n - 1)}
          onBlur={() => setActive(null)}
          onKeyDown={onKey}
        />
      </svg>
      {a && active != null && (
        <div className={s.tip} style={{ left: `${(x(active) / W) * 100}%`, top: `${(Math.min(y(a.minutes), y(a.mean)) / H) * 100}%` }} role="status">
          <div className={s.tipTitle}>{shortMD(a.date)}</div>
          <div className={s.tipRow}>
            <i className={s.tipKey} data-shape="rect" style={{ '--k': 'var(--v2)' } as CSSProperties} />
            <b>{formatMinutes(a.minutes)}</b>
            <span>当天</span>
          </div>
          <div className={s.tipRow}>
            <i className={s.tipKey} style={{ '--k': 'var(--v5)' } as CSSProperties} />
            <b>{formatMinutes(a.mean)}</b>
            <span>7 日平均</span>
          </div>
        </div>
      )}
    </div>
  )
}

/* ============================================================================
   Weekday × hour heatmap
   ========================================================================== */
export function HeatmapChart({ grid, bestHours }: { grid: HeatGrid; bestHours: Set<number> }) {
  const [tip, setTip] = useState<{ d: number; h: number; left: number; top: number } | null>(null)
  const wrap = useRef<HTMLDivElement | null>(null)

  const show = (d: number, h: number, el: HTMLElement) => {
    const box = wrap.current?.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    if (!box) return
    setTip({ d, h, left: r.left - box.left + r.width / 2, top: r.top - box.top })
  }

  return (
    <div className={s.viz} ref={wrap} onPointerLeave={() => setTip(null)}>
      <div className={s.heat} role="grid" aria-label="一周各时段的学习分钟">
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} className={s.heatHour} aria-hidden>
            {h % 3 === 0 ? h : ''}
          </span>
        ))}
        {grid.weekdays.map((wd, d) => (
          <div key={wd} role="row" style={{ display: 'contents' }}>
            <span className={s.heatLabel} role="rowheader">
              {wd}
            </span>
            {grid.cells[d].map((v, h) => (
              <button
                key={h}
                type="button"
                role="gridcell"
                className={s.cell}
                data-l={heatLevel(v, grid.max)}
                aria-label={`${wd} ${h}:00，${v > 0 ? formatMinutes(v) : '没有学习'}`}
                onPointerEnter={e => show(d, h, e.currentTarget)}
                onFocus={e => show(d, h, e.currentTarget)}
                onBlur={() => setTip(null)}
              />
            ))}
          </div>
        ))}
        <span />
        {bestHours.size > 0 && (
          <div className={s.window} aria-hidden>
            {Array.from({ length: 24 }, (_, h) => (
              <i key={h} data-on={bestHours.has(h) || undefined} />
            ))}
          </div>
        )}
      </div>
      {tip && (
        <div className={s.tip} style={{ left: tip.left, top: tip.top }} role="status">
          <div className={s.tipTitle}>
            {grid.weekdays[tip.d]} {tip.h}:00–{(tip.h + 1) % 24}:00
          </div>
          <div className={s.tipRow}>
            <i className={s.tipKey} data-shape="rect" style={{ '--k': `var(--v${Math.max(1, heatLevel(grid.cells[tip.d][tip.h], grid.max))})` } as CSSProperties} />
            <b>{grid.cells[tip.d][tip.h] > 0 ? formatMinutes(grid.cells[tip.d][tip.h]) : '没有学习'}</b>
          </div>
        </div>
      )}
    </div>
  )
}

export function HeatScale({ showWindow }: { showWindow: boolean }) {
  return (
    <div className={`${s.viz} ${s.scale}`} aria-hidden>
      少
      <span>
        <i style={{ background: 'var(--v-empty)' }} />
        {[1, 2, 3, 4, 5].map(l => (
          <i key={l} style={{ background: `var(--v${l})` }} />
        ))}
      </span>
      多
      {showWindow && (
        <>
          <span style={{ marginLeft: '0.75rem' }}>
            <i style={{ height: 3, background: 'var(--mx-evidence)' }} />
          </span>
          完成率最高的时段
        </>
      )}
    </div>
  )
}

/* ============================================================================
   Session outcomes: one stacked bar (part-to-whole), status colours with labels
   ========================================================================== */
const OUTCOME_COLOR: Record<Outcome['key'], string> = {
  completed: 'var(--v-good)',
  early_done: 'var(--v3)',
  interrupted: 'var(--v-warn)',
  distracted: 'var(--v-bad)',
  other: 'var(--v-muted)',
}

export function OutcomeChart({ outcomes }: { outcomes: Outcome[] }) {
  const total = outcomes.reduce((n, o) => n + o.count, 0)
  return (
    <div className={s.viz}>
      <div className={s.stack} role="img" aria-label={outcomes.map(o => `${o.label} ${o.count} 次`).join('，')}>
        {outcomes.map(o => (
          <span
            key={o.key}
            className={s.seg}
            title={`${o.label} ${o.count} 次`}
            style={{ flex: `${o.count} 1 0`, '--k': OUTCOME_COLOR[o.key] } as CSSProperties}
          />
        ))}
      </div>
      <ul className={s.outcomeList}>
        {outcomes.map(o => (
          <li key={o.key} className={s.outcome}>
            <span className={s.outcomeHead}>
              <i className={s.key} style={{ '--k': OUTCOME_COLOR[o.key] } as CSSProperties} />
              {o.label}
            </span>
            <b>
              {o.count}
              <small>{total ? `${Math.round((o.count / total) * 100)}%` : ''}</small>
            </b>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ============================================================================
   Session length: ordered buckets as horizontal bars (sequential, one hue)
   ========================================================================== */
export function LengthChart({ buckets }: { buckets: Array<{ label: string; count: number }> }) {
  const max = Math.max(1, ...buckets.map(b => b.count))
  const topCount = Math.max(...buckets.map(b => b.count))
  return (
    <ul className={`${s.viz} ${s.hbars}`}>
      {buckets.map(b => (
        <li key={b.label} className={s.hbar}>
          <span>{b.label}</span>
          <span className={s.hbarTrack}>
            <span
              className={s.hbarFill}
              data-top={(b.count === topCount && b.count > 0) || undefined}
              style={{ display: 'block', width: `${(b.count / max) * 100}%` }}
            />
          </span>
          <b>{b.count}</b>
        </li>
      ))}
    </ul>
  )
}

/* ============================================================================
   Table twin
   ========================================================================== */
export function DataTable({ caption, head, rows }: { caption: string; head: string[]; rows: Array<Array<string | number>> }) {
  return (
    <div className={s.tableWrap}>
      <table className={s.table}>
        <caption className="mx-visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {head.map(h => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const chartStyles = s

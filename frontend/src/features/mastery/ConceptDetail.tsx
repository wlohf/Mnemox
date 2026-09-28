import { useEffect, useState, type CSSProperties } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, MoreHorizontal, RefreshCw, SlidersHorizontal, Undo2 } from 'lucide-react'
import { Badge, Button, Confirm, Dialog, Field, IconButton, Input, Menu, Notice, ProgressBar, Segmented, Skeleton, Slider, Textarea, toast } from '../../ui'
import {
  addConceptAlias,
  applyConceptOverride,
  clearConceptOverride,
  deleteConcept,
  getConceptDetail,
  getConceptEvidence,
  getConceptState,
  mergeConcept,
  recomputeConceptState,
  renameConcept,
  reviewConcept,
  type ConceptState,
  type ConceptSummary,
  type EvidenceCategory,
} from '../../services/learnerModelApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { listMaterials } from '../../services/materialApi'
import { qk } from '../../app/queryClient'
import { shortDate } from '../../lib/dates'
import { CATEGORY_META, LEVEL_LABEL, basisOf, evidenceTypeLabel, levelColor, levelOf, pct, pct01, riskLabel } from './masteryModel'
import s from './mastery.module.css'

const PAGE = 8
const RAMP = [1, 2, 3, 4, 5] as const

export function ConceptDetail({
  concept,
  concepts,
  onSelect,
  onChanged,
  onDeleted,
}: {
  concept: ConceptSummary
  concepts: ConceptSummary[]
  onSelect: (id: number) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const qc = useQueryClient()
  const [category, setCategory] = useState<'all' | EvidenceCategory>('all')
  const [page, setPage] = useState(0)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [identity, setIdentity] = useState<'rename' | 'alias' | 'merge' | null>(null)
  const [removing, setRemoving] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setCategory('all')
    setPage(0)
  }, [concept.id])

  const stateKey = ['learner', 'state', concept.id] as const
  const state = useQuery({ queryKey: stateKey, queryFn: () => getConceptState(concept.id), retry: false })
  const detail = useQuery({ queryKey: ['learner', 'concept', concept.id], queryFn: () => getConceptDetail(concept.id), retry: false })
  const evidence = useQuery({
    queryKey: ['learner', 'evidence', concept.id, category, page],
    queryFn: () => getConceptEvidence(concept.id, { offset: page * PAGE, limit: PAGE, evidenceCategory: category === 'all' ? undefined : category }),
    placeholderData: prev => prev,
  })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['learner'] })
    onChanged()
  }
  const run = async (fn: () => Promise<unknown>, ok: string, fail: string) => {
    setBusy(true)
    try {
      await fn()
      toast.success(ok)
      refresh()
    } catch (error) {
      toast.error(getApiErrorMessage(error, fail))
    } finally {
      setBusy(false)
    }
  }

  const materials = useQuery({ queryKey: qk.materials, queryFn: () => listMaterials(500), staleTime: 60_000 })
  const materialTitle = (id: number) => materials.data?.find(m => m.id === id)?.title.replace(/.(pdf|docx|md|txt)$/i, '')
  const st = state.data
  const direct = Number(st?.explanation_summary?.direct_evidence_count ?? 0)
  const indirect = Number(st?.explanation_summary?.indirect_signal_count ?? 0)
  // Without any evidence the model's numbers are defaults, not observations.
  const hasEvidence = Boolean(st && (direct > 0 || indirect > 0 || st.manual_override?.active || (st.attempt_count ?? 0) > 0))
  const mastery = pct(st?.mastery_estimate ?? concept.mastery)
  const level = levelOf(mastery, hasEvidence)
  const risk = hasEvidence ? riskLabel(st?.forgetting_risk) : { text: '未知', tone: 'neutral' as const }
  const total = evidence.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))

  return (
    <article className={s.detail} key={concept.id} aria-labelledby="concept-name">
      <header className={s.detailHead}>
        <h2 id="concept-name" className={s.detailName}>
          {concept.name}
        </h2>
        {concept.review_status === 'pending' && <Badge tone="evidence">待你确认</Badge>}
        {concept.review_status === 'rejected' && <Badge>已拒绝</Badge>}
        {st?.manual_override?.active && <Badge tone="ink">你修正过</Badge>}
        <span className={s.detailHeadEnd}>
          {concept.review_status === 'pending' && (
            <>
              <Button size="sm" variant="primary" loading={busy} onClick={() => void run(() => reviewConcept(concept.id, 'confirmed'), '已确认这个概念', '确认失败')}>
                确认
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => reviewConcept(concept.id, 'rejected'), '已拒绝', '操作失败')}>
                不是概念
              </Button>
            </>
          )}
          <Menu
            items={[
              { key: 'override', label: '手动修正掌握度', icon: <SlidersHorizontal />, onSelect: () => setOverrideOpen(true), disabled: !st },
              { key: 'recompute', label: '按证据重新计算', icon: <RefreshCw />, onSelect: () => void run(() => recomputeConceptState(concept.id), '已重新计算', '重新计算失败') },
              { key: 'sep', type: 'separator' },
              { key: 'rename', label: '改名', onSelect: () => setIdentity('rename') },
              { key: 'alias', label: '添加别名', onSelect: () => setIdentity('alias') },
              { key: 'merge', label: '并入另一个概念…', onSelect: () => setIdentity('merge') },
              { key: 'sep2', type: 'separator' },
              { key: 'delete', label: '删除概念', tone: 'danger', onSelect: () => setRemoving(true) },
            ]}
            trigger={
              <IconButton label="概念操作" size="sm">
                <MoreHorizontal />
              </IconButton>
            }
          />
        </span>
      </header>

      {st?.manual_override?.active && (
        <Notice
          tone="ink"
          className={s.override}
          title="这是你手动设定的掌握度"
          actions={
            <Button size="sm" variant="ghost" icon={<Undo2 />} loading={busy} onClick={() => void run(() => clearConceptOverride(concept.id, '在掌握度页撤销手动修正'), '已恢复按证据计算', '撤销失败')}>
              改回按证据计算
            </Button>
          }
        >
          {st.manual_override.reason || '没有写原因。'}
        </Notice>
      )}

      <section className={`${s.panel} ${s.gauge}`} aria-label="掌握程度">
        {state.isLoading ? (
          <Skeleton height={96} />
        ) : state.isError ? (
          <p className={s.basis}>这个概念还没有学习状态。确认它，并做一次相关练习后就会有估计。</p>
        ) : (
          <>
            <div className={s.gaugeTop}>
              <span className={s.gaugeValue}>
                {hasEvidence ? mastery : '—'}
                {hasEvidence && <small>/100</small>}
              </span>
              <span className={s.gaugeLabel}>{LEVEL_LABEL[level]}</span>
            </div>
            <div className={s.track} role="img" aria-label={`掌握度 ${mastery}，${LEVEL_LABEL[level]}`}>
              {RAMP.map(l => (
                <i key={l} style={{ '--c': levelColor(l) } as CSSProperties} />
              ))}
              {hasEvidence && <span className={s.needle} style={{ '--v': mastery } as CSSProperties} />}
            </div>
            <div className={s.gaugeStats}>
              <div className={s.gstat}>
                <span>把握程度</span>
                <b>{hasEvidence ? `${pct01(st?.confidence)}%` : '—'}</b>
              </div>
              <div className={s.gstat}>
                <span>遗忘风险</span>
                <b data-tone={risk.tone}>{risk.text}</b>
              </div>
              <div className={s.gstat}>
                <span>作答 · 答对 · 用提示</span>
                <b>
                  {st?.attempt_count ?? 0} · {st?.correct_count ?? 0} · {st?.hint_count ?? 0}
                </b>
              </div>
            </div>
            <p className={s.basis}>
              {basisOf(st)}
              {st?.common_error_type && ` 最常见的错误：${st.common_error_type}。`}
              {st?.next_review_at && ` 下次复习：${shortDate(st.next_review_at)}。`}
            </p>
          </>
        )}
      </section>

      {detail.data && detail.data.prerequisite_gaps.length > 0 && (
        <section className={`${s.panel} ${s.panelBody} ${s.block}`} style={{ paddingTop: '1rem' }} aria-label="先修缺口">
          <h3 className={s.blockTitle}>
            先补这些 <span>它们还不牢，会拖住这个概念</span>
          </h3>
          <div className={s.gaps}>
            {detail.data.prerequisite_gaps.map(g => (
              <button key={g.concept_id} type="button" className={s.gap} onClick={() => onSelect(g.concept_id)}>
                <i style={{ '--c': levelColor(levelOf(g.mastery_estimate)) } as CSSProperties} aria-hidden />
                {g.name} · {pct(g.mastery_estimate)}
              </button>
            ))}
          </div>
        </section>
      )}

      {detail.data && detail.data.source_evidence.length > 0 && (
        <section className={`${s.panel} ${s.panelBody} ${s.block}`} style={{ paddingTop: '1rem' }} aria-label="出处">
          <h3 className={s.blockTitle}>
            出处 <span>{detail.data.aliases.length > 0 && `也叫：${detail.data.aliases.map(a => a.alias).join('、')}`}</span>
          </h3>
          {detail.data.source_evidence.slice(0, 3).map(q => (
            <blockquote key={q.id} className={s.quote}>
              {q.excerpt.replace(/^#{1,6}s+/gm, '').replace(/[*_`]/g, '').trim()}
              <cite>
                {q.source_type === 'material'
                  ? `资料 · ${materialTitle(q.source_id) ?? `#${q.source_id}`}`
                  : q.source_type === 'note'
                    ? `笔记 #${q.source_id}`
                    : q.source_type === 'wrong_question'
                      ? `错题 #${q.source_id}`
                      : `${q.source_type} #${q.source_id}`}
              </cite>
            </blockquote>
          ))}
        </section>
      )}

      <section className={`${s.panel} ${s.panelBody} ${s.block}`} style={{ paddingTop: '1rem' }} aria-labelledby="ev-title">
        <div className={s.blockTitle} style={{ alignItems: 'center' }}>
          <h3 id="ev-title" style={{ margin: 0, fontSize: 'inherit', fontWeight: 'inherit' }}>
            证据
          </h3>
          <span>{total} 条</span>
          <span style={{ marginLeft: 'auto' }}>
            <Segmented
              size="sm"
              ariaLabel="证据类别"
              value={category}
              onChange={v => {
                setCategory(v)
                setPage(0)
              }}
              options={[
                { value: 'all', label: '全部' },
                { value: 'direct', label: '直接' },
                { value: 'indirect', label: '间接' },
                { value: 'manual', label: '修正' },
              ]}
            />
          </span>
        </div>
        {evidence.isLoading ? (
          <div className={s.skel}>
            <Skeleton height={36} />
            <Skeleton height={36} />
          </div>
        ) : total === 0 ? (
          <p className={s.basis} style={{ marginTop: 0 }}>
            {category === 'all' ? '还没有证据。做一次回忆、练习或复习，就会记录在这里。' : `没有${CATEGORY_META[category as EvidenceCategory].label}。`}
          </p>
        ) : (
          <>
            <ul className={s.evidence}>
              {(evidence.data?.items ?? []).map(e => (
                <li key={e.id} className={s.ev}>
                  <div>
                    <span className={s.evType}>{evidenceTypeLabel(e.evidence_type)}</span>
                    <span className={s.evMeta}>
                      {CATEGORY_META[e.evidence_category]?.label} · {e.observed_at ? shortDate(e.observed_at) : '时间未知'} · 可靠度 {pct01(e.reliability)}%
                    </span>
                  </div>
                  <span className={s.evScore}>
                    <ProgressBar className={s.evBar} value={Math.max(0, Math.min(1, e.score))} label="证据得分" color="var(--mx-m4)" />
                    {pct01(e.score)}
                  </span>
                </li>
              ))}
            </ul>
            {pages > 1 && (
              <div className={s.pager}>
                <IconButton label="上一页" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
                  <ChevronLeft />
                </IconButton>
                {page + 1} / {pages}
                <IconButton label="下一页" size="sm" disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)}>
                  <ChevronRight />
                </IconButton>
              </div>
            )}
          </>
        )}
      </section>

      <OverrideDialog
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        name={concept.name}
        state={st}
        onApply={async body => {
          await applyConceptOverride(concept.id, body)
          toast.success('已按你的判断修正', { description: '证据仍然保留，随时可以改回按证据计算。' })
          refresh()
        }}
      />
      <IdentityDialog
        mode={identity}
        onOpenChange={v => !v && setIdentity(null)}
        concept={concept}
        concepts={concepts}
        onDone={refresh}
      />
      <Confirm
        open={removing}
        onOpenChange={setRemoving}
        tone="danger"
        title={`删除概念「${concept.name}」？`}
        description="它的关系、别名和学习状态都会清除（保留删除记录）。如果只是名字不对，可以改名或并入另一个概念。"
        confirmLabel="删除概念"
        onConfirm={async () => {
          try {
            await deleteConcept(concept.id)
            toast.success('概念已删除')
            onDeleted()
            refresh()
          } catch (error) {
            toast.error(getApiErrorMessage(error, '删除失败'))
            throw error
          }
        }}
      />
    </article>
  )
}

/* ============================================================================
   Manual override — the learner's judgement, recorded as evidence
   ========================================================================== */
function OverrideDialog({
  open,
  onOpenChange,
  name,
  state,
  onApply,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  name: string
  state: ConceptState | undefined
  onApply: (body: { mastery_estimate: number; confidence?: number; forgetting_risk?: number; reason: string }) => Promise<void>
}) {
  const [mastery, setMastery] = useState(50)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!open) return
    setMastery(pct(state?.mastery_estimate))
    setReason('')
  }, [open, state])

  const lvl = levelOf(mastery)
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`修正「${name}」的掌握度`}
      description="如果你比系统更清楚自己的水平，可以直接设定。这会作为一条“你的修正”记进证据里。"
      width={32}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!reason.trim()}
            onClick={async () => {
              setBusy(true)
              try {
                await onApply({ mastery_estimate: mastery, reason: reason.trim() })
                onOpenChange(false)
              } catch (error) {
                toast.error(getApiErrorMessage(error, '修正失败'))
              } finally {
                setBusy(false)
              }
            }}
          >
            应用修正
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="你觉得自己掌握到什么程度">
          <div className={s.sliderRow}>
            <Slider ariaLabel="掌握度" min={0} max={100} step={5} value={mastery} onValueChange={setMastery} />
            <span className={s.sliderValue}>{mastery}</span>
          </div>
          <span style={{ color: 'var(--mx-text-3)', fontSize: 'var(--mx-type-caption)' }}>{LEVEL_LABEL[lvl]}</span>
        </Field>
        <Field label="为什么" htmlFor="ov-reason" hint="必填。以后回看时知道当时的依据。">
          <Textarea id="ov-reason" autoGrow rows={2} maxHeight={160} maxLength={500} value={reason} placeholder="例如：上周考试这部分全对" onChange={e => setReason(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  )
}

/* ============================================================================
   Identity — rename / alias / merge
   ========================================================================== */
function IdentityDialog({
  mode,
  onOpenChange,
  concept,
  concepts,
  onDone,
}: {
  mode: 'rename' | 'alias' | 'merge' | null
  onOpenChange: (v: boolean) => void
  concept: ConceptSummary
  concepts: ConceptSummary[]
  onDone: () => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (mode) setValue(mode === 'rename' ? concept.name : '')
  }, [mode, concept.name])

  const titles = { rename: '改名', alias: '添加别名', merge: '并入另一个概念' } as const
  const others = concepts.filter(c => c.id !== concept.id && c.review_status !== 'rejected')
  const source = mode === 'merge' ? others.find(c => c.name === value.trim()) : undefined

  const submit = async () => {
    const v = value.trim()
    if (!v || !mode) return
    setBusy(true)
    try {
      if (mode === 'rename') await renameConcept(concept.id, v)
      else if (mode === 'alias') await addConceptAlias(concept.id, v)
      else {
        if (!source) throw new Error('没有找到这个概念，请从下面的列表里选')
        await mergeConcept(concept.id, source.id)
      }
      toast.success(mode === 'merge' ? `已把「${v}」并入「${concept.name}」` : '已更新')
      onDone()
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '更新失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={mode != null}
      onOpenChange={onOpenChange}
      title={mode ? titles[mode] : ''}
      description={
        mode === 'merge'
          ? `把重复的概念并进「${concept.name}」，它的证据和关系都会转过来。`
          : mode === 'alias'
            ? '别名能让同一个概念在不同资料里被认出来。'
            : undefined
      }
      width={28}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} disabled={!value.trim() || (mode === 'merge' && !source)} onClick={() => void submit()}>
            {mode === 'merge' ? '并入' : '保存'}
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label={mode === 'merge' ? '要并入的概念' : mode === 'alias' ? '别名' : '新名称'} htmlFor="id-value">
          <Input id="id-value" autoFocus list={mode === 'merge' ? 'concept-names' : undefined} maxLength={120} value={value} onChange={e => setValue(e.target.value)} />
          {mode === 'merge' && (
            <datalist id="concept-names">
              {others.map(c => (
                <option key={c.id} value={c.name} />
              ))}
            </datalist>
          )}
        </Field>
      </div>
    </Dialog>
  )
}

import { useMemo, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Grid3x3, Library, Network, Search, X } from 'lucide-react'
import { Badge, Button, Empty, IconButton, Input, Notice, Segmented, Skeleton, Tabs } from '../../ui'
import { getMasteryMap } from '../../services/learningApi'
import { getLearningRecommendations, listLearnerConcepts } from '../../services/learnerModelApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import {
  LEVEL_LABEL,
  RECOMMENDATION_META,
  chapterMatrix,
  filterConcepts,
  levelColor,
  levelOf,
  overviewOf,
  pct,
  recommendationRoute,
  sortConcepts,
  type ConceptFilter,
} from './masteryModel'
import { ConceptDetail } from './ConceptDetail'
import s from './mastery.module.css'

type View = 'map' | 'concepts'
const RAMP = [1, 2, 3, 4, 5] as const

export function MasteryPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view: View = params.get('view') === 'concepts' || params.get('concept') ? 'concepts' : 'map'
  const selectedId = Number(params.get('concept')) || null
  const [filter, setFilter] = useState<ConceptFilter>('all')
  const [query, setQuery] = useState('')

  const map = useQuery({ queryKey: qk.masteryMap, queryFn: getMasteryMap, staleTime: 60_000 })
  const concepts = useQuery({ queryKey: ['learner', 'concepts'], queryFn: () => listLearnerConcepts(300), staleTime: 60_000 })
  const recs = useQuery({ queryKey: ['learner', 'recommendations'], queryFn: () => getLearningRecommendations(6), staleTime: 60_000, retry: false })

  usePageChrome({ title: '掌握度' })

  const list = concepts.data ?? []
  const ov = overviewOf(list)
  const matrix = chapterMatrix(map.data)
  const shown = useMemo(() => sortConcepts(filterConcepts(list, filter, query)), [list, filter, query])
  const selected = list.find(c => c.id === selectedId) ?? (view === 'concepts' ? shown[0] ?? null : null)

  const setView = (v: View) => {
    const next = new URLSearchParams(params)
    if (v === 'concepts') next.set('view', 'concepts')
    else {
      next.delete('view')
      next.delete('concept')
    }
    setParams(next, { replace: true })
  }
  const openConcept = (id: number) => {
    const next = new URLSearchParams(params)
    next.set('view', 'concepts')
    next.set('concept', String(id))
    setParams(next)
  }

  const chapterCount = matrix.reduce((n, m) => n + m.chapters.length, 0)

  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <h1 className={s.title}>掌握度</h1>
          <p className={s.lead}>
            每个估计都来自你的作答、回忆和复习记录，点开就能看到依据。
            {ov.confirmed > 0 && (
              <>
                {' '}
                已确认 <strong>{ov.confirmed}</strong> 个概念
                {ov.average != null && (
                  <>
                    ，平均 <strong>{ov.average}</strong>
                  </>
                )}
                {ov.weak > 0 && (
                  <>
                    ，<strong>{ov.weak}</strong> 个还不牢
                  </>
                )}
                。
              </>
            )}
          </p>
        </div>
        <div className={s.legend} aria-hidden>
          不牢
          <span className={s.ramp}>
            {RAMP.map(l => (
              <i key={l} style={{ '--c': levelColor(l) } as CSSProperties} />
            ))}
          </span>
          扎实
        </div>
      </header>

      <Tabs
        className={s.tabs}
        value={view}
        onValueChange={setView}
        ariaLabel="视图"
        items={[
          { value: 'map', label: '章节地图', icon: <Grid3x3 /> },
          { value: 'concepts', label: '概念与证据', icon: <Network />, count: ov.pending > 0 ? ov.pending : undefined },
        ]}
      />

      {view === 'map' ? (
        <div className={s.overview}>
          <section className={s.panel} aria-labelledby="map-title">
            <div className={s.panelHead}>
              <h2 id="map-title" className={s.panelTitle}>
                各章节掌握情况
              </h2>
              <span className={s.panelMeta}>{chapterCount > 0 ? `${matrix.length} 份资料 · ${chapterCount} 个章节` : ''}</span>
            </div>
            <div className={s.panelBody}>
              {map.isLoading ? (
                <div className={s.skel}>
                  <Skeleton height={20} width="40%" />
                  <Skeleton height={84} radius={10} />
                </div>
              ) : map.isError ? (
                <Notice tone="danger" title="章节数据没能加载" actions={<Button size="sm" onClick={() => void map.refetch()}>重试</Button>} />
              ) : matrix.length === 0 ? (
                <Empty
                  align="start"
                  icon={<Library />}
                  title="还没有章节数据"
                  body="在资料库里打开一份教材，点“开始学这份资料”，它的章节就会出现在这里，并随你的复习和练习变色。"
                  actions={
                    <Button size="sm" variant="secondary" onClick={() => navigate('/materials')}>
                      去资料库
                    </Button>
                  }
                />
              ) : (
                matrix.map(m => (
                  <div key={m.id} className={s.material}>
                    <div className={s.materialHead}>
                      <span className={s.materialTitle} title={m.title}>
                        {m.title}
                      </span>
                      <span className={s.materialAvg}>平均 {m.average}</span>
                    </div>
                    <div className={s.plots}>
                      {m.chapters.map((c, i) => (
                        <button
                          key={c.id}
                          type="button"
                          className={s.plot}
                          data-level={c.level}
                          style={{ '--c': levelColor(c.level), '--i': i } as CSSProperties}
                          aria-label={`${c.title}：${c.mastery}，${LEVEL_LABEL[c.level]}`}
                          onClick={() => navigate(`/?${new URLSearchParams({ ask: `我想巩固「${c.title}」这一章，先用 3 个问题摸摸我的底。`, context: m.title })}`)}
                        >
                          <span className={s.plotTitle}>{c.title}</span>
                          <span className={s.plotFoot}>
                            {LEVEL_LABEL[c.level]}
                            <b>{c.mastery}</b>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className={s.panel} aria-labelledby="next-title">
            <div className={s.panelHead}>
              <h2 id="next-title" className={s.panelTitle}>
                接下来练什么
              </h2>
              <span className={s.panelMeta}>按先修关系、遗忘风险和目标排序</span>
            </div>
            <div className={s.panelBody}>
              {recs.isLoading ? (
                <div className={s.skel}>
                  <Skeleton height={48} />
                  <Skeleton height={48} />
                </div>
              ) : (recs.data?.items ?? []).length === 0 ? (
                <Empty
                  align="start"
                  icon={<Network />}
                  title="暂时没有建议"
                  body={ov.pending > 0 ? `有 ${ov.pending} 个从资料里抽出的概念等你确认。确认后，建议会根据它们给出。` : '确认几个概念并完成一次练习后，这里会告诉你先练哪个。'}
                  actions={
                    ov.pending > 0 && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setFilter('pending')
                          setView('concepts')
                        }}
                      >
                        去确认概念
                      </Button>
                    )
                  }
                />
              ) : (
                <ul className={s.recs}>
                  {(recs.data?.items ?? []).map(r => {
                    const meta = RECOMMENDATION_META[r.task_type]
                    return (
                      <li key={`${r.concept_id}-${r.task_type}`} className={s.rec}>
                        <div>
                          <div className={s.recHead}>
                            <button
                              type="button"
                              className={s.recName}
                              style={{ padding: 0, border: 0, background: 'none', cursor: 'pointer' }}
                              onClick={() => openConcept(r.concept_id)}
                            >
                              {r.concept_name}
                            </button>
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                          </div>
                          <p className={s.recReason}>{r.reason}</p>
                          <div className={s.recMeta}>
                            约 {r.estimated_minutes} 分钟 · 掌握 {pct(r.mastery_estimate)}
                            {r.blocked_concept_name && ` · 卡住了「${r.blocked_concept_name}」`}
                          </div>
                        </div>
                        <IconButton label={r.suggested_action || '开始'} onClick={() => navigate(recommendationRoute(r))}>
                          <ArrowRight />
                        </IconButton>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </section>
        </div>
      ) : (
        <div className={s.concepts}>
          <section className={`${s.panel} ${s.conceptList}`} aria-label="概念列表">
            <div className={s.conceptTools}>
              <Input
                size="sm"
                prefix={<Search />}
                placeholder="搜索概念"
                aria-label="搜索概念"
                value={query}
                onChange={e => setQuery(e.target.value)}
                suffix={
                  query ? (
                    <IconButton label="清除" size="sm" noTooltip onClick={() => setQuery('')}>
                      <X />
                    </IconButton>
                  ) : undefined
                }
              />
              <Segmented
                size="sm"
                block
                ariaLabel="筛选"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'all', label: '全部' },
                  { value: 'weak', label: '不牢' },
                  { value: 'pending', label: `待确认${ov.pending ? ` ${ov.pending}` : ''}` },
                ]}
              />
            </div>
            <div className={s.conceptScroll}>
              {concepts.isLoading ? (
                <div className={s.skel} style={{ padding: 8 }}>
                  {[0, 1, 2, 3].map(i => (
                    <Skeleton key={i} height={28} />
                  ))}
                </div>
              ) : shown.length === 0 ? (
                <Empty
                  icon={<Network />}
                  title={list.length === 0 ? '还没有概念' : '没有符合条件的概念'}
                  body={list.length === 0 ? '上传资料、记错题或和教练对话时，会自动抽出其中的概念。' : undefined}
                />
              ) : (
                shown.map(c => {
                  const lvl = levelOf(c.mastery, c.review_status === 'confirmed')
                  return (
                    <button
                      key={c.id}
                      type="button"
                      className={s.concept}
                      data-status={c.review_status}
                      aria-current={selected?.id === c.id || undefined}
                      onClick={() => openConcept(c.id)}
                    >
                      <span className={s.swatch} style={{ '--c': levelColor(lvl) } as CSSProperties} aria-hidden />
                      <span className={s.conceptName}>{c.name}</span>
                      <span className={s.conceptValue}>{c.review_status === 'pending' ? '待确认' : c.review_status === 'rejected' ? '' : pct(c.mastery)}</span>
                    </button>
                  )
                })
              )}
            </div>
          </section>

          {selected ? (
            <ConceptDetail
              key={selected.id}
              concept={selected}
              concepts={list}
              onSelect={openConcept}
              onChanged={() => {
                void qc.invalidateQueries({ queryKey: qk.masteryMap })
              }}
              onDeleted={() => {
                const next = new URLSearchParams(params)
                next.delete('concept')
                setParams(next, { replace: true })
              }}
            />
          ) : (
            !concepts.isLoading && <Empty icon={<Network />} title="选一个概念" body="看它的掌握程度、出处和每一条证据。" />
          )}
        </div>
      )}
    </div>
  )
}

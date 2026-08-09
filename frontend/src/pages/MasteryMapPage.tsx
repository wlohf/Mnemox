import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  DatabaseOutlined,
  EditOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import { PageShell } from '../components/PageShell'
import { getApiErrorMessage } from '../services/apiClient'
import { getMasteryMap, type MasteryMapData } from '../services/learningApi'
import {
  applyConceptOverride,
  clearConceptOverride,
  getConceptEvidence,
  getConceptState,
  listLearnerConcepts,
  recomputeConceptState,
  type ConceptState,
  type ConceptSummary,
  type EvidenceCategory,
  type EvidencePage,
} from '../services/learnerModelApi'
import { evidenceCategoryLabel, evidenceTypeLabel, explanationRows } from './learnerModelDisplay'
import { canApplyConceptDetail } from './learnerModelDetailRequest'

const PAGE_SIZE = 10
const EMPTY_EVIDENCE: EvidencePage = { items: [], total: 0, offset: 0, limit: PAGE_SIZE }
const CATEGORY_COLORS: Record<EvidenceCategory, string> = {
  direct: 'green',
  indirect: 'gold',
  manual: 'blue',
  legacy: 'default',
}

function percent(value: number | undefined): number {
  return Math.round(Math.max(0, Math.min(100, Number(value ?? 0))))
}

function formatTime(value?: string | null): string {
  if (!value) return '无记录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export function MasteryMapPage() {
  const navigate = useNavigate()
  const [chapterData, setChapterData] = useState<MasteryMapData | null>(null)
  const [concepts, setConcepts] = useState<ConceptSummary[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [state, setState] = useState<ConceptState | null>(null)
  const [evidence, setEvidence] = useState<EvidencePage>(EMPTY_EVIDENCE)
  const [category, setCategory] = useState<'all' | EvidenceCategory>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideMastery, setOverrideMastery] = useState<number>(0)
  const [overrideConfidence, setOverrideConfidence] = useState<number | null>(null)
  const [overrideRisk, setOverrideRisk] = useState<number | null>(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [mutating, setMutating] = useState(false)
  const activeDetailRequestRef = useRef(0)
  const selectedConceptRef = useRef<number | null>(null)

  const selectConcept = (conceptId: number | null) => {
    selectedConceptRef.current = conceptId
    activeDetailRequestRef.current += 1
    setState(null)
    setEvidence(EMPTY_EVIDENCE)
    setOverrideOpen(false)
    setSelectedId(conceptId)
  }

  const loadOverview = async () => {
    setLoading(true)
    try {
      const [nextConcepts, nextChapters] = await Promise.all([
        listLearnerConcepts(),
        getMasteryMap(),
      ])
      setConcepts(nextConcepts)
      setChapterData(nextChapters)
      const current = selectedConceptRef.current
      const next = current && nextConcepts.some((item) => item.id === current)
        ? current
        : nextConcepts[0]?.id ?? null
      if (next !== current) selectConcept(next)
    } catch (error) {
      message.error(getApiErrorMessage(error, '加载学习者模型失败'))
    } finally {
      setLoading(false)
    }
  }

  const loadDetail = async (conceptId: number, page = 1, nextCategory = category) => {
    const requestId = activeDetailRequestRef.current + 1
    activeDetailRequestRef.current = requestId
    setDetailLoading(true)
    try {
      const [nextState, nextEvidence] = await Promise.all([
        getConceptState(conceptId),
        getConceptEvidence(conceptId, {
          offset: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
          evidenceCategory: nextCategory === 'all' ? undefined : nextCategory,
        }),
      ])
      if (!canApplyConceptDetail(requestId, activeDetailRequestRef.current, conceptId, selectedConceptRef.current)) return
      setState(nextState)
      setEvidence(nextEvidence)
    } catch (error) {
      if (!canApplyConceptDetail(requestId, activeDetailRequestRef.current, conceptId, selectedConceptRef.current)) return
      message.error(getApiErrorMessage(error, '加载概念证据失败'))
    } finally {
      if (canApplyConceptDetail(requestId, activeDetailRequestRef.current, conceptId, selectedConceptRef.current)) {
        setDetailLoading(false)
      }
    }
  }

  useEffect(() => {
    void loadOverview()
  }, [])

  useEffect(() => {
    if (selectedConceptRef.current !== selectedId) {
      selectedConceptRef.current = selectedId
      activeDetailRequestRef.current += 1
      setState(null)
      setEvidence(EMPTY_EVIDENCE)
      setOverrideOpen(false)
    }
    if (selectedId !== null) {
      void loadDetail(selectedId, 1, category)
    } else {
      setDetailLoading(false)
    }
  }, [selectedId])

  const selectedConcept = concepts.find((item) => item.id === selectedId) ?? null
  const filteredConcepts = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    return query ? concepts.filter((item) => item.name.toLocaleLowerCase().includes(query)) : concepts
  }, [concepts, search])

  const overall = useMemo(() => {
    if (concepts.length === 0) return 0
    return percent(concepts.reduce((sum, item) => sum + item.mastery, 0) / concepts.length)
  }, [concepts])

  const openOverride = () => {
    if (selectedId === null || state?.concept_id !== selectedId) return
    setOverrideMastery(percent(state?.mastery_estimate))
    setOverrideConfidence(state ? Number(state.confidence.toFixed(2)) : null)
    setOverrideRisk(state ? Number(state.forgetting_risk.toFixed(2)) : null)
    setOverrideReason('')
    setOverrideOpen(true)
  }

  const refreshSelected = async () => {
    const conceptId = selectedConceptRef.current
    if (conceptId === null) return
    await loadDetail(conceptId, 1, category)
    await loadOverview()
  }

  const applyOverride = async () => {
    const conceptId = selectedId
    if (conceptId === null || state?.concept_id !== conceptId || !overrideReason.trim()) {
      message.warning('请填写修正原因')
      return
    }
    setMutating(true)
    try {
      await applyConceptOverride(conceptId, {
        mastery_estimate: overrideMastery,
        confidence: overrideConfidence ?? undefined,
        forgetting_risk: overrideRisk ?? undefined,
        reason: overrideReason.trim(),
      })
      setOverrideOpen(false)
      await refreshSelected()
      message.success('人工修正已生效')
    } catch (error) {
      message.error(getApiErrorMessage(error, '人工修正失败'))
    } finally {
      setMutating(false)
    }
  }

  const clearOverride = async () => {
    const conceptId = selectedId
    if (conceptId === null || state?.concept_id !== conceptId) return
    setMutating(true)
    try {
      await clearConceptOverride(conceptId, '用户从证据面板撤销人工修正')
      await refreshSelected()
      message.success('人工修正已撤销')
    } catch (error) {
      message.error(getApiErrorMessage(error, '撤销人工修正失败'))
    } finally {
      setMutating(false)
    }
  }

  const recompute = async () => {
    const conceptId = selectedId
    if (conceptId === null || state?.concept_id !== conceptId) return
    setMutating(true)
    try {
      await recomputeConceptState(conceptId)
      await refreshSelected()
      message.success('概念状态已重算')
    } catch (error) {
      message.error(getApiErrorMessage(error, '概念重算失败'))
    } finally {
      setMutating(false)
    }
  }

  const conceptPanel = (
    <div className="mnemox-learner-workbench">
      <section className="mnemox-learner-concepts">
        <div className="mnemox-panel-heading">
          <span>概念</span>
          <Tag>{concepts.length}</Tag>
        </div>
        <div className="mnemox-learner-search">
          <Input.Search value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索概念" allowClear />
        </div>
        <div className="mnemox-learner-concept-list">
          {filteredConcepts.map((concept) => (
            <button
              type="button"
              key={concept.id}
              className={`mnemox-learner-concept${selectedId === concept.id ? ' is-active' : ''}`}
              onClick={() => {
                setCategory('all')
                selectConcept(concept.id)
              }}
            >
              <span>
                <strong>{concept.name}</strong>
                <small>{concept.link_count} 个关联</small>
              </span>
              <b>{percent(concept.mastery)}%</b>
            </button>
          ))}
          {!loading && filteredConcepts.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </div>
      </section>

      <section className="mnemox-learner-state">
        <div className="mnemox-panel-heading">
          <span>{selectedConcept?.name ?? '概念状态'}</span>
          <Space size={4}>
            <Tooltip title="重算状态"><Button type="text" icon={<SyncOutlined />} loading={mutating} onClick={() => void recompute()} disabled={state?.concept_id !== selectedId} /></Tooltip>
            <Tooltip title="人工修正"><Button type="text" icon={<EditOutlined />} onClick={openOverride} disabled={state?.concept_id !== selectedId} /></Tooltip>
          </Space>
        </div>
        <Skeleton active loading={detailLoading && !state}>
          {state ? (
            <>
              <div className="mnemox-learner-metrics">
                <div><ExperimentOutlined /><span>掌握度</span><strong>{percent(state.mastery_estimate)}%</strong><Progress percent={percent(state.mastery_estimate)} showInfo={false} size="small" /></div>
                <div><SafetyCertificateOutlined /><span>置信度</span><strong>{percent(state.confidence * 100)}%</strong><Progress percent={percent(state.confidence * 100)} showInfo={false} size="small" /></div>
                <div><HistoryOutlined /><span>遗忘风险</span><strong>{percent(state.forgetting_risk * 100)}%</strong><Progress percent={percent(state.forgetting_risk * 100)} showInfo={false} status={state.forgetting_risk > 0.65 ? 'exception' : 'normal'} size="small" /></div>
                <div><DatabaseOutlined /><span>模型版本</span><strong className="mnemox-model-version">{state.model_version}</strong><small>可靠度 {percent(state.reliability * 100)}%</small></div>
              </div>
              <div className="mnemox-learner-explanation">
                <h3>结果依据</h3>
                {explanationRows(state.explanation_summary).map(([label, value]) => (
                  <div key={label}><span>{label}</span><strong>{value}</strong></div>
                ))}
                <div><span>最近证据</span><strong>{formatTime(state.last_evidence_at)}</strong></div>
                <div><span>最近复习</span><strong>{formatTime(state.last_reviewed_at)}</strong></div>
              </div>
              {state.manual_override?.active && (
                <div className="mnemox-learner-override">
                  <div><Tag color="blue">人工修正生效中</Tag><span>{state.manual_override.reason}</span></div>
                  <Button size="small" danger loading={mutating} onClick={() => void clearOverride()}>撤销</Button>
                </div>
              )}
            </>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个概念" />}
        </Skeleton>
      </section>

      <section className="mnemox-learner-evidence">
        <div className="mnemox-panel-heading">
          <span>证据历史</span>
          <Tag>{evidence.total}</Tag>
        </div>
        <div className="mnemox-learner-filter">
          <Segmented
            block
            value={category}
            options={[
              { label: '全部', value: 'all' },
              { label: '直接', value: 'direct' },
              { label: '间接', value: 'indirect' },
              { label: '人工', value: 'manual' },
              { label: '旧版', value: 'legacy' },
            ]}
            onChange={(value) => {
              const next = value as 'all' | EvidenceCategory
              setCategory(next)
              if (selectedId !== null) void loadDetail(selectedId, 1, next)
            }}
          />
        </div>
        <List
          loading={detailLoading}
          dataSource={evidence.items}
          locale={{ emptyText: '暂无证据' }}
          renderItem={(item) => (
            <List.Item className="mnemox-evidence-item">
              <div className="mnemox-evidence-main">
                <div>
                  <Tag color={CATEGORY_COLORS[item.evidence_category]}>{evidenceCategoryLabel(item.evidence_category)}</Tag>
                  <strong>{evidenceTypeLabel(item.evidence_type)}</strong>
                </div>
                <Progress percent={percent(item.score * 100)} size="small" />
                <small>{item.source_type} · 可靠度 {percent(item.reliability * 100)}% · {formatTime(item.observed_at)}</small>
                <small>{item.model_version}</small>
              </div>
            </List.Item>
          )}
        />
        {evidence.total > PAGE_SIZE && (
          <Pagination
            size="small"
            current={Math.floor(evidence.offset / evidence.limit) + 1}
            pageSize={evidence.limit}
            total={evidence.total}
            showSizeChanger={false}
            onChange={(page) => selectedId !== null && void loadDetail(selectedId, page, category)}
          />
        )}
      </section>
    </div>
  )

  const chapterPanel = (
    <div className="mnemox-mastery-chapters">
      <section>
        <div className="mnemox-panel-heading"><span>总体掌握度</span><strong>{overall}%</strong></div>
        <div className="mnemox-mastery-overall"><Progress percent={overall} /></div>
      </section>
      <section>
        <div className="mnemox-panel-heading"><span>资料掌握分布</span></div>
        <List
          dataSource={chapterData?.materials ?? []}
          locale={{ emptyText: '暂无章节数据' }}
          renderItem={(material) => (
            <List.Item>
              <div className="mnemox-mastery-material">
                <div><strong>{material.material_title}</strong><Tag>{percent(material.average_mastery)}%</Tag></div>
                <Progress percent={percent(material.average_mastery)} />
              </div>
            </List.Item>
          )}
        />
      </section>
      <section>
        <div className="mnemox-panel-heading"><span>薄弱点</span></div>
        <List
          dataSource={chapterData?.weak_points ?? []}
          locale={{ emptyText: '暂无明显薄弱点' }}
          renderItem={(item) => (
            <List.Item><div><strong>{item.chapter_title}</strong><small>{item.material_title} · {percent(item.mastery_level)}%</small></div></List.Item>
          )}
        />
      </section>
    </div>
  )

  return (
    <PageShell
      title="学习者模型"
      onBack={() => navigate('/')}
      maxWidth={1480}
      rightExtra={<Tooltip title="刷新"><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void refreshSelected()} /></Tooltip>}
    >
      <Tabs
        defaultActiveKey="concepts"
        items={[
          { key: 'concepts', label: '概念证据', children: conceptPanel },
          { key: 'chapters', label: '章节分布', children: chapterPanel },
        ]}
      />

      <Modal
        title={`人工修正 · ${selectedConcept?.name ?? ''}`}
        open={overrideOpen}
        confirmLoading={mutating}
        onOk={() => void applyOverride()}
        onCancel={() => setOverrideOpen(false)}
        okText="应用修正"
      >
        <div className="mnemox-override-form">
          <label><span>掌握度</span><InputNumber min={0} max={100} value={overrideMastery} onChange={(value) => setOverrideMastery(Number(value ?? 0))} suffix="%" /></label>
          <label><span>置信度</span><InputNumber min={0} max={1} step={0.05} value={overrideConfidence} onChange={(value) => setOverrideConfidence(value === null ? null : Number(value))} /></label>
          <label><span>遗忘风险</span><InputNumber min={0} max={1} step={0.05} value={overrideRisk} onChange={(value) => setOverrideRisk(value === null ? null : Number(value))} /></label>
          <label><span>修正原因</span><Input.TextArea value={overrideReason} maxLength={500} rows={3} onChange={(event) => setOverrideReason(event.target.value)} /></label>
        </div>
      </Modal>
    </PageShell>
  )
}

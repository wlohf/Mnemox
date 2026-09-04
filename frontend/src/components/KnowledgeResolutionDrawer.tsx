import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Drawer,
  List,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  CheckOutlined,
  PlusOutlined,
  StopOutlined,
  TagsOutlined,
} from '@ant-design/icons'

import { getApiErrorMessage } from '../services/apiClient'
import {
  listResolutionCandidates,
  resolveKnowledgeCandidate,
  type ResolutionAction,
  type ResolutionCandidate,
} from '../services/knowledgeApi'
import { listLearnerConcepts, type ConceptSummary } from '../services/learnerModelApi'


interface KnowledgeResolutionDrawerProps {
  open: boolean
  materialId?: number | null
  materialTitle?: string | null
  onClose: () => void
  onResolved?: () => void | Promise<void>
}

const relationLabels: Record<ResolutionCandidate['relation_type'], string> = {
  about: '主题',
  uses: '使用',
  applies_to: '适用于',
  exemplifies: '例证',
}

export default function KnowledgeResolutionDrawer({
  open,
  materialId,
  materialTitle,
  onClose,
  onResolved,
}: KnowledgeResolutionDrawerProps) {
  const navigate = useNavigate()
  const [candidates, setCandidates] = useState<ResolutionCandidate[]>([])
  const [concepts, setConcepts] = useState<ConceptSummary[]>([])
  const [selectedConcepts, setSelectedConcepts] = useState<Record<number, number | undefined>>({})
  const [loading, setLoading] = useState(false)
  const [busyCandidateId, setBusyCandidateId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const loadQueue = useCallback(async () => {
    if (!open) return
    setLoading(true)
    setLoadError(null)
    try {
      const [nextCandidates, nextConcepts] = await Promise.all([
        listResolutionCandidates({
          sourceType: materialId ? 'material' : undefined,
          sourceId: materialId ?? undefined,
          limit: 100,
        }),
        listLearnerConcepts(500),
      ])
      setCandidates(nextCandidates)
      setConcepts(nextConcepts.filter((concept) => concept.review_status === 'confirmed'))
      setSelectedConcepts(Object.fromEntries(
        nextCandidates.map((candidate) => [candidate.id, candidate.candidate_concept_id ?? undefined]),
      ))
    } catch (error) {
      setLoadError(getApiErrorMessage(error, '解析候选加载失败，请重试'))
    } finally {
      setLoading(false)
    }
  }, [materialId, open])

  useEffect(() => {
    void loadQueue()
  }, [loadQueue])

  const conceptOptions = useMemo(() => concepts.map((concept) => ({
    value: concept.id,
    label: concept.name,
  })), [concepts])

  const decide = async (candidate: ResolutionCandidate, action: ResolutionAction) => {
    const conceptId = selectedConcepts[candidate.id]
    if ((action === 'link' || action === 'link_add_alias') && !conceptId) {
      message.warning('请先选择要关联的概念')
      return
    }
    setBusyCandidateId(candidate.id)
    try {
      await resolveKnowledgeCandidate(candidate.id, {
        action,
        concept_id: conceptId,
        concept_name: action === 'create_new' ? candidate.mention_text : undefined,
      })
      setCandidates((current) => current.filter((item) => item.id !== candidate.id))
      message.success(
        action === 'reject'
          ? '已忽略该概念提及'
          : action === 'create_new'
            ? '已创建概念并完成关联'
            : '概念关联已确认',
      )
      await onResolved?.()
    } catch (error) {
      message.error(getApiErrorMessage(error, '解析操作失败，请重试'))
    } finally {
      setBusyCandidateId(null)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width="min(520px, 100vw)"
      title="概念解析"
      extra={<Tag color={candidates.length > 0 ? 'gold' : 'green'}>{candidates.length} 项待确认</Tag>}
      styles={{ body: { padding: '20px 24px' } }}
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 20 }}>
        {materialTitle ? `核对《${materialTitle}》中抽取到的概念提及。` : '核对抽取到的概念提及。'}
        语义相似只提供建议，确认前不会合并或改写概念。
      </Typography.Paragraph>
      <Button
        type="link"
        size="small"
        icon={<ApartmentOutlined />}
        onClick={() => {
          onClose()
          navigate('/mastery')
        }}
        style={{ padding: 0, marginBottom: 16 }}
      >
        合并重复概念
      </Button>

      {loadError && (
        <Alert
          type="error"
          showIcon
          message="无法加载解析候选"
          description={loadError}
          action={<Button size="small" onClick={() => void loadQueue()}>重试</Button>}
          style={{ marginBottom: 16 }}
        />
      )}

      <List
        loading={loading}
        dataSource={candidates}
        locale={{ emptyText: loadError ? '修复连接后重试' : '当前没有待确认的概念提及' }}
        renderItem={(candidate) => {
          const busy = busyCandidateId === candidate.id
          const score = Math.round((candidate.scores?.combined ?? 0) * 100)
          return (
            <List.Item style={{ padding: '18px 0', alignItems: 'stretch' }}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Space size={8} wrap>
                  <Typography.Text strong style={{ fontSize: 15 }}>{candidate.mention_text}</Typography.Text>
                  <Tag>{relationLabels[candidate.relation_type]}</Tag>
                  {candidate.candidate_concept_name && (
                    <Tag color="blue" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      建议 {candidate.candidate_concept_name} · {score}%
                    </Tag>
                  )}
                </Space>

                <Typography.Paragraph
                  style={{ margin: 0, color: 'var(--text-secondary)', lineHeight: 1.65 }}
                  ellipsis={{ rows: 3, expandable: true, symbol: '展开原句' }}
                >
                  {candidate.claim_statement || candidate.mention_context}
                </Typography.Paragraph>

                <Select
                  showSearch
                  allowClear
                  value={selectedConcepts[candidate.id]}
                  options={conceptOptions}
                  optionFilterProp="label"
                  placeholder="搜索已有概念"
                  disabled={busy}
                  onChange={(value) => setSelectedConcepts((current) => ({
                    ...current,
                    [candidate.id]: value,
                  }))}
                  style={{ width: '100%' }}
                  aria-label={`为 ${candidate.mention_text} 选择已有概念`}
                />

                <Space size={8} wrap>
                  <Button
                    type="primary"
                    size="small"
                    icon={<CheckOutlined />}
                    loading={busy}
                    disabled={!selectedConcepts[candidate.id]}
                    onClick={() => void decide(candidate, 'link')}
                  >
                    仅关联本次
                  </Button>
                  <Button
                    size="small"
                    icon={<TagsOutlined />}
                    disabled={busy || !selectedConcepts[candidate.id]}
                    onClick={() => void decide(candidate, 'link_add_alias')}
                  >
                    关联并设为别名
                  </Button>
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    disabled={busy}
                    onClick={() => void decide(candidate, 'create_new')}
                  >
                    新建“{candidate.mention_text}”
                  </Button>
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<StopOutlined />}
                    disabled={busy}
                    onClick={() => void decide(candidate, 'reject')}
                  >
                    忽略
                  </Button>
                </Space>
              </Space>
            </List.Item>
          )
        }}
      />
    </Drawer>
  )
}

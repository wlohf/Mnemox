import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Input,
  Layout,
  List,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  CheckOutlined,
  CloudUploadOutlined,
  ExperimentOutlined,
  LinkOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  SyncOutlined,
} from '@ant-design/icons'

import KnowledgeResolutionDrawer from '../components/KnowledgeResolutionDrawer'
import { getApiErrorMessage } from '../services/apiClient'
import { rebuildKnowledgeProjection } from '../services/knowledgeApi'
import {
  getExtractionRun,
  getKnowledgeLabStatus,
  getMaterialClaims,
  getMaterialExtraction,
  listLabConcepts,
  listLabMaterials,
  reviewLabClaim,
  runLabAssociation,
  runLabKnowledgePath,
  startMaterialExtraction,
  uploadLabMaterial,
  type AssociationItem,
  type AssociationResponse,
  type ExtractionRun,
  type KnowledgeLabMaterial,
  type KnowledgeLabStatus,
  type KnowledgePathResponse,
  type LabClaim,
  type LabConcept,
  type MaterialClaimSnapshot,
  type MaterialExtractionSummary,
} from '../services/knowledgeLabApi'

const { Header, Content } = Layout
const { Text, Title, Paragraph } = Typography
const TERMINAL_EXTRACTION = new Set(['succeeded', 'partial', 'failed', 'cancelled'])

function statusTag(status?: string | null) {
  const value = String(status || 'unknown')
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: 'gold', label: '待审核' },
    confirmed: { color: 'green', label: '已确认' },
    rejected: { color: 'red', label: '已拒绝' },
    queued: { color: 'blue', label: '排队中' },
    running: { color: 'processing', label: '抽取中' },
    succeeded: { color: 'success', label: '完成' },
    partial: { color: 'warning', label: '部分完成' },
    failed: { color: 'error', label: '失败' },
    cancelled: { color: 'default', label: '已取消' },
    not_registered: { color: 'default', label: '未登记' },
    not_started: { color: 'default', label: '未开始' },
    disabled: { color: 'default', label: '未启用' },
  }
  const resolved = map[value] ?? { color: 'default', label: value }
  return <Tag color={resolved.color}>{resolved.label}</Tag>
}

function learningStatusTag(status: string) {
  if (status === 'mastered') return <Tag color="green">已掌握</Tag>
  if (status === 'weak') return <Tag color="orange">薄弱</Tag>
  return <Tag>未学习</Tag>
}

function renderAssociation(item: AssociationItem) {
  return (
    <Card key={item.related.claim_id} size="small" style={{ marginBottom: 12 }}>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="blue">{item.relation}</Tag>
          <Tag>score {item.score.toFixed(3)}</Tag>
          <Tag>confidence {item.confidence.toFixed(3)}</Tag>
          {item.inferred && <Tag color="purple">推断关联</Tag>}
        </Space>
        <Text strong>{item.related.claim}</Text>
        <Text type="secondary">来源：{item.related.source_title || `${item.related.source_type}:${item.related.source_id}`}</Text>
        {item.shared_structure && <Text>共同结构：{item.shared_structure}</Text>}
        {item.evidence.related.slice(0, 2).map((evidence) => (
          <blockquote
            key={evidence.evidence_key}
            style={{ margin: 0, padding: '8px 12px', borderLeft: '3px solid var(--border-light)' }}
          >
            <Text type="secondary">{evidence.excerpt}</Text>
          </blockquote>
        ))}
        {item.explanation && (
          <Alert
            type="info"
            showIcon
            message="Multi-hop explanation"
            description={(
              <Space direction="vertical" size={4}>
                <Text>{item.explanation.summary}</Text>
                <Space wrap>
                  {item.explanation.steps.map((step, index) => {
                    if (step.type === 'concept') return <Tag key={index} color="geekblue">{String(step.name)}</Tag>
                    if (step.type === 'relation') return <Tag key={index} color="purple">{String(step.relation_type)}</Tag>
                    return <Tag key={index}>{String(step.label || step.type)}</Tag>
                  })}
                </Space>
              </Space>
            )}
          />
        )}
      </Space>
    </Card>
  )
}

export function KnowledgeLabPage() {
  const navigate = useNavigate()
  const [materials, setMaterials] = useState<KnowledgeLabMaterial[]>([])
  const [selectedMaterialId, setSelectedMaterialId] = useState<number | undefined>()
  const [status, setStatus] = useState<KnowledgeLabStatus | null>(null)
  const [extraction, setExtraction] = useState<MaterialExtractionSummary | null>(null)
  const [activeRun, setActiveRun] = useState<ExtractionRun | null>(null)
  const [snapshot, setSnapshot] = useState<MaterialClaimSnapshot | null>(null)
  const [concepts, setConcepts] = useState<LabConcept[]>([])
  const [claimFilter, setClaimFilter] = useState<'all' | 'pending' | 'confirmed' | 'rejected'>('all')
  const [initialLoading, setInitialLoading] = useState(true)
  const [materialLoading, setMaterialLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [reviewingClaimId, setReviewingClaimId] = useState<number | null>(null)
  const [resolutionOpen, setResolutionOpen] = useState(false)
  const [associationText, setAssociationText] = useState('')
  const [associationWithMaterial, setAssociationWithMaterial] = useState(true)
  const [associationResult, setAssociationResult] = useState<AssociationResponse | null>(null)
  const [associationLoading, setAssociationLoading] = useState(false)
  const [pathStarts, setPathStarts] = useState<number[]>([])
  const [pathTarget, setPathTarget] = useState<number | undefined>()
  const [pathResult, setPathResult] = useState<KnowledgePathResponse | null>(null)
  const [pathLoading, setPathLoading] = useState(false)
  const [projectionBusy, setProjectionBusy] = useState(false)

  const selectedMaterial = useMemo(
    () => materials.find((item) => item.id === selectedMaterialId) ?? null,
    [materials, selectedMaterialId],
  )
  const confirmedConcepts = useMemo(
    () => concepts.filter((item) => item.review_status === 'confirmed'),
    [concepts],
  )

  const refreshGlobal = useCallback(async () => {
    const [nextStatus, nextMaterials, nextConcepts] = await Promise.all([
      getKnowledgeLabStatus(),
      listLabMaterials(),
      listLabConcepts(),
    ])
    setStatus(nextStatus)
    setMaterials(nextMaterials)
    setConcepts(nextConcepts)
    setSelectedMaterialId((current) => current ?? nextMaterials[0]?.id)
  }, [])

  const refreshMaterial = useCallback(async (materialId: number, filter = claimFilter) => {
    setMaterialLoading(true)
    try {
      const [nextExtraction, nextSnapshot] = await Promise.all([
        getMaterialExtraction(materialId),
        getMaterialClaims(materialId, filter),
      ])
      setExtraction(nextExtraction)
      setSnapshot(nextSnapshot)
      const latestRun = (nextExtraction.runs ?? [])[0] ?? null
      setActiveRun((current) => current && !TERMINAL_EXTRACTION.has(current.status) ? current : latestRun)
    } catch (error) {
      message.error(getApiErrorMessage(error, '资料知识状态加载失败'))
    } finally {
      setMaterialLoading(false)
    }
  }, [claimFilter])

  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      setInitialLoading(true)
      try {
        await refreshGlobal()
      } catch (error) {
        if (!cancelled) message.error(getApiErrorMessage(error, 'Knowledge Lab 初始化失败'))
      } finally {
        if (!cancelled) setInitialLoading(false)
      }
    }
    void boot()
    return () => { cancelled = true }
  }, [refreshGlobal])

  useEffect(() => {
    if (!selectedMaterialId) {
      setExtraction(null)
      setSnapshot(null)
      return
    }
    void refreshMaterial(selectedMaterialId)
  }, [refreshMaterial, selectedMaterialId])

  useEffect(() => {
    const runId = activeRun?.id
    if (!runId || TERMINAL_EXTRACTION.has(activeRun.status)) return
    const timer = window.setInterval(() => {
      void getExtractionRun(runId)
        .then(async (next) => {
          setActiveRun(next)
          if (TERMINAL_EXTRACTION.has(next.status) && selectedMaterialId) {
            await Promise.all([refreshMaterial(selectedMaterialId), refreshGlobal()])
          }
        })
        .catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [activeRun?.id, activeRun?.status, refreshGlobal, refreshMaterial, selectedMaterialId])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const uploaded = await uploadLabMaterial(file)
      message.success(uploaded.duplicate ? '资料已存在，已复用现有记录' : '资料上传成功')
      await refreshGlobal()
      setSelectedMaterialId(uploaded.id)
    } catch (error) {
      message.error(getApiErrorMessage(error, '资料上传失败'))
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleExtract = async () => {
    if (!selectedMaterialId) return
    setExtracting(true)
    try {
      const run = await startMaterialExtraction(selectedMaterialId)
      setActiveRun(run)
      message.success(`已创建 ${run.extractor_type} 抽取任务`)
      await refreshMaterial(selectedMaterialId)
    } catch (error) {
      message.error(getApiErrorMessage(error, '抽取任务创建失败'))
    } finally {
      setExtracting(false)
    }
  }

  const handleReview = async (claim: LabClaim, nextStatus: 'confirmed' | 'rejected') => {
    if (!selectedMaterialId) return
    setReviewingClaimId(claim.id)
    try {
      await reviewLabClaim(claim.id, nextStatus)
      message.success(nextStatus === 'confirmed' ? 'Claim 已确认' : 'Claim 已拒绝')
      await Promise.all([
        refreshMaterial(selectedMaterialId),
        refreshGlobal(),
      ])
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Claim 审核失败'))
    } finally {
      setReviewingClaimId(null)
    }
  }

  const handleRebuildProjection = async () => {
    setProjectionBusy(true)
    try {
      await rebuildKnowledgeProjection(true)
      message.success('已重新排队 Knowledge Projection；完成后再刷新 Runtime 状态')
      window.setTimeout(() => { void refreshGlobal() }, 1200)
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Projection 重建排队失败'))
    } finally {
      setProjectionBusy(false)
    }
  }

  const handleAssociation = async () => {
    const text = associationText.trim()
    if (!text) {
      message.warning('先输入一个想测试的联想问题或文本')
      return
    }
    setAssociationLoading(true)
    setAssociationResult(null)
    try {
      const result = await runLabAssociation({
        text,
        source_type: associationWithMaterial && selectedMaterialId ? 'material' : undefined,
        source_id: associationWithMaterial ? selectedMaterialId : undefined,
        limit: 5,
      })
      setAssociationResult(result)
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Association V2 查询失败'))
    } finally {
      setAssociationLoading(false)
    }
  }

  const handlePath = async () => {
    if (!pathStarts.length || !pathTarget) {
      message.warning('请选择至少一个起点 Concept 和一个目标 Concept')
      return
    }
    setPathLoading(true)
    setPathResult(null)
    try {
      setPathResult(await runLabKnowledgePath({
        start_concept_ids: pathStarts,
        target_concept_id: pathTarget,
        max_depth: 6,
        relation_types: ['prerequisite_of'],
        limit: 3,
      }))
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Knowledge Path 查询失败'))
    } finally {
      setPathLoading(false)
    }
  }

  const graphRuntime = status?.graph_runtime ?? null
  const graphBackend = String(
    graphRuntime?.effective_backend
      ?? graphRuntime?.selected_backend
      ?? graphRuntime?.configured_backend
      ?? 'sql',
  )
  const projectionCaughtUp = Boolean(graphRuntime?.projection?.caught_up)
  const graphPrimaryReady = Boolean(graphRuntime?.primary_ready)
  const graphServingReady = Boolean(graphRuntime?.serving_ready)
  const extractionStatus = activeRun?.status ?? extraction?.status ?? 'not_started'

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
      <Header
        style={{
          height: 64,
          padding: '0 24px',
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-light)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回工作台</Button>
          <Divider type="vertical" />
          <ExperimentOutlined />
          <Text strong>Knowledge Lab</Text>
          <Tag color="purple">Dogfooding</Tag>
        </Space>
        <Space>
          <Button icon={<SyncOutlined />} loading={projectionBusy} onClick={handleRebuildProjection}>重建 Projection</Button>
          <Button icon={<ReloadOutlined />} onClick={() => void refreshGlobal()}>刷新 Runtime</Button>
        </Space>
      </Header>

      <Content style={{ padding: 24 }}>
        <div style={{ maxWidth: 1480, margin: '0 auto' }}>
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            <div>
              <Title level={2} style={{ marginBottom: 6 }}>真实笔记知识图实验台</Title>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                从资料导入一路检查到 Claim、Concept、Association 和 Knowledge Path。这里展示的是实际产品数据，不是独立 Demo 数据库。
              </Paragraph>
            </div>

            {!status?.enabled && !initialLoading && (
              <Alert
                type="warning"
                showIcon
                message="Knowledge V2 当前未启用"
                description="云端 dogfooding 需要在服务端开启 KNOWLEDGE_V2_ENABLED；Association/Knowledge Path 还需要对应 feature flag。"
              />
            )}

            <Card loading={initialLoading} title={<Space><SafetyCertificateOutlined />Runtime / Readiness</Space>}>
              <Row gutter={[16, 16]}>
                <Col xs={12} md={6}><Statistic title="Sources" value={status?.counts.sources ?? 0} /></Col>
                <Col xs={12} md={6}><Statistic title="Claims" value={status?.counts.claims ?? 0} /></Col>
                <Col xs={12} md={6}><Statistic title="Confirmed Links" value={status?.counts.confirmed_claim_links ?? 0} /></Col>
                <Col xs={12} md={6}><Statistic title="Pending Resolution" value={status?.counts.pending_resolution ?? 0} /></Col>
              </Row>
              <Divider />
              <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
                <Descriptions.Item label="Knowledge V2">{status?.enabled ? <Tag color="green">ON</Tag> : <Tag>OFF</Tag>}</Descriptions.Item>
                <Descriptions.Item label="Graph backend"><Tag color={graphBackend === 'neo4j' ? 'geekblue' : 'default'}>{graphBackend}</Tag></Descriptions.Item>
                <Descriptions.Item label="Primary ready">{graphPrimaryReady ? <Tag color="green">YES</Tag> : <Tag color="orange">NO</Tag>}</Descriptions.Item>
                <Descriptions.Item label="Serving ready">{graphServingReady ? <Tag color="green">YES</Tag> : <Tag color="orange">NO</Tag>}</Descriptions.Item>
                <Descriptions.Item label="Projection caught-up">{projectionCaughtUp ? <Tag color="green">YES</Tag> : <Tag color="gold">NO / N/A</Tag>}</Descriptions.Item>
              </Descriptions>
              {graphBackend !== 'neo4j' && (
                <Alert
                  style={{ marginTop: 12 }}
                  type="info"
                  showIcon
                  message="Association 可以继续使用 SQL；Knowledge Path 是 graph-native 能力，云端测试时建议启用 Optional Neo4j backend。"
                />
              )}
            </Card>

            <Row gutter={[20, 20]}>
              <Col xs={24} lg={8}>
                <Card title={<Space><CloudUploadOutlined />1. 导入与抽取</Space>}>
                  <Upload.Dragger
                    accept=".md,.txt,.pdf,.docx"
                    showUploadList={false}
                    disabled={uploading}
                    beforeUpload={(file) => { void handleUpload(file as File); return false }}
                  >
                    <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
                    <p className="ant-upload-text">拖入你的技术笔记</p>
                    <p className="ant-upload-hint">支持 Markdown / TXT / PDF / DOCX</p>
                  </Upload.Dragger>
                  <Divider />
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Text type="secondary">当前资料</Text>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      style={{ width: '100%' }}
                      placeholder="选择一篇资料"
                      value={selectedMaterialId}
                      onChange={(value) => {
                        setSelectedMaterialId(value)
                        setAssociationResult(null)
                        setPathResult(null)
                      }}
                      options={materials.map((item) => ({
                        value: item.id,
                        label: item.title,
                      }))}
                    />
                    <Space wrap>
                      <Button type="primary" loading={extracting} disabled={!selectedMaterialId || !status?.enabled} onClick={handleExtract}>
                        开始 / 重新抽取
                      </Button>
                      <Button
                        disabled={!selectedMaterialId}
                        loading={materialLoading}
                        onClick={() => selectedMaterialId && void refreshMaterial(selectedMaterialId)}
                      >
                        刷新
                      </Button>
                    </Space>
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="抽取状态">{statusTag(extractionStatus)}</Descriptions.Item>
                      <Descriptions.Item label="Extractor">{activeRun?.extractor_type ?? extraction?.runs?.[0]?.extractor_type ?? '-'}</Descriptions.Item>
                      <Descriptions.Item label="Pending Claims">{extraction?.pending_claim_count ?? snapshot?.counts.pending ?? 0}</Descriptions.Item>
                      <Descriptions.Item label="Pending Resolution">{extraction?.pending_resolution_count ?? 0}</Descriptions.Item>
                    </Descriptions>
                    {activeRun && !TERMINAL_EXTRACTION.has(activeRun.status) && <Progress percent={60} status="active" showInfo={false} />}
                  </Space>
                </Card>
              </Col>

              <Col xs={24} lg={16}>
                <Card
                  loading={materialLoading}
                  title={<Space><CheckOutlined />2. Claim + Evidence 审核</Space>}
                  extra={(
                    <Space wrap>
                      <Select
                        size="small"
                        value={claimFilter}
                        onChange={(value) => {
                          setClaimFilter(value)
                          if (selectedMaterialId) void refreshMaterial(selectedMaterialId, value)
                        }}
                        options={[
                          { value: 'all', label: '全部' },
                          { value: 'pending', label: '待审核' },
                          { value: 'confirmed', label: '已确认' },
                          { value: 'rejected', label: '已拒绝' },
                        ]}
                      />
                      <Button
                        icon={<ApartmentOutlined />}
                        disabled={!selectedMaterialId}
                        onClick={() => setResolutionOpen(true)}
                      >
                        Concept Resolution
                      </Button>
                    </Space>
                  )}
                >
                  {snapshot && (
                    <Space wrap style={{ marginBottom: 12 }}>
                      <Tag>总计 {snapshot.counts.total}</Tag>
                      <Tag color="gold">待审核 {snapshot.counts.pending}</Tag>
                      <Tag color="green">确认 {snapshot.counts.confirmed}</Tag>
                      <Tag color="red">拒绝 {snapshot.counts.rejected}</Tag>
                      {snapshot.truncated && <Tag color="orange">当前列表已截断</Tag>}
                    </Space>
                  )}
                  <List
                    dataSource={snapshot?.claims ?? []}
                    locale={{ emptyText: <Empty description={selectedMaterialId ? '这篇资料还没有可展示的 Claim' : '先选择资料'} /> }}
                    renderItem={(claim) => (
                      <List.Item
                        key={claim.id}
                        actions={claim.review_status === 'pending' ? [
                          <Button
                            key="confirm"
                            size="small"
                            type="primary"
                            icon={<CheckOutlined />}
                            loading={reviewingClaimId === claim.id}
                            onClick={() => void handleReview(claim, 'confirmed')}
                          >确认</Button>,
                          <Button
                            key="reject"
                            size="small"
                            danger
                            icon={<StopOutlined />}
                            loading={reviewingClaimId === claim.id}
                            onClick={() => void handleReview(claim, 'rejected')}
                          >拒绝</Button>,
                        ] : undefined}
                      >
                        <List.Item.Meta
                          title={(
                            <Space wrap>
                              {statusTag(claim.review_status)}
                              <Tag>{claim.claim_kind}</Tag>
                              <Text strong>{claim.statement}</Text>
                            </Space>
                          )}
                          description={(
                            <Space direction="vertical" size={6} style={{ width: '100%' }}>
                              <Text type="secondary">confidence {claim.confidence.toFixed(3)} · {claim.derivation_type}</Text>
                              {claim.concepts.length > 0 && (
                                <Space wrap>
                                  {claim.concepts.map((concept) => (
                                    <Tag key={concept.link_id} color={concept.review_status === 'confirmed' ? 'geekblue' : 'default'}>
                                      {concept.name} · {concept.relation_type}
                                    </Tag>
                                  ))}
                                </Space>
                              )}
                              {claim.evidence.map((evidence) => (
                                <blockquote
                                  key={evidence.id}
                                  style={{ margin: 0, padding: '8px 12px', borderLeft: '3px solid var(--border-light)' }}
                                >
                                  <Text>{evidence.excerpt}</Text><br />
                                  <Text type="secondary">Evidence {evidence.grounding_method} · {evidence.confidence.toFixed(3)}</Text>
                                </blockquote>
                              ))}
                              {claim.evidence.length === 0 && <Alert type="warning" message="没有 Evidence，不能确认这个 Claim" />}
                            </Space>
                          )}
                        />
                      </List.Item>
                    )}
                  />
                </Card>
              </Col>
            </Row>

            <Card title={<Space><ApartmentOutlined />3. Concept inventory / Learning Path</Space>}>
              <Row gutter={[20, 20]}>
                <Col xs={24} lg={8}>
                  <Statistic title="Confirmed Concepts" value={confirmedConcepts.length} />
                  <Paragraph type="secondary" style={{ marginTop: 8 }}>
                    先完成 Claim 审核和 Concept Resolution，再用已确认 Concept 测试先修路径。
                  </Paragraph>
                  <Space wrap>
                    {confirmedConcepts.slice(0, 16).map((concept) => (
                      <Tag key={concept.id} color="geekblue">{concept.name} · {concept.mastery.toFixed(0)}</Tag>
                    ))}
                  </Space>
                </Col>
                <Col xs={24} lg={16}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Select
                      mode="multiple"
                      maxTagCount="responsive"
                      showSearch
                      optionFilterProp="label"
                      placeholder="起点 Concept（你已掌握/想从这里开始）"
                      value={pathStarts}
                      onChange={setPathStarts}
                      options={confirmedConcepts.map((concept) => ({ value: concept.id, label: concept.name }))}
                    />
                    <Select
                      showSearch
                      allowClear
                      optionFilterProp="label"
                      placeholder="目标 Concept"
                      value={pathTarget}
                      onChange={setPathTarget}
                      options={confirmedConcepts.map((concept) => ({ value: concept.id, label: concept.name }))}
                    />
                    <Button type="primary" icon={<LinkOutlined />} loading={pathLoading} onClick={handlePath}>查询 Knowledge Path</Button>
                    {pathResult?.status === 'no_path' && <Alert type="info" message="没有找到满足当前关系/深度限制的路径" />}
                    {pathResult?.paths.map((path, pathIndex) => (
                      <Card key={pathIndex} size="small" title={`Path ${pathIndex + 1} · depth ${path.depth} · score ${path.score.toFixed(3)}`}>
                        <Space wrap size={[4, 8]}>
                          {path.nodes.map((node, index) => (
                            <Space key={`${node.concept_id}-${index}`} size={4}>
                              <Tag color={node.is_target ? 'purple' : node.is_start ? 'blue' : 'default'}>{node.name}</Tag>
                              {learningStatusTag(node.learning_status)}
                              {index < path.edges.length && <Tag color="gold">→ {path.edges[index].relation_type} →</Tag>}
                            </Space>
                          ))}
                        </Space>
                        <Collapse
                          ghost
                          size="small"
                          items={path.edges.map((edge, index) => ({
                            key: String(index),
                            label: `${edge.from.name} → ${edge.relation_type} → ${edge.to.name} · ${edge.provenance_status}`,
                            children: edge.evidence.length
                              ? edge.evidence.map((item, evidenceIndex) => <Paragraph key={evidenceIndex}>{item.excerpt}</Paragraph>)
                              : <Text type="secondary">没有可展示的来源 excerpt；provenance 已显式标记。</Text>,
                          }))}
                        />
                      </Card>
                    ))}
                    {pathResult && (
                      <Collapse
                        ghost
                        items={[{ key: 'runtime', label: 'Path runtime diagnostics', children: <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(pathResult.runtime, null, 2)}</pre> }]}
                      />
                    )}
                  </Space>
                </Col>
              </Row>
            </Card>

            <Card title={<Space><LinkOutlined />4. Association V2 / Explainable Multi-hop</Space>}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Input.TextArea
                  autoSize={{ minRows: 3, maxRows: 8 }}
                  value={associationText}
                  onChange={(event) => setAssociationText(event.target.value)}
                  placeholder="例如：Tool Calling 和 Agent Runtime 为什么有关？或者粘贴一段你想寻找关联的知识。"
                />
                <Checkbox
                  checked={associationWithMaterial}
                  disabled={!selectedMaterialId}
                  onChange={(event) => setAssociationWithMaterial(event.target.checked)}
                >
                  把当前资料作为 Association anchor/source context（会避免把同一资料自己的 Claim 当成跨来源推荐）
                </Checkbox>
                <Button type="primary" icon={<ExperimentOutlined />} loading={associationLoading} onClick={handleAssociation}>运行 Association V2</Button>
                {associationResult && associationResult.associations.length === 0 && <Alert type="info" message="当前没有找到满足证据/来源约束的 Association" />}
                {associationResult?.associations.map(renderAssociation)}
                {associationResult && (
                  <Collapse
                    ghost
                    items={[{ key: 'diag', label: 'Association diagnostics', children: <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(associationResult.diagnostics, null, 2)}</pre> }]}
                  />
                )}
              </Space>
            </Card>
          </Space>
        </div>
      </Content>

      <KnowledgeResolutionDrawer
        open={resolutionOpen}
        materialId={selectedMaterialId}
        materialTitle={selectedMaterial?.title}
        onClose={() => setResolutionOpen(false)}
        onResolved={async () => {
          if (selectedMaterialId) await refreshMaterial(selectedMaterialId)
          await refreshGlobal()
        }}
      />
    </Layout>
  )
}

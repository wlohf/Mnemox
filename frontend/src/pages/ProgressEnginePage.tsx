import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, Row, Col, Progress, List, Tag, Space, Switch, Slider, Divider, Select, Modal, message } from 'antd'
import { ArrowLeftOutlined, RadarChartOutlined } from '@ant-design/icons'
import {
  getProgressEngine,
  analyzeMaterialForProgress,
  setMaterialClassification,
  getMaterialLearningPlan,
  generateTrainingTasks,
  generate7DayPlan,
  adaptiveReplan,
  type ProgressEngineData,
  type ProgressMaterialItem,
} from '../services/learningApi'

const { Header, Content } = Layout

export function ProgressEnginePage() {
  const navigate = useNavigate()
  const [data, setData] = useState<ProgressEngineData | null>(null)
  const [includeNonTextbook, setIncludeNonTextbook] = useState(false)
  const [loadingId, setLoadingId] = useState<number | null>(null)
  const [weights, setWeights] = useState({ chapter: 0.4, quiz: 0.25, wrong: 0.2, output: 0.15 })
  const [planLoadingId, setPlanLoadingId] = useState<number | null>(null)
  const [materialPlans, setMaterialPlans] = useState<Record<number, { chapter_path: any[]; training_pack: any[] }>>({})
  const [replanMode, setReplanMode] = useState<'balanced' | 'weak_first' | 'output_first'>('balanced')
  const [replanPreview, setReplanPreview] = useState<Array<{ task_id: number; title: string; task_type?: string; planned_date?: string | null; priority: number }>>([])
  const [showReplanModal, setShowReplanModal] = useState(false)

  const load = async (include = includeNonTextbook) => {
    const d = await getProgressEngine(include, weights)
    setData(d)
  }

  useEffect(() => {
    void load(false)
  }, [])

  const runAnalyze = async (materialId: number) => {
    setLoadingId(materialId)
    const res = await analyzeMaterialForProgress(materialId)
    setLoadingId(null)
    if (!res) {
      message.error('AI 分析失败')
      return
    }
    message.success(`分析完成：${res.is_textbook ? '教材型' : '非教材型'}（置信度 ${Math.round(res.confidence * 100)}%）`)
    await load()
  }

  const toggleTextbook = async (m: ProgressMaterialItem, next: boolean) => {
    const ok = await setMaterialClassification(m.material_id, next)
    if (!ok) {
      message.error('更新分类失败')
      return
    }
    message.success(next ? '已标记为教材' : '已标记为非教材')
    await load()
  }

  const loadPlan = async (m: ProgressMaterialItem) => {
    setPlanLoadingId(m.material_id)
    const plan = await getMaterialLearningPlan(m.material_id)
    setPlanLoadingId(null)
    if (!plan) {
      message.error('加载学习路径失败')
      return
    }
    setMaterialPlans((prev) => ({ ...prev, [m.material_id]: { chapter_path: plan.chapter_path, training_pack: plan.training_pack } }))
  }

  const makeTrainingTasks = async (m: ProgressMaterialItem) => {
    const created = await generateTrainingTasks(m.material_id)
    if (!created) {
      message.error('生成训练任务失败')
      return
    }
    message.success(`已生成 ${created.created_task_count} 个训练任务（目标ID ${created.goal_id}）`)
  }

  const make7DayPlan = async (m: ProgressMaterialItem) => {
    const created = await generate7DayPlan(m.material_id, 7)
    if (!created) {
      message.error('生成 7 天计划失败')
      return
    }
    message.success(`已生成 ${created.created_task_count} 个计划任务（目标ID ${created.goal_id}）`)
  }

  const runAdaptiveReplan = async (m: ProgressMaterialItem) => {
    const res = await adaptiveReplan(m.material_id, { days: 7, focus_mode: replanMode })
    if (!res) {
      message.error('动态重排失败')
      return
    }
    setReplanPreview(res.preview || [])
    setShowReplanModal(true)
    message.success(`已重排 ${res.rescheduled} 个任务`)
  }

  const normalizeWeights = () => {
    const total = weights.chapter + weights.quiz + weights.wrong + weights.output
    if (total <= 0) return
    setWeights((prev) => ({
      chapter: Number((prev.chapter / total).toFixed(2)),
      quiz: Number((prev.quiz / total).toFixed(2)),
      wrong: Number((prev.wrong / total).toFixed(2)),
      output: Number((prev.output / total).toFixed(2)),
    }))
  }

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Header style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', paddingInline: 16 }}>
        <div style={{ maxWidth: 1240, margin: '0 auto', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}><RadarChartOutlined style={{ marginRight: 8 }} />进度引擎</span>
          </Space>
            <Space>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>包含非教材</span>
            <Switch
              checked={includeNonTextbook}
              onChange={(v) => {
                setIncludeNonTextbook(v)
                void load(v)
              }}
            />
            <Button onClick={() => void load()}>刷新</Button>
            <Select
              value={replanMode}
              onChange={(v) => setReplanMode(v as any)}
              options={[
                { label: '均衡重排', value: 'balanced' },
                { label: '薄弱优先', value: 'weak_first' },
                { label: '输出优先', value: 'output_first' },
              ]}
              style={{ width: 130 }}
            />
          </Space>
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1240, margin: '0 auto' }}>
          <Card size="small" title="进度权重配置" style={{ marginBottom: 12 }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={6}><div style={{ fontSize: 12 }}>章节掌握 {Math.round(weights.chapter * 100)}%</div><Slider min={0} max={1} step={0.05} value={weights.chapter} onChange={(v) => setWeights((p) => ({ ...p, chapter: Number(v) }))} /></Col>
              <Col xs={24} md={6}><div style={{ fontSize: 12 }}>做题正确率 {Math.round(weights.quiz * 100)}%</div><Slider min={0} max={1} step={0.05} value={weights.quiz} onChange={(v) => setWeights((p) => ({ ...p, quiz: Number(v) }))} /></Col>
              <Col xs={24} md={6}><div style={{ fontSize: 12 }}>错题修复率 {Math.round(weights.wrong * 100)}%</div><Slider min={0} max={1} step={0.05} value={weights.wrong} onChange={(v) => setWeights((p) => ({ ...p, wrong: Number(v) }))} /></Col>
              <Col xs={24} md={6}><div style={{ fontSize: 12 }}>输出质量 {Math.round(weights.output * 100)}%</div><Slider min={0} max={1} step={0.05} value={weights.output} onChange={(v) => setWeights((p) => ({ ...p, output: Number(v) }))} /></Col>
            </Row>
            <Space>
              <Button size="small" onClick={normalizeWeights}>归一化</Button>
              <Button size="small" type="primary" onClick={() => void load()}>应用权重重算</Button>
            </Space>
          </Card>

          <Card size="small" title="总进度" style={{ marginBottom: 12 }}>
            <Progress percent={Math.round(data?.total_progress || 0)} strokeColor="#10a37f" />
            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>资料数：{data?.material_count || 0}</div>
          </Card>

          <Row gutter={[16, 16]}>
            <Col xs={24}>
              <Card size="small" title="资料级进度分解">
                <List
                  dataSource={data?.materials || []}
                  locale={{ emptyText: '暂无可计算进度的资料' }}
                  renderItem={(m) => (
                    <List.Item>
                      <div style={{ width: '100%' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8 }}>
                          <Space wrap>
                            <span style={{ fontWeight: 500 }}>{m.title}</span>
                            <Tag color={m.is_textbook ? 'green' : 'default'}>{m.is_textbook ? '教材型' : '非教材'}</Tag>
                            {m.profile_source && <Tag>{m.profile_source}</Tag>}
                            <Tag>置信度 {Math.round((m.textbook_confidence || 0) * 100)}%</Tag>
                          </Space>
                          <Space>
                            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>教材标记</span>
                            <Switch checked={m.is_textbook} onChange={(v) => void toggleTextbook(m, v)} />
                            <Button size="small" loading={loadingId === m.material_id} onClick={() => void runAnalyze(m.material_id)}>AI分析</Button>
                            <Button size="small" loading={planLoadingId === m.material_id} onClick={() => void loadPlan(m)}>学习路径</Button>
                            <Button size="small" onClick={() => void makeTrainingTasks(m)}>生成训练任务</Button>
                            <Button size="small" onClick={() => void make7DayPlan(m)}>生成7天计划</Button>
                            <Button size="small" onClick={() => void runAdaptiveReplan(m)}>动态重排</Button>
                          </Space>
                        </div>

                        <Row gutter={[8, 8]}>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.overall_progress)} format={(p) => `总进度 ${p}%`} /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.chapter_progress)} format={(p) => `章节掌握 ${p}%`} /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.practice_correct_rate)} format={(p) => `做题正确率 ${p}%`} strokeColor="#3b82f6" /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.question_type_coverage || 0)} format={(p) => `题型掌握覆盖 ${p}%`} strokeColor="#14b8a6" /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.wrong_fix_rate)} format={(p) => `错题修复率 ${p}%`} strokeColor="#f59e0b" /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.task_execution_quality || 0)} format={(p) => `任务执行质量 ${p}%`} strokeColor="#0ea5e9" /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.output_quality)} format={(p) => `输出质量 ${p}%`} strokeColor="#8b5cf6" /></Col>
                          <Col xs={24} md={12}><Progress percent={Math.round(m.chapter_completion)} format={(p) => `章节完成率 ${p}%`} strokeColor="#10b981" /></Col>
                        </Row>

                        {Array.isArray(m.structure?.chapters) && m.structure.chapters.length > 0 && (
                          <div style={{ marginTop: 10, background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 8, padding: 10 }}>
                            <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>教材结构（AI提炼）</div>
                            <List
                              size="small"
                              dataSource={m.structure.chapters.slice(0, 6)}
                              renderItem={(ch: any) => (
                                <List.Item>
                                  <div>
                                    <div style={{ fontSize: 12, fontWeight: 500 }}>{ch.title}</div>
                                    <div style={{ fontSize: 11, color: '#999' }}>
                                      知识点：{(ch.key_points || []).slice(0, 4).join(' / ') || '-'}
                                    </div>
                                    <div style={{ fontSize: 11, color: '#999' }}>
                                      题型：{(ch.question_types || []).slice(0, 4).join(' / ') || '-'}
                                    </div>
                                  </div>
                                </List.Item>
                              )}
                            />
                          </div>
                        )}

                        {materialPlans[m.material_id] && (
                          <>
                            <Divider style={{ margin: '10px 0' }} />
                            <Row gutter={[12, 12]}>
                              <Col xs={24} lg={14}>
                                <Card size="small" title="章节学习路径（按优先级）">
                                  <List
                                    size="small"
                                    dataSource={materialPlans[m.material_id].chapter_path.slice(0, 8)}
                                    renderItem={(c: any) => (
                                      <List.Item>
                                        <div style={{ width: '100%' }}>
                                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                            <span>{c.chapter_title}</span>
                                            <Tag color={c.priority === 'high' ? 'red' : c.priority === 'medium' ? 'orange' : 'green'}>{c.priority}</Tag>
                                          </div>
                                          <div style={{ fontSize: 12, color: '#666' }}>掌握 {Math.round(c.mastery_level)}% · 题数 {c.question_count} · 错题 {c.wrong_count}</div>
                                          <div style={{ fontSize: 11, color: '#999' }}>题型：{(c.question_types || []).join(' / ') || '-'}</div>
                                        </div>
                                      </List.Item>
                                    )}
                                  />
                                </Card>
                              </Col>
                              <Col xs={24} lg={10}>
                                <Card size="small" title="题型训练包">
                                  <List
                                    size="small"
                                    dataSource={materialPlans[m.material_id].training_pack.slice(0, 8)}
                                    renderItem={(tp: any) => (
                                      <List.Item>
                                        <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between' }}>
                                          <span>{tp.question_type}</span>
                                          <span style={{ fontSize: 12, color: '#666' }}>建议 {tp.suggest_count} 题</span>
                                        </div>
                                      </List.Item>
                                    )}
                                  />
                                </Card>
                              </Col>
                            </Row>
                          </>
                        )}
                      </div>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>
        </div>
      </Content>

      <Modal
        title="动态重排预览（已应用）"
        open={showReplanModal}
        onCancel={() => setShowReplanModal(false)}
        onOk={() => setShowReplanModal(false)}
        okText="知道了"
        cancelButtonProps={{ style: { display: 'none' } }}
      >
        <div style={{ marginBottom: 10 }}>
          <Space>
            <span style={{ fontSize: 12, color: '#666' }}>重排偏好：</span>
            <Select
              value={replanMode}
              onChange={(v) => setReplanMode(v as any)}
              options={[
                { label: '均衡', value: 'balanced' },
                { label: '薄弱优先', value: 'weak_first' },
                { label: '输出优先', value: 'output_first' },
              ]}
              style={{ width: 140 }}
            />
          </Space>
        </div>
        <List
          size="small"
          dataSource={replanPreview}
          locale={{ emptyText: '暂无预览任务' }}
          renderItem={(t) => (
            <List.Item>
              <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{t.title}</span>
                <span style={{ fontSize: 12, color: '#666' }}>{t.planned_date || '-'} · 优先级 {t.priority}</span>
              </div>
            </List.Item>
          )}
        />
      </Modal>
    </Layout>
  )
}

import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Row, Col, Button, Tag, Space, Modal, Input,
  DatePicker, Select, message, Segmented, Tree, Tooltip, Progress,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  PlusOutlined, CalendarOutlined,
  FlagOutlined, CheckSquareOutlined, ApartmentOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useOfflineGoals, type OfflineGoalItem } from '../hooks/useOfflineGoals'
import { useOfflineGoalTasks, type OfflineGoalTaskItem } from '../hooks/useOfflineGoalTasks'
import {
  startStudySession, completeStudySession, listActiveStudySessions, type StudySessionItem,
} from '../services/studySessionApi'
import { evaluateTaskOutput, type OutputEvalResult } from '../services/learningApi'
import { getApiErrorMessage } from '../services/apiClient'
import { GoalPlanModal } from '../components/GoalPlanModal'
import { apiFetch } from '../services/apiClient'
import { PageShell } from '../components/PageShell'

type GoalFilter = 'all' | 'active' | 'completed' | 'paused'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', in_progress: 'orange', completed: 'green',
}
const STATUS_LABEL: Record<string, string> = {
  pending: '待办', in_progress: '进行中', completed: '已完成',
}

interface TaskTreeNode extends DataNode {
  task: OfflineGoalTaskItem
  children?: TaskTreeNode[]
}

// Build tree nodes from flat task list. Parent links come from server ids, so
// locally-created unsynced tasks must not recurse through the root bucket.
function buildTree(tasks: OfflineGoalTaskItem[]): TaskTreeNode[] {
  const byParent = new Map<number | null, OfflineGoalTaskItem[]>()
  const serverIds = new Set(
    tasks
      .map(t => t._serverId)
      .filter((id): id is number => id != null),
  )

  for (const t of tasks) {
    const key = (
      t.parent_task_id != null
      && serverIds.has(t.parent_task_id)
      && t.parent_task_id !== t._serverId
    ) ? t.parent_task_id : null
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key)!.push(t)
  }

  const makeNodes = (parentId: number | null, ancestors = new Set<number>()): TaskTreeNode[] => {
    const children = byParent.get(parentId) || []
    children.sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1))
    return children.map(t => {
      const isMilestone = t.task_type === 'milestone'
      let subs: TaskTreeNode[] = []
      if (t._serverId != null && !ancestors.has(t._serverId)) {
        const nextAncestors = new Set(ancestors)
        nextAncestors.add(t._serverId)
        subs = makeNodes(t._serverId, nextAncestors)
      }
      return {
        key: t._localId,
        title: t.title,
        task: t,
        icon: isMilestone ? <FlagOutlined style={{ color: 'var(--accent-600)' }} /> : <CheckSquareOutlined style={{ color: 'var(--text-tertiary)' }} />,
        children: subs.length > 0 ? subs : undefined,
        isLeaf: subs.length === 0,
      }
    })
  }
  return makeNodes(null)
}

export function GoalsTasksPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<GoalFilter>('all')
  const [selectedGoal, setSelectedGoal] = useState<OfflineGoalItem | null>(null)
  const [activeSessions, setActiveSessions] = useState<Record<number, StudySessionItem>>({})
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([])

  const { goals, createGoal, deleteGoal } = useOfflineGoals(filter === 'all' ? undefined : filter)
  const { goalTasks, createGoalTask, updateGoalTask, deleteGoalTask } = useOfflineGoalTasks(
    selectedGoal ? { goalLocalId: selectedGoal._localId } : undefined,
  )

  // Modals
  const [goalModalOpen, setGoalModalOpen] = useState(false)
  const [goalTitle, setGoalTitle] = useState('')
  const [goalDesc, setGoalDesc] = useState('')
  const [goalDeadline, setGoalDeadline] = useState<string | undefined>()

  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [taskTitle, setTaskTitle] = useState('')
  const [taskType, setTaskType] = useState('learn')
  const [taskPlannedDate, setTaskPlannedDate] = useState<string | undefined>()
  const [taskParentId, setTaskParentId] = useState<number | null>(null)

  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [generatingNextWeek, setGeneratingNextWeek] = useState(false)

  const [evalModalOpen, setEvalModalOpen] = useState(false)
  const [evalTask, setEvalTask] = useState<OfflineGoalTaskItem | null>(null)
  const [evalOutput, setEvalOutput] = useState('')
  const [evalRubric, setEvalRubric] = useState('准确性、结构清晰、覆盖关键点、可复述性')
  const [evalResult, setEvalResult] = useState<OutputEvalResult | null>(null)
  const [evalLoading, setEvalLoading] = useState(false)

  // Auto-select first goal
  useEffect(() => {
    if (goals.length > 0 && !selectedGoal) setSelectedGoal(goals[0])
    else if (goals.length > 0 && selectedGoal) {
      if (!goals.find(g => g._localId === selectedGoal._localId)) setSelectedGoal(goals[0])
    } else if (goals.length === 0) setSelectedGoal(null)
  }, [goals.length, selectedGoal?._localId])

  useEffect(() => { void listActiveStudySessions().then(list => {
    const map: Record<number, StudySessionItem> = {}
    for (const s of list) { if (s.task_id) map[s.task_id] = s }
    setActiveSessions(map)
  }) }, [])

  // Expand milestone nodes by default
  useEffect(() => {
    const milestoneKeys = goalTasks
      .filter(t => t.task_type === 'milestone' && t._localId)
      .map(t => t._localId)
    setExpandedKeys(milestoneKeys)
  }, [goalTasks.length])

  const treeData = useMemo(() => buildTree(goalTasks), [goalTasks])

  // Stats
  const stats = useMemo(() => {
    const total = goalTasks.length
    const done = goalTasks.filter(t => t.status === 'completed').length
    const milestones = goalTasks.filter(t => t.task_type === 'milestone').length
    return { total, done, milestones }
  }, [goalTasks])

  const handleCreateGoal = async () => {
    if (!goalTitle.trim()) { message.warning('请输入目标标题'); return }
    try {
      const created = await createGoal({
        title: goalTitle.trim(),
        description: goalDesc.trim() || undefined,
        deadline: goalDeadline,
      })
      message.success('目标已创建')
      setGoalModalOpen(false)
      setGoalTitle(''); setGoalDesc(''); setGoalDeadline(undefined)
      setSelectedGoal(created)
    } catch (error) {
      message.error(getApiErrorMessage(error, '创建目标失败'))
    }
  }

  const handleCreateTask = async () => {
    if (!selectedGoal) { message.warning('请先选择目标'); return }
    if (!taskTitle.trim()) { message.warning('请输入任务标题'); return }
    try {
      await createGoalTask(selectedGoal._localId, selectedGoal._serverId, {
        title: taskTitle.trim(),
        task_type: taskType,
        planned_date: taskPlannedDate,
        parent_task_id: taskType === 'milestone' ? null : taskParentId,
      })
      message.success('任务已创建')
      setTaskModalOpen(false)
      setTaskTitle(''); setTaskType('learn'); setTaskPlannedDate(undefined); setTaskParentId(null)
    } catch (error) {
      message.error(getApiErrorMessage(error, '创建任务失败'))
    }
  }

  const quickStatus = async (t: OfflineGoalTaskItem, status: 'pending' | 'in_progress' | 'completed') => {
    if (status === 'completed') { openEval(t); return }
    try {
      await updateGoalTask(t._localId, { status })
    } catch (error) {
      message.error(getApiErrorMessage(error, '更新任务状态失败'))
    }
  }

  const startLearning = async (t: OfflineGoalTaskItem) => {
    if (!t._serverId) { message.warning('任务尚未同步'); return }
    const session = await startStudySession(t._serverId)
    if (!session) { message.error('启动失败'); return }
    setActiveSessions(prev => ({ ...prev, [t._serverId!]: session }))
    message.success('学习会话已开始')
  }

  const completeLearning = async (t: OfflineGoalTaskItem) => {
    if (!t._serverId) return
    const active = activeSessions[t._serverId]
    if (!active) { message.warning('没有进行中的会话'); return }
    await completeStudySession(active.id, { mark_task_completed: false })
    setActiveSessions(prev => { const n = { ...prev }; delete n[t._serverId!]; return n })
    message.success('会话已结束')
    openEval(t)
  }

  const openEval = (t: OfflineGoalTaskItem) => {
    setEvalTask(t); setEvalOutput(''); setEvalResult(null); setEvalModalOpen(true)
  }

  const submitEval = async () => {
    if (!evalTask?._serverId) { message.warning('任务尚未同步'); return }
    if (!evalOutput.trim()) { message.warning('请输入产出内容'); return }
    setEvalLoading(true)
    try {
      const res = await evaluateTaskOutput({
        task_id: evalTask._serverId, output_text: evalOutput,
        rubric: evalRubric, mark_task_completed: true,
      })
      setEvalResult(res)
      message.success(`评估完成：${res.score} 分`)
      await updateGoalTask(evalTask._localId, { status: res.score >= 80 ? 'completed' : 'in_progress' })
    } catch (error) {
      message.error(getApiErrorMessage(error, '评估失败'))
    } finally {
      setEvalLoading(false)
    }
  }

  const handleGenerateNextWeek = async () => {
    if (!selectedGoal?._serverId) { message.warning('目标尚未同步'); return }
    setGeneratingNextWeek(true)
    try {
      const r = await apiFetch<{ generated_tasks: number }>(`/api/goals/${selectedGoal._serverId}/plan/next-week`, { method: 'POST' })
      message.success(`已生成 ${r.generated_tasks} 个下周任务`)
      window.location.reload()
    } catch (e: any) {
      message.error(e.message || '生成失败')
    } finally {
      setGeneratingNextWeek(false)
    }
  }

  // Synced tasks can be selected as a parent. Unsynced tasks do not have the
  // server id required by the API yet.
  const parentTaskOptions = goalTasks
    .filter(t => t._serverId)
    .map(t => ({
      label: `${t.task_type === 'milestone' ? '里程碑' : '任务'} · ${t.title}`,
      value: t._serverId!,
    }))

  const renderTaskNode = (t: OfflineGoalTaskItem) => {
    const isMilestone = t.task_type === 'milestone'
    const hasSession = t._serverId ? !!activeSessions[t._serverId] : false
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', padding: '2px 0' }}>
        <span style={{ fontWeight: isMilestone ? 600 : 400, fontSize: isMilestone ? 13 : 12 }}>{t.title}</span>
        {t._syncStatus !== 'synced' && <Tag color="orange" style={{ fontSize: 10 }}>未同步</Tag>}
        <Tag color={STATUS_COLOR[t.status]} style={{ fontSize: 10 }}>{STATUS_LABEL[t.status]}</Tag>
        {t.planned_date && <Tag style={{ fontSize: 10 }}>{t.planned_date}</Tag>}
        {hasSession && <Tag color="cyan" style={{ fontSize: 10 }}>学习中</Tag>}
        <Space size={2} style={{ marginLeft: 4 }}>
          {t.status !== 'in_progress' && (
            <Button size="small" style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => quickStatus(t, 'in_progress')}>开始</Button>
          )}
          <Button size="small" type="primary" ghost style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => quickStatus(t, 'completed')}>完成</Button>
          {hasSession
            ? <Button size="small" danger style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => completeLearning(t)}>结束会话</Button>
            : <Button size="small" style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => startLearning(t)}>学习</Button>
          }
          <Button size="small" style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => {
            if (!t._serverId) {
              message.warning('任务同步后才能添加子任务，请稍后再试')
              return
            }
            setTaskParentId(t._serverId)
            setTaskType('learn')
            setTaskModalOpen(true)
          }}>+子任务</Button>
          <Button size="small" danger style={{ fontSize: 11, padding: '0 6px', height: 20 }} onClick={() => {
            Modal.confirm({
              title: '删除任务', content: `确定删除"${t.title}"？`,
              okText: '删除', okType: 'danger', cancelText: '取消',
              onOk: async () => {
                try {
                  await deleteGoalTask(t._localId)
                  message.success('已删除')
                } catch (error: any) {
                  message.error(error?.message || '删除失败')
                }
              },
            })
          }}>删除</Button>
        </Space>
      </div>
    )
  }

  return (
    <PageShell
      title={(
        <Space wrap>
          <ApartmentOutlined style={{ fontSize: 16, color: 'var(--accent-600)' }} />
          <span>目标与任务</span>
          <Segmented
            value={filter}
            onChange={v => setFilter(v as GoalFilter)}
            options={[
              { label: '全部', value: 'all' },
              { label: '进行中', value: 'active' },
              { label: '已完成', value: 'completed' },
              { label: '暂停', value: 'paused' },
            ]}
            size="small"
          />
        </Space>
      )}
      onBack={() => navigate('/')}
      rightExtra={<Button icon={<PlusOutlined />} onClick={() => setGoalModalOpen(true)}>新建大目标</Button>}
      maxWidth={1200}
    >
          <Row gutter={[16, 16]}>
            {/* Goals list */}
            <Col xs={24} lg={7}>
              <Card size="small" title={<span><FlagOutlined style={{ marginRight: 6 }} />大目标</span>}>
                {goals.length === 0 && (
                  <div style={{ color: 'var(--text-tertiary)', fontSize: 13, padding: '8px 0' }}>
                    暂无目标，点击右上角新建
                  </div>
                )}
                {goals.map(g => (
                  <div
                    key={g._localId}
                    onClick={() => setSelectedGoal(g)}
                    style={{
                      cursor: 'pointer',
                      padding: '10px 12px',
                      borderRadius: 8,
                      marginBottom: 6,
                      border: `1px solid ${selectedGoal?._localId === g._localId ? 'var(--accent-600)' : 'var(--border-color)'}`,
                      background: selectedGoal?._localId === g._localId ? 'var(--accent-50)' : 'var(--bg-tertiary)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>{g.title}</div>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        style={{ flexShrink: 0, marginLeft: 4 }}
                        onClick={e => {
                          e.stopPropagation()
                          Modal.confirm({
                            title: '删除大目标',
                            content: `确定删除"${g.title}"？相关任务也将被删除。`,
                            okText: '删除', okType: 'danger', cancelText: '取消',
                            onOk: async () => {
                              try {
                                await deleteGoal(g._localId)
                                message.success('已删除')
                              } catch (error: any) {
                                message.error(error?.message || '删除失败')
                              }
                            },
                          })
                        }}
                      />
                    </div>
                    <Space size={4} wrap>
                      <Tag color={g.status === 'active' ? 'blue' : g.status === 'completed' ? 'green' : 'default'} style={{ fontSize: 11 }}>
                        {g.status === 'active' ? '进行中' : g.status === 'completed' ? '已完成' : '暂停'}
                      </Tag>
                      {g.deadline && <Tag style={{ fontSize: 11 }}>{g.deadline}</Tag>}
                      {g._syncStatus !== 'synced' && <Tag color="orange" style={{ fontSize: 10 }}>未同步</Tag>}
                    </Space>
                  </div>
                ))}
              </Card>
            </Col>

            {/* Task tree */}
            <Col xs={24} lg={17}>
              {!selectedGoal ? (
                <Card size="small">
                  <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: 32 }}>请先选择一个大目标</div>
                </Card>
              ) : (
                <Card
                  size="small"
                  title={
                    <Space>
                      <span style={{ fontWeight: 600 }}>{selectedGoal.title}</span>
                      {stats.total > 0 && (
                        <Tag color="blue">{stats.done}/{stats.total} 完成</Tag>
                      )}
                    </Space>
                  }
                  extra={
                    <Space size={4}>
                      <Tooltip title="添加里程碑（子目标）">
                        <Button size="small" icon={<FlagOutlined />} onClick={() => { setTaskType('milestone'); setTaskParentId(null); setTaskModalOpen(true) }}>
                          里程碑
                        </Button>
                      </Tooltip>
                      <Tooltip title="添加每日任务">
                        <Button size="small" icon={<PlusOutlined />} type="primary" onClick={() => { setTaskType('learn'); setTaskParentId(null); setTaskModalOpen(true) }}>
                          添加任务
                        </Button>
                      </Tooltip>
                      <Button size="small" icon={<CalendarOutlined />} onClick={() => setPlanModalOpen(true)}>制定计划</Button>
                      <Button size="small" loading={generatingNextWeek} onClick={handleGenerateNextWeek}>生成下周</Button>
                    </Space>
                  }
                >
                  {stats.total > 0 && (
                    <Progress
                      percent={Math.round((stats.done / stats.total) * 100)}
                      size="small"
                      style={{ marginBottom: 12 }}
                      strokeColor="var(--accent-600)"
                    />
                  )}

                  {treeData.length === 0 ? (
                    <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: 24 }}>
                      暂无任务。先添加里程碑（子目标），再在里程碑下添加每日任务。
                    </div>
                  ) : (
                    <Tree
                      showIcon
                      blockNode
                      expandedKeys={expandedKeys}
                      onExpand={keys => setExpandedKeys(keys)}
                      treeData={treeData}
                      titleRender={node => renderTaskNode((node as TaskTreeNode).task)}
                      style={{ background: 'transparent' }}
                    />
                  )}
                </Card>
              )}
            </Col>
          </Row>

      {/* New Goal Modal */}
      <Modal title="新建大目标" open={goalModalOpen} onOk={handleCreateGoal} onCancel={() => setGoalModalOpen(false)} okText="创建">
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>目标标题 <span style={{ color: 'red' }}>*</span></div>
          <Input placeholder="例如：英语六级考试过线" value={goalTitle} onChange={e => setGoalTitle(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>描述</div>
          <Input value={goalDesc} onChange={e => setGoalDesc(e.target.value)} />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>截止日期</div>
          <DatePicker style={{ width: '100%' }} onChange={v => setGoalDeadline(v ? v.format('YYYY-MM-DD') : undefined)} />
        </div>
      </Modal>

      {/* New Task Modal */}
      <Modal
        title={taskType === 'milestone' ? '添加里程碑（子目标）' : '添加任务'}
        open={taskModalOpen}
        onOk={handleCreateTask}
        onCancel={() => setTaskModalOpen(false)}
        okText="创建"
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>类型</div>
          <Select
            value={taskType} onChange={setTaskType} style={{ width: '100%' }}
            options={[
              { label: '🚩 里程碑（子目标）', value: 'milestone' },
              { label: '📚 学习', value: 'learn' },
              { label: '🔄 复习', value: 'review' },
              { label: '✏️ 练习', value: 'practice' },
              { label: '📝 总结', value: 'summarize' },
            ]}
          />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>标题 <span style={{ color: 'red' }}>*</span></div>
          <Input
            placeholder={taskType === 'milestone' ? '例如：词汇量提升到 5000' : '例如：背诵 Unit 3 单词'}
            value={taskTitle}
            onChange={e => setTaskTitle(e.target.value)}
          />
        </div>
        {taskType !== 'milestone' && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ marginBottom: 4 }}>父任务（可选）</div>
            <Select
              allowClear placeholder="不选则直接挂在目标下"
              value={taskParentId ?? undefined}
              onChange={v => setTaskParentId(v ? Number(v) : null)}
              style={{ width: '100%' }}
              options={parentTaskOptions}
            />
          </div>
        )}
        <div>
          <div style={{ marginBottom: 4 }}>计划日期</div>
          <DatePicker style={{ width: '100%' }} onChange={v => setTaskPlannedDate(v ? v.format('YYYY-MM-DD') : undefined)} />
        </div>
      </Modal>

      {/* Eval Modal */}
      <Modal
        title={`输出评估${evalTask ? `：${evalTask.title}` : ''}`}
        open={evalModalOpen}
        onOk={() => void submitEval()}
        confirmLoading={evalLoading}
        onCancel={() => setEvalModalOpen(false)}
        okText="开始评估"
        width={680}
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>评估标准</div>
          <Input value={evalRubric} onChange={e => setEvalRubric(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>你的学习产出</div>
          <Input.TextArea value={evalOutput} onChange={e => setEvalOutput(e.target.value)} autoSize={{ minRows: 5, maxRows: 12 }} />
        </div>
        {evalResult && (
          <Card size="small" title={`评分：${evalResult.score} 分（${evalResult.verdict}）`}>
            <b>优点：</b><ul>{evalResult.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
            <b>不足：</b><ul>{evalResult.gaps.map((s, i) => <li key={i}>{s}</li>)}</ul>
            <b>下一步：</b><ul>{evalResult.next_actions.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </Card>
        )}
      </Modal>

      <GoalPlanModal
        open={planModalOpen}
        goalId={selectedGoal?._serverId || null}
        materialId={selectedGoal?.material_id || null}
        onClose={() => setPlanModalOpen(false)}
        onSuccess={() => window.location.reload()}
      />
    </PageShell>
  )
}

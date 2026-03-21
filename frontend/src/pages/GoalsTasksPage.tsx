import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import {
  Layout,
  Card,
  Row,
  Col,
  Button,
  List,
  Tag,
  Space,
  Modal,
  Input,
  DatePicker,
  Select,
  message,
  Segmented,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined, CalendarOutlined } from '@ant-design/icons'
import { useOfflineGoals, type OfflineGoalItem } from '../hooks/useOfflineGoals'
import { useOfflineGoalTasks, type OfflineGoalTaskItem } from '../hooks/useOfflineGoalTasks'
import {
  startStudySession,
  completeStudySession,
  listActiveStudySessions,
  type StudySessionItem,
} from '../services/studySessionApi'
import { createNote } from '../services/noteApi'
import { evaluateTaskOutput, type OutputEvalResult } from '../services/learningApi'
import { GoalPlanModal } from '../components/GoalPlanModal'
import { apiFetch } from '../services/apiClient'

const { Header, Content } = Layout

type GoalFilter = 'all' | 'active' | 'completed' | 'paused'

export function GoalsTasksPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<GoalFilter>('all')
  const [selectedGoal, setSelectedGoal] = useState<OfflineGoalItem | null>(null)
  const [selectedDay, setSelectedDay] = useState(dayjs())
  const [activeSessions, setActiveSessions] = useState<Record<number, StudySessionItem>>({})

  // Offline data hooks
  const { goals, createGoal } = useOfflineGoals(filter === 'all' ? undefined : filter)
  const { goalTasks, createGoalTask, updateGoalTask, deleteGoalTask } = useOfflineGoalTasks(
    selectedGoal ? { goalLocalId: selectedGoal._localId } : undefined,
  )
  const { goalTasks: dailyTasks } = useOfflineGoalTasks({
    plannedDate: selectedDay.format('YYYY-MM-DD'),
  })

  // Modal state
  const [goalModalOpen, setGoalModalOpen] = useState(false)
  const [goalTitle, setGoalTitle] = useState('')
  const [goalDesc, setGoalDesc] = useState('')
  const [goalTargetLevel, setGoalTargetLevel] = useState('')
  const [goalDeadline, setGoalDeadline] = useState<string | undefined>(undefined)

  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [taskTitle, setTaskTitle] = useState('')
  const [taskDesc, setTaskDesc] = useState('')
  const [taskType, setTaskType] = useState('learn')
  const [taskPlannedDate, setTaskPlannedDate] = useState<string | undefined>(undefined)

  const [evalModalOpen, setEvalModalOpen] = useState(false)
  const [evalTask, setEvalTask] = useState<OfflineGoalTaskItem | null>(null)
  const [evalOutput, setEvalOutput] = useState('')
  const [evalRubric, setEvalRubric] = useState('准确性、结构清晰、覆盖关键点、可复述性')
  const [evalResult, setEvalResult] = useState<OutputEvalResult | null>(null)
  const [evalLoading, setEvalLoading] = useState(false)

  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [generatingNextWeek, setGeneratingNextWeek] = useState(false)

  // Auto-select first goal
  useEffect(() => {
    if (goals.length > 0 && !selectedGoal) {
      setSelectedGoal(goals[0])
    } else if (goals.length > 0 && selectedGoal) {
      const stillExists = goals.find((g) => g._localId === selectedGoal._localId)
      if (!stillExists) setSelectedGoal(goals[0])
    } else if (goals.length === 0) {
      setSelectedGoal(null)
    }
  }, [goals.length, selectedGoal?._localId])

  const loadActiveSessions = async () => {
    const list = await listActiveStudySessions()
    const map: Record<number, StudySessionItem> = {}
    for (const s of list) {
      if (s.task_id) map[s.task_id] = s
    }
    setActiveSessions(map)
  }

  useEffect(() => {
    void loadActiveSessions()
  }, [])

  const handleCreateGoal = async () => {
    if (!goalTitle.trim()) {
      message.warning('请输入目标标题')
      return
    }
    const created = await createGoal({
      title: goalTitle.trim(),
      description: goalDesc.trim() || undefined,
      target_level: goalTargetLevel.trim() || undefined,
      deadline: goalDeadline,
    })
    message.success('目标已创建')
    setGoalModalOpen(false)
    setGoalTitle('')
    setGoalDesc('')
    setGoalTargetLevel('')
    setGoalDeadline(undefined)
    setSelectedGoal(created)
  }

  const handleCreateTask = async () => {
    if (!selectedGoal) {
      message.warning('请先选择目标')
      return
    }
    if (!taskTitle.trim()) {
      message.warning('请输入任务标题')
      return
    }
    await createGoalTask(selectedGoal._localId, selectedGoal._serverId, {
      title: taskTitle.trim(),
      description: taskDesc.trim() || undefined,
      task_type: taskType,
      planned_date: taskPlannedDate,
    })
    message.success('任务已创建')
    setTaskModalOpen(false)
    setTaskTitle('')
    setTaskDesc('')
    setTaskType('learn')
    setTaskPlannedDate(undefined)
  }

  const quickStatus = async (task: OfflineGoalTaskItem, status: 'pending' | 'in_progress' | 'completed') => {
    if (status === 'completed') {
      openEval(task)
      message.info('完成任务前请先进行输出评估')
      return
    }
    const ok = await updateGoalTask(task._localId, { status })
    if (!ok) {
      message.error('更新任务状态失败')
    }
  }

  // Study session features still use online API (task._serverId required)
  const startLearning = async (task: OfflineGoalTaskItem) => {
    if (!task._serverId) {
      message.warning('任务尚未同步到服务器，请等待同步后再开始学习')
      return
    }
    const session = await startStudySession(task._serverId)
    if (!session) {
      message.error('启动学习会话失败')
      return
    }
    try {
      localStorage.setItem('study_active_session_id', String(session.id))
      localStorage.setItem('study_active_task_id', String(task._serverId))
    } catch {
      // ignore
    }
    message.success('学习会话已开始')
    await loadActiveSessions()
  }

  const completeLearning = async (task: OfflineGoalTaskItem) => {
    if (!task._serverId) return
    const active = activeSessions[task._serverId]
    if (!active) {
      message.warning('该任务没有进行中的学习会话')
      return
    }
    const done = await completeStudySession(active.id, { mark_task_completed: false })
    if (!done) {
      message.error('结束学习会话失败')
      return
    }
    try {
      const sid = localStorage.getItem('study_active_session_id')
      const tid = localStorage.getItem('study_active_task_id')
      if (sid && Number(sid) === active.id) localStorage.removeItem('study_active_session_id')
      if (tid && Number(tid) === task._serverId) localStorage.removeItem('study_active_task_id')
    } catch {
      // ignore
    }
    message.success('学习会话已结束，请先完成输出评估')
    await loadActiveSessions()
    openEval(task)
  }

  const createTaskNote = async (task: OfflineGoalTaskItem) => {
    if (!task._serverId) {
      message.warning('任务尚未同步，请等待同步后再创建笔记')
      return
    }
    const created = await createNote({
      title: `任务笔记：${task.title}`,
      content: `# ${task.title}\n\n- 任务ID：${task._serverId}\n- 目标ID：${task.goal_id}\n\n`,
      note_type: 'summary',
      links: [{ link_type: 'task', link_id: task._serverId }],
    })
    if (!created) {
      message.error('创建任务关联笔记失败')
      return
    }
    message.success('已创建任务关联笔记')
  }

  const openEval = (task: OfflineGoalTaskItem) => {
    setEvalTask(task)
    setEvalOutput('')
    setEvalResult(null)
    setEvalModalOpen(true)
  }

  const submitEval = async () => {
    if (!evalTask || !evalTask._serverId) {
      message.warning('任务尚未同步，无法评估')
      return
    }
    if (!evalOutput.trim()) {
      message.warning('请先输入你的产出内容')
      return
    }
    setEvalLoading(true)
    const res = await evaluateTaskOutput({
      task_id: evalTask._serverId,
      output_text: evalOutput,
      rubric: evalRubric,
      mark_task_completed: true,
    })
    setEvalLoading(false)
    if (!res) {
      message.error('评估失败')
      return
    }
    setEvalResult(res)
    message.success(`评估完成：${res.score} 分`)
    if (res.score >= 80) {
      await updateGoalTask(evalTask._localId, { status: 'completed' })
      message.success('评分达标，任务已完成')
    } else {
      await updateGoalTask(evalTask._localId, { status: 'in_progress' })
      message.warning('评分未达标，任务保持进行中')
    }
  }

  const handleGenerateNextWeek = async () => {
    if (!selectedGoal?._serverId) {
      message.warning('目标尚未同步，无法生成下周任务')
      return
    }
    
    setGeneratingNextWeek(true)
    try {
      const response = await apiFetch<{ generated_tasks: number }>(`/api/goals/${selectedGoal._serverId}/plan/next-week`, {
        method: 'POST',
      })
      message.success(`下周任务已生成，共 ${response.generated_tasks} 个任务`)
      // Reload tasks
      window.location.reload()
    } catch (error: any) {
      message.error(error.message || '生成下周任务失败')
    } finally {
      setGeneratingNextWeek(false)
    }
  }

  // Helper: get server id for session lookup
  const getSessionForTask = (task: OfflineGoalTaskItem) =>
    task._serverId ? activeSessions[task._serverId] : undefined

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Header style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', paddingInline: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', height: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>目标与任务</span>
            <Segmented
              value={filter}
              onChange={(v) => setFilter(v as GoalFilter)}
              options={[
                { label: '全部', value: 'all' },
                { label: '进行中', value: 'active' },
                { label: '已完成', value: 'completed' },
                { label: '暂停', value: 'paused' },
              ]}
            />
          </Space>
          <Space>
            <Button icon={<PlusOutlined />} onClick={() => setGoalModalOpen(true)}>新建目标</Button>
            <Button type="primary" icon={<PlusOutlined />} disabled={!selectedGoal} onClick={() => setTaskModalOpen(true)}>添加任务</Button>
          </Space>
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <Card size="small" title="学习目标">
                <List
                  dataSource={goals}
                  locale={{ emptyText: '暂无目标，先创建一个' }}
                  renderItem={(g) => (
                    <List.Item
                      style={{ cursor: 'pointer', background: selectedGoal?._localId === g._localId ? '#e6f7ff' : 'transparent', borderRadius: 6, paddingInline: 8 }}
                      onClick={() => setSelectedGoal(g)}
                    >
                      <List.Item.Meta
                        title={
                          <Space size={4}>
                            <span style={{ fontSize: 13 }}>{g.title}</span>
                            {g._syncStatus !== 'synced' && (
                              <Tag color="orange" style={{ fontSize: 10 }}>未同步</Tag>
                            )}
                          </Space>
                        }
                        description={
                          <Space wrap size={4}>
                            <Tag color={g.status === 'active' ? 'blue' : g.status === 'completed' ? 'green' : 'default'}>
                              {g.status === 'active' ? '进行中' : g.status === 'completed' ? '已完成' : '暂停'}
                            </Tag>
                            {g.deadline && <Tag>{g.deadline}</Tag>}
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            </Col>

            <Col xs={24} lg={16}>
              <Card
                size="small"
                title={selectedGoal ? `目标任务：${selectedGoal.title}` : '目标任务'}
                extra={
                  selectedGoal ? (
                    <Space>
                      <Button
                        size="small"
                        icon={<CalendarOutlined />}
                        onClick={() => setPlanModalOpen(true)}
                      >
                        制定学习计划
                      </Button>
                      <Button
                        size="small"
                        type="primary"
                        loading={generatingNextWeek}
                        onClick={handleGenerateNextWeek}
                      >
                        生成下周任务
                      </Button>
                      <Tag>{goalTasks.length} 项</Tag>
                    </Space>
                  ) : undefined
                }
              >
                <List
                  dataSource={goalTasks}
                  locale={{ emptyText: selectedGoal ? '该目标暂无任务' : '先选择一个目标' }}
                  renderItem={(t) => (
                    <List.Item
                      actions={[
                        <Button size="small" onClick={() => quickStatus(t, 'pending')}>待办</Button>,
                        <Button size="small" onClick={() => quickStatus(t, 'in_progress')}>进行中</Button>,
                        <Button size="small" type="primary" ghost onClick={() => quickStatus(t, 'completed')}>完成(先评估)</Button>,
                        getSessionForTask(t) ? (
                          <Button size="small" danger onClick={() => completeLearning(t)}>结束会话</Button>
                        ) : (
                          <Button size="small" onClick={() => startLearning(t)}>开始学习</Button>
                        ),
                        <Button size="small" onClick={() => navigate('/')}>去对话</Button>,
                        <Button size="small" onClick={() => createTaskNote(t)}>写笔记</Button>,
                        <Button size="small" onClick={() => openEval(t)}>评估输出</Button>,
                        <Button
                          size="small"
                          danger
                          onClick={async () => {
                            Modal.confirm({
                              title: '删除任务',
                              content: `确定要删除任务"${t.title}"吗？`,
                              okText: '删除',
                              okType: 'danger',
                              cancelText: '取消',
                              onOk: async () => {
                                const success = await deleteGoalTask(t._localId)
                                if (success) {
                                  message.success('任务已删除')
                                } else {
                                  message.error('删除失败')
                                }
                              },
                            })
                          }}
                        >
                          删除
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space size={4}>
                            <span style={{ fontSize: 13 }}>{t.title}</span>
                            {t._syncStatus !== 'synced' && (
                              <Tag color="orange" style={{ fontSize: 10 }}>未同步</Tag>
                            )}
                          </Space>
                        }
                        description={
                          <Space wrap size={6}>
                            <Tag>{t.task_type || 'learn'}</Tag>
                            <Tag color={t.status === 'completed' ? 'green' : t.status === 'in_progress' ? 'orange' : 'default'}>{t.status}</Tag>
                            {t._serverId && activeSessions[t._serverId] && <Tag color="cyan">学习中</Tag>}
                            {t.planned_date && <Tag>{t.planned_date}</Tag>}
                            {t.chapter_title && <Tag>{t.chapter_title}</Tag>}
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          <Card size="small" title="每日任务视图" style={{ marginTop: 16 }}>
            <Space style={{ marginBottom: 12 }}>
              <span>日期：</span>
              <DatePicker value={selectedDay} onChange={(v) => setSelectedDay(v || dayjs())} />
              <Tag color="blue">{dailyTasks.length} 项</Tag>
            </Space>
            <List
              dataSource={dailyTasks}
              locale={{ emptyText: '当天暂无任务' }}
              renderItem={(t) => (
                <List.Item>
                  <List.Item.Meta
                    title={t.title}
                    description={`${t.status} · ${t.task_type || 'learn'} · 目标ID ${t.goal_id ?? '(未同步)'}`}
                  />
                </List.Item>
              )}
            />
          </Card>
        </div>
      </Content>

      <Modal
        title="新建目标"
        open={goalModalOpen}
        onOk={handleCreateGoal}
        onCancel={() => setGoalModalOpen(false)}
        okText="创建"
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>目标标题</div>
          <Input value={goalTitle} onChange={(e) => setGoalTitle(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>描述</div>
          <Input value={goalDesc} onChange={(e) => setGoalDesc(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>目标等级</div>
          <Input value={goalTargetLevel} onChange={(e) => setGoalTargetLevel(e.target.value)} placeholder="例如：掌握到 80%" />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>截止日期</div>
          <DatePicker style={{ width: '100%' }} onChange={(v) => setGoalDeadline(v ? v.format('YYYY-MM-DD') : undefined)} />
        </div>
      </Modal>

      <Modal
        title="添加任务"
        open={taskModalOpen}
        onOk={handleCreateTask}
        onCancel={() => setTaskModalOpen(false)}
        okText="创建"
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>任务标题</div>
          <Input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>描述</div>
          <Input value={taskDesc} onChange={(e) => setTaskDesc(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>任务类型</div>
          <Select
            value={taskType}
            onChange={setTaskType}
            style={{ width: '100%' }}
            options={[
              { label: '学习', value: 'learn' },
              { label: '复习', value: 'review' },
              { label: '练习', value: 'practice' },
              { label: '总结', value: 'summarize' },
            ]}
          />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>计划日期</div>
          <DatePicker style={{ width: '100%' }} onChange={(v) => setTaskPlannedDate(v ? v.format('YYYY-MM-DD') : undefined)} />
        </div>
      </Modal>

      <Modal
        title={`输出评估${evalTask ? `：${evalTask.title}` : ''}`}
        open={evalModalOpen}
        onOk={() => void submitEval()}
        confirmLoading={evalLoading}
        onCancel={() => setEvalModalOpen(false)}
        okText="开始评估"
        width={760}
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>评估标准</div>
          <Input value={evalRubric} onChange={(e) => setEvalRubric(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>你的学习产出（摘要/答案/讲解）</div>
          <Input.TextArea value={evalOutput} onChange={(e) => setEvalOutput(e.target.value)} autoSize={{ minRows: 6, maxRows: 12 }} />
        </div>
        {evalResult && (
          <Card size="small" title={`评分结果：${evalResult.score} 分（${evalResult.verdict}）`}>
            <div style={{ marginBottom: 8 }}>
              <b>优点：</b>
              <ul>{evalResult.strengths.map((s, i) => <li key={`s-${i}`}>{s}</li>)}</ul>
            </div>
            <div style={{ marginBottom: 8 }}>
              <b>不足：</b>
              <ul>{evalResult.gaps.map((s, i) => <li key={`g-${i}`}>{s}</li>)}</ul>
            </div>
            <div>
              <b>下一步：</b>
              <ul>{evalResult.next_actions.map((s, i) => <li key={`n-${i}`}>{s}</li>)}</ul>
            </div>
          </Card>
        )}
      </Modal>

      <GoalPlanModal
        open={planModalOpen}
        goalId={selectedGoal?._serverId || null}
        materialId={selectedGoal?.material_id || null}
        onClose={() => setPlanModalOpen(false)}
        onSuccess={() => {
          // Reload tasks after plan is set
          window.location.reload()
        }}
      />
    </Layout>
  )
}

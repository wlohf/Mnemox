import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Col, Collapse, Dropdown, Empty, List, Modal, Popconfirm, Progress, Row, Space, Switch, Tag, Typography, message } from 'antd'
import { BulbOutlined, CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined, LockOutlined, ReloadOutlined, ThunderboltOutlined, UserOutlined } from '@ant-design/icons'
import { PageShell } from '../components/PageShell'
import {
  controlAgentProfileItem,
  executeAgentAction,
  getAgentActionDraft,
  getAgentBrief,
  getAgentCoreProfile,
  getAgentGoalContext,
  getAgentGoalContextActionDraft,
  getAgentStatus,
  ignoreAgentMemoryCandidate,
  listAgentMemoryCandidates,
  recordAgentActionFeedback,
  runAgentMemoryLearning,
  triggerAgentTask,
  confirmAgentMemoryCandidate,
  type AgentAction,
  type AgentActionDraftResponse,
  type AgentBrief,
  type AgentCoreProfile,
  type AgentGoalContext,
  type AgentGoalContextItem,
  type AgentMemoryCandidate,
  type AgentNegativeReasonCode,
  type AgentPersonalizationItem,
  type AgentRuntimeInfo,
} from '../services/agentApi'
import {
  listCoachNudges,
  recordCoachNudgeFeedback,
  type CoachFeedbackOutcome,
  type CoachNudge,
} from '../services/coachApi'

const { Paragraph, Text } = Typography

const negativeReasonOptions: Array<{ key: AgentNegativeReasonCode; label: string }> = [
  { key: 'too_long', label: '太长' },
  { key: 'too_late', label: '太晚' },
  { key: 'too_easy', label: '太简单' },
  { key: 'too_hard', label: '太难' },
  { key: 'too_disruptive', label: '太打扰' },
  { key: 'irrelevant_to_goal', label: '和当前目标无关' },
  { key: 'already_known', label: '已经掌握' },
  { key: 'other', label: '其他原因' },
]

const profileOperationCopy = {
  ignore: { label: '不再使用这条', title: '之后不再让这条画像影响建议？' },
  inaccurate: { label: '这不准确', title: '把这条画像标记为不准确？' },
  lock: { label: '锁定', title: '锁定这条画像理解？' },
  unlock: { label: '取消锁定', title: '取消锁定后允许 Agent 继续更新这条理解？' },
  restore: { label: '恢复', title: '恢复这条画像理解？' },
}

function priorityColor(priority: AgentAction['priority']) {
  if (priority === 'high') return 'red'
  if (priority === 'medium') return 'orange'
  return 'green'
}

function riskColor(risk?: AgentBrief['risk_level']) {
  if (risk === 'high') return 'red'
  if (risk === 'medium') return 'orange'
  return 'green'
}

function autonomyLabel(level?: string) {
  if (level === 'copilot+') return 'Copilot+｜深度协同'
  if (level === 'copilot') return 'Copilot｜主动协同'
  if (level === 'coach') return 'Coach｜教练引导'
  return 'Observe｜观察学习'
}

function formatCompactValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(formatCompactValue).filter(Boolean).join('；')
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${formatCompactValue(item)}`)
      .filter((item) => !item.endsWith(': '))
    return entries.join('，')
  }
  return String(value)
}

function parseEvidence(evidence: AgentMemoryCandidate['evidence'] | AgentCoreProfile['evidence']): string[] {
  if (!evidence) return []
  if (Array.isArray(evidence)) return evidence.map(formatCompactValue).filter(Boolean)
  if (typeof evidence !== 'string') return [formatCompactValue(evidence)].filter(Boolean)
  const trimmed = evidence.trim()
  if (!trimmed) return []
  try {
    const parsed = JSON.parse(trimmed)
    if (Array.isArray(parsed)) return parsed.map(formatCompactValue).filter(Boolean)
    if (parsed && typeof parsed === 'object') {
      return Object.entries(parsed).map(([key, value]) => `${key}: ${formatCompactValue(value)}`).filter(Boolean)
    }
  } catch {
    // Evidence may already be a plain human-readable sentence.
  }
  return [trimmed]
}

function confidenceLabel(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${Math.round(Number(value) * 100)}%`
}

function coreProfileLines(profile: AgentCoreProfile | null): string[] {
  if (!profile?.memory_value) return []
  const raw = profile.memory_value.trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean)
    if (parsed && typeof parsed === 'object') {
      const summary = (parsed as { summary?: unknown }).summary
      if (Array.isArray(summary)) {
        const summaryLines = summary.flatMap((group) => {
          if (!group || typeof group !== 'object') return [formatCompactValue(group)]
          const category = String((group as { category?: unknown }).category || 'profile')
          const items = (group as { items?: unknown }).items
          if (Array.isArray(items)) return items.slice(0, 4).map((item) => `${category}: ${formatCompactValue(item)}`)
          return [`${category}: ${formatCompactValue(group)}`]
        }).filter(Boolean)
        if (summaryLines.length > 0) return summaryLines
      }
      return Object.entries(parsed)
        .filter(([key]) => key !== 'summary')
        .map(([key, value]) => `${key}: ${formatCompactValue(value)}`)
        .filter(Boolean)
    }
  } catch {
    // Core profile may be a curated plain-text summary.
  }
  return raw.split('\n').map((line) => line.trim()).filter(Boolean)
}

export function AgentPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [brief, setBrief] = useState<AgentBrief | null>(null)
  const [useLlm, setUseLlm] = useState(false)
  const [draftLoading, setDraftLoading] = useState(false)
  const [draft, setDraft] = useState<AgentActionDraftResponse | null>(null)
  const [executeLoading, setExecuteLoading] = useState(false)
  const [runtime, setRuntime] = useState<AgentRuntimeInfo | null>(null)
  const [goalContext, setGoalContext] = useState<AgentGoalContext | null>(null)
  const [coachNudges, setCoachNudges] = useState<CoachNudge[]>([])
  const [agentLoading, setAgentLoading] = useState<string | null>(null)
  const [showDebug, setShowDebug] = useState(false)
  const [memoryCandidates, setMemoryCandidates] = useState<AgentMemoryCandidate[]>([])
  const [coreProfile, setCoreProfile] = useState<AgentCoreProfile | null>(null)
  const [memoryReviewLoading, setMemoryReviewLoading] = useState(false)
  const [memoryActionLoading, setMemoryActionLoading] = useState<number | 'run' | null>(null)

  const loadRuntime = async () => {
    const data = await getAgentStatus()
    if (data) setRuntime(data)
  }

  const loadCoachNudges = async () => {
    const data = await listCoachNudges(undefined, 8)
    if (data) setCoachNudges(data)
  }

  const loadAgentMemoryReview = async () => {
    setMemoryReviewLoading(true)
    const [candidates, profile] = await Promise.all([
      listAgentMemoryCandidates(),
      getAgentCoreProfile(),
    ])
    setMemoryCandidates(candidates || [])
    setCoreProfile(profile)
    setMemoryReviewLoading(false)
  }

  const load = async (llm = useLlm) => {
    setLoading(true)
    const [data, runtimeData, nudgesData, goalData, candidatesData, profileData] = await Promise.all([
      getAgentBrief(llm),
      getAgentStatus(),
      listCoachNudges(undefined, 8),
      getAgentGoalContext().catch(() => null),
      listAgentMemoryCandidates(),
      getAgentCoreProfile(),
    ])
    setLoading(false)
    if (runtimeData) setRuntime(runtimeData)
    if (nudgesData) setCoachNudges(nudgesData)
    if (goalData) setGoalContext(goalData)
    setMemoryCandidates(candidatesData || [])
    setCoreProfile(profileData)
    if (!data) {
      message.error('加载 Agent 简报失败')
      return
    }
    setBrief(data)
  }

  useEffect(() => {
    void load(false)
  }, [])

  const openDraft = async (action: AgentAction) => {
    setDraftLoading(true)
    const data = await getAgentActionDraft(action.id, useLlm)
    setDraftLoading(false)
    if (!data) {
      message.error('生成行动草案失败，请刷新后重试')
      return
    }
    if (!data.requires_confirmation) {
      void recordAgentActionFeedback(action.id, { outcome: 'accepted', notes: '从 Agent 页面跳转执行' })
      navigate(data.draft.route || action.route)
      return
    }
    setDraft(data)
  }

  const confirmDraft = async () => {
    if (!draft) return
    setExecuteLoading(true)
    const result = await executeAgentAction(draft.action.id, useLlm)
    setExecuteLoading(false)
    if (!result) {
      message.error('执行行动失败，请刷新后重试')
      return
    }
    message.success(result.status === 'created' ? '已创建今日任务' : '已记录行动')
    setDraft(null)
    await load()
    if (result.route) navigate(result.route)
  }

  const runAgent = async (agent: 'study_plan' | 'review' | 'chat') => {
    setAgentLoading(agent)
    const payload = agent === 'chat' ? { tool: 'search_notes', query: '', limit: 5 } : {}
    const result = await triggerAgentTask(agent, agent === 'chat' ? 'search_notes' : 'run', payload)
    setAgentLoading(null)
    if (!result) {
      message.error('Agent 任务执行失败')
      return
    }
    setRuntime(result.runtime)
    message.success(result.result.summary)
    await loadRuntime()
    if (agent !== 'chat') await load()
  }

  const openGoalFocusDraft = async () => {
    const focus = goalContext?.today_focus
    if (!focus) return
    if (!focus.requires_confirmation) {
      navigate(focus.route || '/agent')
      return
    }
    setDraftLoading(true)
    const data = await getAgentGoalContextActionDraft(focus.action_id)
    setDraftLoading(false)
    if (!data) {
      message.error('生成目标行动草案失败，请刷新后重试')
      return
    }
    setDraft(data)
  }

  const sendCoachFeedback = async (nudge: CoachNudge, outcome: CoachFeedbackOutcome) => {
    const result = await recordCoachNudgeFeedback(nudge.id, { outcome })
    if (!result) {
      message.error('Coach 反馈记录失败')
      return
    }
    message.success('已记录 Coach 反馈')
    await loadCoachNudges()
  }

  const runMemoryLearning = async () => {
    setMemoryActionLoading('run')
    const result = await runAgentMemoryLearning()
    setMemoryActionLoading(null)
    if (!result) {
      message.error('长期记忆学习失败，请稍后重试')
      return
    }
    message.success(result.message || `已检查长期记忆：确认 ${result.confirmed ?? 0}，待确认 ${result.staged ?? 0}`)
    await loadAgentMemoryReview()
  }

  const confirmMemoryCandidate = async (candidate: AgentMemoryCandidate, lock = false) => {
    setMemoryActionLoading(candidate.id)
    const result = await confirmAgentMemoryCandidate(candidate.id, { lock })
    setMemoryActionLoading(null)
    if (!result) {
      message.error('确认记忆失败，请稍后重试')
      return
    }
    message.success(lock ? '已确认并锁定这条长期记忆' : '已确认这条长期记忆')
    await loadAgentMemoryReview()
  }

  const ignoreMemoryCandidate = async (candidate: AgentMemoryCandidate, reason: 'ignored' | 'inaccurate') => {
    setMemoryActionLoading(candidate.id)
    const result = await ignoreAgentMemoryCandidate(candidate.id, { reason })
    setMemoryActionLoading(null)
    if (!result) {
      message.error('更新待确认记忆失败，请稍后重试')
      return
    }
    message.success(reason === 'inaccurate' ? '已标记为不准确' : '已忽略这条记忆')
    await loadAgentMemoryReview()
  }

  const tasks = brief?.context?.tasks || {}
  const review = brief?.context?.review || {}
  const learning = brief?.context?.learning || {}
  const memory = brief?.context?.memory || {}
  const personalization = brief?.context?.personalization
  const feedbackStats = personalization?.feedback_stats

  const controlProfileItem = async (item: AgentPersonalizationItem, operation: 'ignore' | 'inaccurate' | 'lock' | 'unlock' | 'restore') => {
    const result = await controlAgentProfileItem(item.id, operation)
    if (!result) {
      message.error('画像操作失败，请刷新后重试')
      return
    }
    message.success('已更新画像控制，Agent 下次会参考')
    await load()
  }

  const renderProfileAction = (item: AgentPersonalizationItem, operation: 'ignore' | 'inaccurate' | 'lock' | 'unlock' | 'restore', danger = false) => (
    <Popconfirm
      key={operation}
      title={profileOperationCopy[operation].title}
      description="这只会影响 Agent 如何理解你和排序建议，可随时恢复。"
      okText="确认"
      cancelText="取消"
      onConfirm={() => void controlProfileItem(item, operation)}
    >
      <Button size="small" danger={danger}>{profileOperationCopy[operation].label}</Button>
    </Popconfirm>
  )

  const renderProfileItem = (item: AgentPersonalizationItem) => (
    <List.Item
      actions={[
        item.locked ? renderProfileAction(item, 'unlock') : renderProfileAction(item, 'lock'),
        renderProfileAction(item, 'inaccurate'),
        renderProfileAction(item, 'ignore', true),
        (item.ignored || item.inaccurate) ? renderProfileAction(item, 'restore') : null,
      ].filter(Boolean)}
    >
      <Space direction="vertical" size={2}>
        <Space wrap>
          <Text>{item.text}</Text>
          {item.source && <Tag>{item.source}</Tag>}
          {item.locked && <Tag color="gold">已锁定</Tag>}
          {item.inaccurate && <Tag color="red">不准确</Tag>}
          {item.ignored && <Tag color="default">已忽略</Tag>}
        </Space>
        {item.confidence !== undefined && <Text type="secondary">置信度：{Math.round(Number(item.confidence) * 100)}%</Text>}
      </Space>
    </List.Item>
  )

  const renderMemoryCandidate = (candidate: AgentMemoryCandidate) => {
    const evidence = parseEvidence(candidate.evidence)
    return (
      <List.Item
        actions={[
          <Button
            key="confirm"
            size="small"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={memoryActionLoading === candidate.id}
            onClick={() => void confirmMemoryCandidate(candidate)}
          >
            确认
          </Button>,
          <Button
            key="lock"
            size="small"
            icon={<LockOutlined />}
            loading={memoryActionLoading === candidate.id}
            onClick={() => void confirmMemoryCandidate(candidate, true)}
          >
            确认并锁定
          </Button>,
          <Popconfirm
            key="inaccurate"
            title="把这条候选记忆标记为不准确？"
            description="Agent 不会把它加入长期记忆。"
            okText="标记"
            cancelText="取消"
            onConfirm={() => void ignoreMemoryCandidate(candidate, 'inaccurate')}
          >
            <Button size="small" danger icon={<CloseCircleOutlined />} loading={memoryActionLoading === candidate.id}>
              不准确
            </Button>
          </Popconfirm>,
          <Popconfirm
            key="ignore"
            title="忽略这条候选记忆？"
            description="它会从待确认列表移除，不影响其他记忆。"
            okText="忽略"
            cancelText="取消"
            onConfirm={() => void ignoreMemoryCandidate(candidate, 'ignored')}
          >
            <Button size="small" loading={memoryActionLoading === candidate.id}>忽略</Button>
          </Popconfirm>,
        ]}
      >
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Space wrap>
            <Text strong>{candidate.memory_value}</Text>
            <Tag color="blue">{candidate.category || 'memory'}</Tag>
            {candidate.memory_type && <Tag>{candidate.memory_type}</Tag>}
            <Tag color="gold">置信度 {confidenceLabel(candidate.confidence)}</Tag>
            {candidate.source_type && <Tag color="purple">{candidate.source_type}{candidate.source_id ? ` #${candidate.source_id}` : ''}</Tag>}
          </Space>
          {evidence.length > 0 && (
            <Space wrap>
              {evidence.slice(0, 4).map((item) => <Tag key={item}>{item}</Tag>)}
            </Space>
          )}
          {candidate.expires_at && <Text type="secondary">有效期至：{candidate.expires_at}</Text>}
        </Space>
      </List.Item>
    )
  }

  const sendFeedback = async (action: AgentAction, outcome: 'helpful' | 'later' | 'useless' | 'dismissed', reasonCode?: AgentNegativeReasonCode) => {
    const notesMap = {
      helpful: '用户认为该建议有帮助',
      later: '用户选择稍后再处理该建议',
      useless: '用户认为该建议无用',
      dismissed: '用户拒绝该建议',
    }
    const result = await recordAgentActionFeedback(action.id, {
      outcome,
      notes: reasonCode ? `${notesMap[outcome]}：${negativeReasonOptions.find((item) => item.key === reasonCode)?.label || reasonCode}` : notesMap[outcome],
      effectiveness: outcome === 'helpful' ? 0.9 : outcome === 'later' ? 0.45 : 0.1,
      reason_code: reasonCode,
    })
    if (!result) {
      message.error('反馈记录失败')
      return
    }
    message.success('已记录反馈，Agent 下次会参考')
    await load()
  }

  const negativeFeedbackMenu = (action: AgentAction, outcome: 'later' | 'useless' | 'dismissed') => ({
    items: negativeReasonOptions.map((reason) => ({ key: reason.key, label: reason.label })),
    onClick: ({ key }: { key: string }) => void sendFeedback(action, outcome, key as AgentNegativeReasonCode),
  })

  const supportingCount = (items?: AgentGoalContextItem[]) => (items || []).length

  return (
    <PageShell
      title={<><ExperimentOutlined style={{ marginRight: 8 }} />自主学习 Agent</>}
      onBack={() => navigate('/')}
      rightExtra={(
        <Space>
          <Text type="secondary">高级规划</Text>
          <Switch
            checked={useLlm}
            onChange={(checked) => {
              setUseLlm(checked)
              void load(checked)
            }}
          />
          <Button onClick={() => setShowDebug((v) => !v)}>
            {showDebug ? '隐藏调试' : '显示调试'}
          </Button>
          <Button loading={loading} onClick={() => void load()}>刷新感知</Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type={brief?.risk_level === 'high' ? 'error' : brief?.risk_level === 'medium' ? 'warning' : 'success'}
          showIcon
          message={brief?.current_focus || 'Agent 正在观察你的学习状态'}
          description={brief?.state_summary || '暂无简报，请刷新后查看。'}
        />

        {brief?.planner?.source === 'llm' && (
          <Alert
            type="info"
            showIcon
            message={`LLM Planner：${brief.planner.strategy || '已启用增强规划'}`}
            description={brief.planner.fallback_plan ? `保底方案：${brief.planner.fallback_plan}` : undefined}
          />
        )}

        <Card
          size="small"
          loading={loading}
          title="Current Goal"
          extra={<Button size="small" onClick={() => navigate(goalContext?.active_goal?.route || goalContext?.goal_creation?.route || '/goals')}>打开目标</Button>}
        >
          {goalContext?.active_goal ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Row gutter={[12, 12]}>
                <Col xs={24} md={9}>
                  <Space direction="vertical" size={4}>
                    <Space wrap>
                      <Text strong>{goalContext.active_goal.title}</Text>
                      {goalContext.active_goal.deadline && <Tag color="blue">截止 {goalContext.active_goal.deadline}</Tag>}
                      {goalContext.active_goal.target_level && <Tag>{goalContext.active_goal.target_level}</Tag>}
                    </Space>
                    <Space wrap>
                      <Tag>待办 {goalContext.active_goal.progress?.pending_task_count ?? 0}</Tag>
                      <Tag color={goalContext.active_goal.progress?.today_task_count ? 'green' : 'default'}>今日 {goalContext.active_goal.progress?.today_task_count ?? 0}</Tag>
                      <Tag color={goalContext.active_goal.progress?.overdue_task_count ? 'red' : 'default'}>过期 {goalContext.active_goal.progress?.overdue_task_count ?? 0}</Tag>
                      <Tag color="cyan">已完成 {goalContext.active_goal.progress?.completed_today_count ?? 0}</Tag>
                    </Space>
                  </Space>
                </Col>
                <Col xs={24} md={8}>
                  <Space direction="vertical" size={4}>
                    <Text type="secondary">Today's Smallest Useful Action</Text>
                    <Text strong>{goalContext.today_focus?.title}</Text>
                    <Text type="secondary">{goalContext.today_focus?.estimated_minutes} 分钟 · {goalContext.today_focus?.reason}</Text>
                  </Space>
                </Col>
                <Col xs={24} md={7}>
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    <Space wrap>
                      {goalContext.risk_flags?.no_daily_plan && <Tag color="orange">无今日计划</Tag>}
                      {goalContext.risk_flags?.review_debt_high && <Tag color="red">复习积压高</Tag>}
                      {goalContext.risk_flags?.goal_stale && <Tag color="gold">目标偏久未推进</Tag>}
                      {!goalContext.risk_flags?.no_daily_plan && !goalContext.risk_flags?.review_debt_high && !goalContext.risk_flags?.goal_stale && <Tag color="green">无高风险信号</Tag>}
                    </Space>
                    <Button
                      type="primary"
                      size="small"
                      loading={draftLoading}
                      onClick={() => void openGoalFocusDraft()}
                    >
                      {goalContext.today_focus?.requires_confirmation ? '生成草案' : '开始行动'}
                    </Button>
                  </Space>
                </Col>
              </Row>

              <Row gutter={[12, 12]}>
                <Col xs={24} md={12}>
                  <Text strong>Evidence</Text>
                  <Space wrap style={{ marginTop: 8 }}>
                    {(goalContext.evidence || []).map((item) => <Tag key={item}>{item}</Tag>)}
                  </Space>
                </Col>
                <Col xs={24} md={12}>
                  <Text strong>Supporting Context</Text>
                  <Space wrap style={{ marginTop: 8 }}>
                    <Tag color={supportingCount(goalContext.supporting_context?.notes) ? 'blue' : 'default'}>笔记 {supportingCount(goalContext.supporting_context?.notes)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.materials) ? 'purple' : 'default'}>资料 {supportingCount(goalContext.supporting_context?.materials)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.wrong_questions) ? 'red' : 'default'}>错题 {supportingCount(goalContext.supporting_context?.wrong_questions)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.review_items) ? 'orange' : 'default'}>复习 {supportingCount(goalContext.supporting_context?.review_items)}</Tag>
                  </Space>
                  <List
                    size="small"
                    dataSource={[
                      ...(goalContext.supporting_context?.notes || []).slice(0, 2).map((item) => ({ ...item, _kind: '笔记' })),
                      ...(goalContext.supporting_context?.wrong_questions || []).slice(0, 2).map((item) => ({ ...item, _kind: '错题' })),
                    ]}
                    locale={{ emptyText: '暂未找到直接支持该目标的笔记或错题。' }}
                    renderItem={(item) => (
                      <List.Item>
                        <Space wrap>
                          <Tag>{String(item._kind || '证据')}</Tag>
                          <Text>{String(item.title || item.id || '-')}</Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Col>
              </Row>
            </Space>
          ) : (
            <Alert
              type="info"
              showIcon
              message={goalContext?.goal_creation?.title || '创建当前主目标'}
              description={goalContext?.goal_creation?.message || '当前没有活跃目标。先创建一个目标后，Agent 会把任务、笔记、错题和复习证据组织到同一个 cockpit。'}
              action={<Button size="small" type="primary" onClick={() => navigate('/goals')}>创建目标</Button>}
            />
          )}
        </Card>

        <Card
          size="small"
          title={<><BulbOutlined style={{ marginRight: 8 }} />Coach Nudges</>}
          extra={<Button size="small" onClick={() => void loadCoachNudges()}>刷新</Button>}
        >
          <List
            size="small"
            dataSource={coachNudges.filter((item) => item.status !== 'dismissed' && item.status !== 'completed')}
            locale={{ emptyText: '暂无 Coach nudge。聊天低动力、番茄中断或复习积压时会出现在这里。' }}
            renderItem={(nudge) => (
              <List.Item
                actions={[
                  nudge.route || nudge.suggested_action?.route ? (
                    <Button
                      key="open"
                      size="small"
                      type="primary"
                      onClick={() => {
                        void sendCoachFeedback(nudge, 'accepted')
                        navigate(nudge.route || nudge.suggested_action?.route || '/agent')
                      }}
                    >
                      {nudge.suggested_action?.label || '去处理'}
                    </Button>
                  ) : null,
                  <Button key="helpful" size="small" onClick={() => void sendCoachFeedback(nudge, 'helpful')}>有帮助</Button>,
                  <Button key="later" size="small" onClick={() => void sendCoachFeedback(nudge, 'later')}>稍后</Button>,
                  <Button key="dismiss" size="small" danger onClick={() => void sendCoachFeedback(nudge, 'too_disruptive')}>太打扰</Button>,
                ].filter(Boolean)}
              >
                <Space direction="vertical" size={4}>
                  <Space wrap>
                    <Tag color={priorityColor(nudge.priority)}>{nudge.priority}</Tag>
                    <Tag>{nudge.skill_id}</Tag>
                    <Text strong>{nudge.title}</Text>
                  </Space>
                  <Paragraph style={{ marginBottom: 0 }}>{nudge.body}</Paragraph>
                  {nudge.explainability?.reason && (
                    <Text type="secondary">{nudge.explainability.reason}</Text>
                  )}
                  {(nudge.explainability?.sources || []).length > 0 && (
                    <Space wrap>
                      {(nudge.explainability?.sources || []).slice(0, 4).map((source) => (
                        <Tag key={`${source.type}-${source.id}`} color={source.type === 'note' ? 'blue' : 'purple'}>
                          {source.type === 'note' ? '笔记' : '记忆'}：{source.title || source.id}
                        </Tag>
                      ))}
                    </Space>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">自主等级</Text>
              <div style={{ marginTop: 8 }}>
                <Tag color="blue">{autonomyLabel(brief?.autonomy_level)}</Tag>
              </div>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                根据学习天数、长期记忆数量和行为数据动态判断。
              </Paragraph>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">准备度</Text>
              <Progress percent={Math.round(brief?.readiness_score || 0)} status={brief?.risk_level === 'high' ? 'exception' : 'normal'} />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">风险等级</Text>
              <div style={{ marginTop: 8 }}><Tag color={riskColor(brief?.risk_level)}>{brief?.risk_level || '-'}</Tag></div>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                由复习积压、过期任务、今日启动情况和走神率综合判断。
              </Paragraph>
            </Card>
          </Col>
        </Row>

        <Card
          size="small"
          title={<><UserOutlined style={{ marginRight: 8 }} />长期记忆审核</>}
          loading={memoryReviewLoading}
          extra={(
            <Space>
              <Tag color={memoryCandidates.length ? 'gold' : 'green'}>待确认 {memoryCandidates.length}</Tag>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={memoryActionLoading === 'run'}
                onClick={() => void runMemoryLearning()}
              >
                运行学习
              </Button>
            </Space>
          )}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={9}>
                <Space direction="vertical" size={4}>
                  <Text type="secondary">Core Profile</Text>
                  <Text strong>{coreProfile ? `更新于 ${coreProfile.updated_at || '-'}` : '暂无核心画像'}</Text>
                  <Text type="secondary">只汇总高置信长期信号，不包含原始笔记正文或敏感材料。</Text>
                </Space>
              </Col>
              <Col xs={24} md={15}>
                {coreProfileLines(coreProfile).length > 0 ? (
                  <Space wrap>
                    {coreProfileLines(coreProfile).slice(0, 8).map((line) => (
                      <Tag key={line} color="cyan">{line}</Tag>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="继续学习、反馈和整理笔记后会生成核心画像" />
                )}
              </Col>
            </Row>
            <List
              size="small"
              dataSource={memoryCandidates}
              locale={{ emptyText: '没有待确认记忆。低风险聚合记忆会自动提交；敏感或主观推断会在这里等待你确认。' }}
              renderItem={renderMemoryCandidate}
            />
          </Space>
        </Card>

        <Card size="small" title={<><UserOutlined style={{ marginRight: 8 }} />我对你的了解</>} loading={loading}>
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <div>
              <Text strong>画像摘要：</Text>
              <List
                size="small"
                dataSource={personalization?.summary_items || []}
                locale={{ emptyText: '暂无足够画像。继续使用任务、复习、错题和反馈后，Agent 会逐步了解你的学习节奏。' }}
                renderItem={renderProfileItem}
              />
            </div>
            <div>
              <Text strong>最近学到的偏好：</Text>
              <List
                size="small"
                dataSource={personalization?.preference_items || []}
                locale={{ emptyText: '暂无可控偏好。' }}
                renderItem={renderProfileItem}
              />
            </div>
            {(personalization?.feedback_impacts || []).length > 0 && (
              <div>
                <Text strong>最近反馈影响：</Text>
                <Space wrap style={{ marginTop: 6 }}>
                  {personalization?.feedback_impacts?.map((impact) => (
                    <Tag key={`${impact.dimension}-${impact.key}`} color={impact.effect === 'deprioritize' ? 'orange' : 'green'}>{impact.message}</Tag>
                  ))}
                </Space>
              </div>
            )}
            <Collapse
              size="small"
              ghost
              items={[{
                key: 'profile-audit',
                label: '我根据你的修正学到了什么 / 画像修正记录',
                children: (
                  <List
                    size="small"
                    dataSource={personalization?.profile_control_logs || runtime?.profile_control_logs || []}
                    locale={{ emptyText: '暂无画像修正记录。你标记“不准确 / 不再使用 / 锁定”后会显示在这里。' }}
                    renderItem={(log) => (
                      <List.Item>
                        <Space direction="vertical" size={2}>
                          <Space wrap>
                            <Tag color="purple">{log.operation_label || log.operation || log.status || '-'}</Tag>
                            <Text type="secondary">{log.item_id}</Text>
                            <Text type="secondary">{log.created_at}</Text>
                          </Space>
                          <Text>{log.item_text || log.message || '已记录你的画像修正，后续建议会参考。'}</Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              }]}
            />
            <Space wrap>
              <Tag>接受/有帮助：{String(feedbackStats?.accepted ?? 0)}</Tag>
              <Tag>拒绝/稍后/无用：{String(feedbackStats?.rejected_or_delayed ?? 0)}</Tag>
              {feedbackStats?.accepted_rate !== null && feedbackStats?.accepted_rate !== undefined && (
                <Tag color="green">建议接受率：{Math.round(Number(feedbackStats.accepted_rate) * 100)}%</Tag>
              )}
            </Space>
            <List
              size="small"
              header="最近反馈 / Agent 学习记录"
              dataSource={personalization?.recent_feedback || []}
              locale={{ emptyText: '暂无反馈记录。你可以对每条建议点“有帮助 / 稍后 / 无用 / 不再提醒”。' }}
              renderItem={(item) => (
                <List.Item>
                  <Space direction="vertical" size={2}>
                    <Space wrap>
                      <Tag>{item.outcome_label || item.outcome || '-'}</Tag>
                      <Text type="secondary">{item.action_id}</Text>
                      {item.action_type && <Tag>{item.action_type}</Tag>}
                      {item.topic && <Tag color="blue">{item.topic}</Tag>}
                      {item.reason_label && <Tag color="orange">原因：{item.reason_label}</Tag>}
                    </Space>
                    {item.source_signal && <Text type="secondary">影响来源：{item.source_signal}</Text>}
                    {item.notes && <Text>{item.notes}</Text>}
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        </Card>

        <Card
          size="small"
          title={<><ThunderboltOutlined style={{ marginRight: 8 }} />下一步行动</>}
          loading={loading}
        >
          <List
            dataSource={brief?.next_actions || []}
            locale={{ emptyText: '暂无行动建议' }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="helpful"
                    size="small"
                    onClick={() => void sendFeedback(item, 'helpful')}
                  >
                    有帮助
                  </Button>,
                  <Dropdown key="later" menu={negativeFeedbackMenu(item, 'later')} trigger={['click']}>
                    <Button size="small">稍后 / 选择原因</Button>
                  </Dropdown>,
                  <Dropdown key="useless" menu={negativeFeedbackMenu(item, 'useless')} trigger={['click']}>
                    <Button size="small" danger>无用 / 选择原因</Button>
                  </Dropdown>,
                  <Dropdown key="dismissed" menu={negativeFeedbackMenu(item, 'dismissed')} trigger={['click']}>
                    <Button size="small" danger>不再提醒 / 原因</Button>
                  </Dropdown>,
                  <Button
                    key="go"
                    size="small"
                    loading={draftLoading}
                    type={item.priority === 'high' ? 'primary' : 'default'}
                    onClick={() => void openDraft(item)}
                  >
                    生成草案
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={(
                    <Space wrap>
                      <Tag color={priorityColor(item.priority)}>{item.priority}</Tag>
                      <span>{item.title}</span>
                      <Tag>{item.estimated_minutes} 分钟</Tag>
                    </Space>
                  )}
                  description={(
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Text>{item.reason}</Text>
                      <Collapse
                        size="small"
                        ghost
                        items={[{
                          key: 'why',
                          label: '为什么推荐',
                          children: (
                            <Space direction="vertical" size={4}>
                              {item.explainability?.summary && <Alert type="info" showIcon message={item.explainability.summary} />}
                              <Text strong>参考数据</Text>
                              <Space wrap>{(item.explainability?.data_signals || []).map((signal) => <Tag key={signal}>{signal}</Tag>)}</Space>
                              {(item.explainability?.feedback_refs || []).length > 0 && (
                                <>
                                  <Text strong>历史反馈</Text>
                                  <List size="small" dataSource={item.explainability?.feedback_refs || []} renderItem={(ref) => <List.Item>• {ref}</List.Item>} />
                                </>
                              )}
                              {(item.explainability?.reason_adjustments || []).length > 0 && (
                                <Space wrap>
                                  {item.explainability?.reason_adjustments?.map((text) => <Tag key={text} color="geekblue">{text}</Tag>)}
                                </Space>
                              )}
                              {item.explainability?.adjustment && <Text type="secondary">{item.explainability.adjustment}</Text>}
                              {item.explainability?.audit?.write_requires_confirmation && <Tag color="gold">写入型动作：仅生成草案，需你确认后执行</Tag>}
                            </Space>
                          ),
                        }]}
                      />
                    </Space>
                  )}
                />
              </List.Item>
            )}
          />
        </Card>

        <Card size="small" title={<><BulbOutlined style={{ marginRight: 8 }} />关注信号</>} loading={loading}>
          <List
            dataSource={brief?.watch_signals || []}
            renderItem={(item) => <List.Item>• {item}</List.Item>}
          />
        </Card>

        {showDebug && (
          <>
            <Card size="small" title="Agent 感知上下文" loading={loading}>
              <Row gutter={[12, 12]}>
                <Col xs={12} md={6}><Tag>今日任务：{String(tasks.today_task_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>过期任务：{String(tasks.overdue_task_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>到期复习：{String(review.due_review_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>今日学习：{String(learning.today_minutes ?? 0)} 分钟</Tag></Col>
                <Col xs={12} md={6}><Tag>长期记忆：{String(memory.active_memory_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>走神率：{Math.round(Number(learning.recent_distracted_rate ?? 0) * 100)}%</Tag></Col>
              </Row>
            </Card>

            <Card size="small" title="Agent Runtime" loading={loading}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color={runtime?.status === 'running' ? 'processing' : 'default'}>状态：{runtime?.status || 'idle'}</Tag>
                  {(runtime?.agents || []).map((agent) => (
                    <Button
                      key={agent.name}
                      size="small"
                      loading={agentLoading === agent.name}
                      onClick={() => void runAgent(agent.name as 'study_plan' | 'review' | 'chat')}
                    >
                      触发 {agent.display_name}
                    </Button>
                  ))}
                </Space>
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={12}>
                    <List
                      size="small"
                      header="任务队列"
                      bordered
                      dataSource={runtime?.task_queue || []}
                      locale={{ emptyText: '暂无任务' }}
                      renderItem={(job) => (
                        <List.Item>
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag>{String(job.agent || '-')}</Tag>
                              <Tag color={job.status === 'failed' ? 'red' : job.status === 'completed' ? 'green' : 'blue'}>{String(job.status || '-')}</Tag>
                              <Text type="secondary">{String(job.task || '')}</Text>
                            </Space>
                            {Boolean(job.summary) && <Text>{String(job.summary)}</Text>}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Col>
                  <Col xs={24} md={12}>
                    <List
                      size="small"
                      header="执行日志"
                      bordered
                      dataSource={runtime?.execution_logs || []}
                      locale={{ emptyText: '暂无日志' }}
                      renderItem={(log) => (
                        <List.Item>
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag>{String(log.agent || '-')}</Tag>
                              <Tag color={log.status === 'failed' ? 'red' : log.status === 'completed' ? 'green' : 'blue'}>{String(log.status || '-')}</Tag>
                              <Text type="secondary">{String(log.created_at || '')}</Text>
                            </Space>
                            <Text>{String(log.message || '')}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Col>
                </Row>
              </Space>
            </Card>
          </>
        )}

        <Modal
          title="确认 Agent 行动草案"
          open={!!draft}
          onCancel={() => setDraft(null)}
          onOk={() => void confirmDraft()}
          confirmLoading={executeLoading}
          okText="确认创建"
          cancelText="取消"
        >
          {draft && (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Alert type="info" showIcon message={draft.action.title} description={draft.action.reason} />
              <Card size="small">
                <Paragraph><Text strong>操作：</Text>{draft.draft.operation === 'create_task' ? '创建今日任务' : '跳转执行'}</Paragraph>
                {draft.draft.title && <Paragraph><Text strong>任务标题：</Text>{draft.draft.title}</Paragraph>}
                {draft.draft.description && <Paragraph><Text strong>说明：</Text>{draft.draft.description}</Paragraph>}
                {draft.draft.planned_date && <Paragraph><Text strong>计划日期：</Text>{draft.draft.planned_date}</Paragraph>}
                {draft.draft.estimated_minutes && <Paragraph><Text strong>预计时长：</Text>{draft.draft.estimated_minutes} 分钟</Paragraph>}
              </Card>
              <Paragraph type="secondary">Agent 只会在你确认后写入任务；如果状态已变化，请先刷新感知。</Paragraph>
            </Space>
          )}
        </Modal>
      </Space>
    </PageShell>
  )
}

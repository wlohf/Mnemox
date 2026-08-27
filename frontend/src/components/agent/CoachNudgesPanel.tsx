import { BulbOutlined } from '@ant-design/icons'
import { Button, Card, List, Modal, Space, Tag, Typography } from 'antd'
import type { CoachActionAttempt, CoachFeedbackOutcome, CoachNudge, CoachNudgeReplay } from '../../services/coachApi'

const { Paragraph, Text } = Typography

function statusLabel(status: CoachNudge['status']) {
  const labels: Record<CoachNudge['status'], string> = {
    pending: '待展示',
    shown: '已展示',
    accepted: '已采纳',
    started: '进行中',
    snoozed: '稍后提醒',
    dismissed: '已忽略',
    completed: '已完成',
    abandoned: '未继续',
    expired: '已过期',
  }
  return labels[status] || status
}

function statusColor(status: CoachNudge['status']) {
  if (status === 'completed') return 'green'
  if (status === 'started') return 'blue'
  if (status === 'accepted') return 'cyan'
  if (status === 'snoozed') return 'gold'
  return 'default'
}

function attemptLabel(status?: CoachActionAttempt['status']) {
  const labels: Record<string, string> = {
    started: '等待真实学习行为',
    completed: '已由学习行为完成',
    abandoned: '行动已中止',
    expired: '行动窗口已结束',
  }
  return labels[String(status || '')] || '行动待确认'
}

function timelineLabel(eventType: string) {
  const labels: Record<string, string> = {
    'coach.nudge.created': '建议已生成',
    'coach.nudge.shown': '建议已展示',
    'coach.nudge.accepted': '用户已采纳',
    'coach.nudge.started': '开始行动',
    'coach.nudge.completed': '行动已完成',
    'coach.nudge.abandoned': '行动未继续',
    'coach.nudge.expired': '行动窗口已结束',
    'pomodoro.started': '番茄钟已开始',
    'pomodoro.completed': '番茄钟已完成',
    'pomodoro.interrupted': '番茄钟已中断',
    'review.completed': '复习已完成',
  }
  return labels[eventType] || eventType
}

function priorityColor(priority: CoachNudge['priority']) {
  if (priority === 'high') return 'red'
  if (priority === 'medium') return 'orange'
  return 'green'
}

interface CoachNudgesPanelProps {
  nudges: CoachNudge[]
  replay: CoachNudgeReplay | null
  replayLoading: boolean
  onRefresh: () => void
  onFeedback: (nudge: CoachNudge, outcome: CoachFeedbackOutcome) => Promise<boolean>
  onStart: (nudge: CoachNudge) => Promise<void>
  onShowReplay: (nudge: CoachNudge) => Promise<void>
  onCloseReplay: () => void
}

/** A complete, confirmation-first Coach recommendation slice. */
export function CoachNudgesPanel({
  nudges,
  replay,
  replayLoading,
  onRefresh,
  onFeedback,
  onStart,
  onShowReplay,
  onCloseReplay,
}: CoachNudgesPanelProps) {
  return (
    <>
      <Card
        size="small"
        title={<><BulbOutlined style={{ marginRight: 8 }} />Coach 建议</>}
        extra={<Button size="small" onClick={onRefresh}>刷新</Button>}
      >
        <List
          size="small"
          dataSource={nudges.filter((item) => item.status !== 'dismissed')}
          locale={{ emptyText: '暂时没有建议。出现复习积压、番茄钟中断或学习卡住时，Coach 会在这里给一个小下一步。' }}
          renderItem={(nudge) => (
            <List.Item
              actions={[
                nudge.status === 'pending' || nudge.status === 'shown' ? (
                  <Button key="accept" size="small" type="primary" onClick={() => void onFeedback(nudge, 'accepted')}>
                    采纳建议
                  </Button>
                ) : null,
                nudge.status === 'accepted' ? (
                  <Button key="start" size="small" type="primary" onClick={() => void onStart(nudge)}>
                    {nudge.suggested_action?.label || '开始行动'}
                  </Button>
                ) : null,
                nudge.status === 'started' ? (
                  <Button key="continue" size="small" type="primary" onClick={() => void onStart(nudge)}>
                    {nudge.suggested_action?.label || '继续行动'}
                  </Button>
                ) : null,
                nudge.status === 'started' ? <Button key="completed" size="small" onClick={() => void onFeedback(nudge, 'completed')}>确认已完成</Button> : null,
                nudge.status === 'started' ? <Button key="abandoned" size="small" onClick={() => void onFeedback(nudge, 'abandoned')}>不继续了</Button> : null,
                nudge.status === 'pending' || nudge.status === 'shown' || nudge.status === 'accepted' ? (
                  <Button key="later" size="small" onClick={() => void onFeedback(nudge, 'later')}>稍后提醒</Button>
                ) : null,
                nudge.status === 'pending' || nudge.status === 'shown' || nudge.status === 'accepted' ? (
                  <Button key="dismiss" size="small" danger onClick={() => void onFeedback(nudge, 'too_disruptive')}>太打扰</Button>
                ) : null,
                <Button key="replay" size="small" onClick={() => void onShowReplay(nudge)}>查看回放</Button>,
              ].filter(Boolean)}
            >
              <Space direction="vertical" size={4}>
                <Space wrap>
                  <Tag color={priorityColor(nudge.priority)}>{nudge.priority}</Tag>
                  <Tag color={statusColor(nudge.status)}>{statusLabel(nudge.status)}</Tag>
                  {nudge.action_attempt && (
                    <Tag color={nudge.action_attempt.status === 'completed' ? 'green' : nudge.action_attempt.status === 'started' ? 'blue' : 'default'}>
                      {attemptLabel(nudge.action_attempt.status)}
                    </Tag>
                  )}
                  {nudge.requires_confirmation && <Tag color="gold">需要确认</Tag>}
                  <Tag>{nudge.skill_id}</Tag>
                  <Text strong>{nudge.title}</Text>
                </Space>
                <Paragraph style={{ marginBottom: 0 }}>{nudge.body}</Paragraph>
                {nudge.action_attempt?.outcome_source === 'domain_event' && (
                  <Text type="secondary">已关联真实学习事件：{nudge.action_attempt.linked_event_type || '已完成'}</Text>
                )}
                {nudge.explainability?.reason && <Text type="secondary">{nudge.explainability.reason}</Text>}
                {(nudge.explainability?.sources || []).length > 0 && (
                  <Space wrap>
                    {(nudge.explainability?.sources || []).slice(0, 4).map((source) => (
                      <Tag key={`${source.type}-${source.id}`} color={source.type === 'note' ? 'blue' : source.type === 'wrong_question' ? 'red' : 'purple'}>
                        {source.type === 'note' ? '笔记' : source.type === 'wrong_question' ? '错题' : '记忆'}：{source.title || source.id}
                      </Tag>
                    ))}
                  </Space>
                )}
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Modal
        title="Coach 行动回放"
        open={Boolean(replay) || replayLoading}
        onCancel={onCloseReplay}
        footer={<Button onClick={onCloseReplay}>关闭</Button>}
        confirmLoading={replayLoading}
      >
        {replay && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Text strong>{replay.nudge.title || 'Coach 建议'}</Text>
            {replay.nudge.explainability?.reason && <Text type="secondary">触发依据：{replay.nudge.explainability.reason}</Text>}
            <Text type="secondary">建议动作：{replay.nudge.suggested_action?.label || replay.nudge.route || '查看建议'}</Text>
            <Text type="secondary">触发事件：{replay.trigger_event_id || '手动或页面内触发'}</Text>
            {(replay.attempts || []).map((attempt) => (
              <Space key={attempt.id} wrap>
                <Tag color={attempt.status === 'completed' ? 'green' : attempt.status === 'started' ? 'blue' : 'default'}>{attemptLabel(attempt.status)}</Tag>
                <Text type="secondary">{attempt.outcome_source === 'domain_event' ? `真实学习事件：${attempt.linked_event_type || '-'}` : '等待或用户确认'}</Text>
              </Space>
            ))}
            <List
              size="small"
              dataSource={replay.timeline}
              locale={{ emptyText: '这条建议尚未产生更多行为事件。' }}
              renderItem={(event) => (
                <List.Item>
                  <Space direction="vertical" size={1}>
                    <Text>{timelineLabel(event.event_type)}</Text>
                    <Text type="secondary">{event.timestamp ? new Date(event.timestamp).toLocaleString('zh-CN') : '时间待记录'}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        )}
      </Modal>
    </>
  )
}

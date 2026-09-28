import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Collapse, Input, List, Space, Switch, Tag, Typography, message } from 'antd'
import { getApiErrorMessage } from '../services/apiClient'
import { getUnderstanding, setUnderstandingPreferences, refreshUnderstanding, analyzeUnderstanding, reviewUnderstanding, getUnderstandingEvidence, getUnderstandingHistory, searchUnderstandingMemory, rebuildUnderstandingGraph, excludeUnderstandingEvidence, retryUnderstandingJob, reextractUnderstandingEvidence, cleanupUnderstandingGraph, type Overview, type Hypothesis, type Experience, type MemoryRecall, type Usage } from '../services/understandingApi'
import { captureApiSession } from '../services/sessionScope'
import { EpisodeRecall } from './EpisodeRecall'

const labels: Record<string, string> = { candidate: '待验证猜测', observing: '后续观察中', contested: '出现反例', needs_review: '待复查', withdrawn: '已撤回', superseded: '已替代' }

const jobErrors: Record<string, string> = { understanding_ai_configuration_required: '请在 AI 设置中配置自己的 Coach 提供商和密钥，再重试', understanding_daily_budget_exhausted: '今日预算已用完，将在下一个 UTC 日继续', understanding_call_exceeds_daily_budget: '单次请求超过每日预算，请减少输入或调整预算配置后重试', source_changed_during_run: '依据已变化，旧结果已丢弃', source_changed_before_reextraction: '依据已变化，请重新查看原始记录后发起抽取' }

function usageText(usage: Usage) {
  return `模型调用 ${usage.model_calls} 次；${usage.actual_tokens == null ? `已报告 ${usage.reported_tokens} Token，另有 ${usage.usage_missing_calls} 次用量未知` : `${usage.actual_tokens} Token`}；${usage.configured_cost_usd == null ? '费用未知（缺少单价或用量）' : `按配置单价估算 $${usage.configured_cost_usd.toFixed(6)}`}`
}

function evidenceDetail(value: unknown): value is Experience {
  return typeof value === 'object' && value !== null && 'id' in value && 'source' in value
}

function memoryDetail(value: unknown): value is MemoryRecall {
  return typeof value === 'object' && value !== null && 'experiences' in value && 'timeline' in value
}

export function UnderstandingPanel() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [corrections, setCorrections] = useState<Record<string, string>>({})
  const [detail, setDetail] = useState<unknown>(null)
  const [query, setQuery] = useState('上次卡在哪里，试过什么，现在有什么变化')
  const load = useCallback(async () => {
    const scope = captureApiSession()
    try {
      const result = await getUnderstanding()
      scope.assertActive()
      setData(result)
      setError('')
    } catch (e) {
      if (!scope.signal.aborted) setError(getApiErrorMessage(e, '阶段性理解暂不可用'))
    }
  }, [])
  useEffect(() => { void load() }, [load])
  const pending = data?.jobs.some(j => ['pending', 'running'].includes(j.status))
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => { void load() }, 4000)
    return () => clearInterval(timer)
  }, [pending, load])
  const action = async (run: () => Promise<unknown>) => {
    setBusy(true)
    const scope = captureApiSession()
    try { await run(); scope.assertActive(); await load() }
    catch (e) { if (!scope.signal.aborted) message.error(getApiErrorMessage(e, '操作失败')) }
    finally { if (!scope.signal.aborted) setBusy(false) }
  }
  const show = async (read: () => Promise<unknown>) => {
    const scope = captureApiSession()
    const value = await read()
    scope.assertActive()
    setDetail(value)
  }
  const review = (h: Hypothesis, reviewAction: string) => action(() => reviewUnderstanding(h, reviewAction, corrections[h.id] || null))
  return <Card title="阶段性理解与连续记忆">
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" message="这些是可以被推翻的阶段性估计。记录数量和使用天数不等于可信度；原始经历与后续验证分别计算。" />
      {error && <Alert type="warning" message={error} />}
      {data && <>
        <Space wrap>
          {([['analysis_enabled', '阶段性分析'], ['graph_enabled', 'Graphiti 经历增强'], ['consume_enabled', '用于聊天与 Coach']] as const).map(([key, label]) =>
            <Space key={key}><Switch aria-label={label} checked={data.preferences[key]} disabled={busy || (key === 'graph_enabled' && !data.capabilities.graphiti_episodes)}
              onChange={value => void action(() => setUnderstandingPreferences({ ...data.preferences, [key]: value }))} />{label}</Space>)}
        </Space>
        {data.preferences.graph_enabled && <Typography.Text type="secondary">新复盘、带备注的专注记录及 Coach 结果会在后台抽取，使用你的 AI 配置和每日预算。</Typography.Text>}
        {!data.capabilities.graphiti_episodes && <Typography.Text type="secondary">当前部署使用 SQL；Graphiti 经历增强尚未开启。</Typography.Text>}
        {data.graph_projection && <Typography.Text>可抽取经历 {data.graph_projection.eligible} 条，已保存抽取 {data.graph_projection.saved} 条，待处理 {data.graph_projection.pending} 条。</Typography.Text>}
        {data.daily_usage && <Typography.Text>今日用量（UTC {data.daily_usage.date_utc}）：{usageText(data.daily_usage)}。调用上限 {data.daily_usage.call_limit} 次。</Typography.Text>}
        <Space wrap>
          <Button loading={busy} onClick={() => void action(() => refreshUnderstanding())}>更新证据并重评</Button>
          <Button disabled={!data.preferences.analysis_enabled || busy || pending} onClick={() => void action(() => analyzeUnderstanding())}>提出新观察（使用 AI）</Button>
          <Typography.Text>可用经历：{data.evidence_count}</Typography.Text>
        </Space>
        <List dataSource={data.hypotheses} locale={{ emptyText: '目前没有足够依据提出判断，也可以先启用分析，再尝试提出新观察。' }} renderItem={h => <List.Item key={h.id}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space><Tag>{labels[h.status] || h.status}</Tag><Tag>估计 · v{h.version}</Tag>{h.review_status === 'ignored' && <Tag>已忽略</Tag>}</Space>
            <Typography.Text strong>{h.statement}</Typography.Text>
            <Typography.Text>适用情境：{h.details.context || '待重新确认'}</Typography.Text>
            <Typography.Text>后续独立分组：支持 {h.assessment.support_groups ?? 0}，反例 {h.assessment.counter_groups ?? 0}，未知 {h.assessment.unknown_groups ?? 0}</Typography.Text>
            {h.assessment.interval_95 && <Typography.Text>记录符合比例区间：{h.assessment.interval_95.map(v => `${Math.round(v * 100)}%`).join('–')}；{h.assessment.interval_meaning}</Typography.Text>}
            <Typography.Text>尚不清楚：{h.details.unknowns?.join('；') || '暂无可验证结论'}；下一步观察：{h.details.next_signal || '等待新记录'}</Typography.Text>
            {h.details.user_correction && <Typography.Text>你的纠正：{h.details.user_correction}</Typography.Text>}
            <Space wrap>{[...(h.details.support || []), ...(h.details.counter || []), ...(h.details.context_refs || [])].map(ref => <Button key={ref.id} onClick={() => void action(() => show(() => getUnderstandingEvidence(ref.id)))}>查看依据：{ref.quote.slice(0, 30)}</Button>)}</Space>
            <Input aria-label={`纠正 ${h.id}`} placeholder="这个估计哪里不适合你？补充情境，不会自动变成已确认事实" value={corrections[h.id] || ''} onChange={e => setCorrections(prev => ({ ...prev, [h.id]: e.target.value }))} />
            <Space wrap>
              <Button disabled={busy || !corrections[h.id]?.trim()} onClick={() => void review(h, 'correct')}>提交纠正</Button>
              <Button disabled={busy} onClick={() => void review(h, h.review_status === 'ignored' ? 'restore' : 'ignore')}>{h.review_status === 'ignored' ? '恢复观察' : '忽略'}</Button>
              <Button disabled={busy} onClick={() => void review(h, 'withdraw')}>撤回判断</Button>
              <Button disabled={busy} danger onClick={() => void review(h, 'delete')}>删除判断</Button>
              <Button onClick={() => void action(() => show(() => getUnderstandingHistory(h.id)))}>修订历史</Button>
            </Space>
          </Space>
        </List.Item>} />
        <Input.Search aria-label="连续经历检索" value={query} onChange={e => setQuery(e.target.value)} enterButton="回看经历" onSearch={() => void action(() => show(() => searchUnderstandingMemory(query)))} />
        {data.preferences.graph_enabled && <Button disabled={busy || pending} onClick={() => void action(() => rebuildUnderstandingGraph())}>从保存的抽取结果重建图（不调用模型）</Button>}
        {data.capabilities.graphiti_episodes && <Button disabled={busy || pending} onClick={() => void action(() => cleanupUnderstandingGraph())}>清理失效图记录（不调用模型）</Button>}
        {detail != null && <Card size="small" title="依据 / 历史 / 检索结果" extra={<Button onClick={() => setDetail(null)}>收起</Button>}>
          {memoryDetail(detail) ? <EpisodeRecall result={detail} onEvidence={id => void action(() => show(() => getUnderstandingEvidence(id)))} /> : <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(detail, null, 2)}</pre>}
          {evidenceDetail(detail) && data.preferences.graph_enabled && detail.graph?.eligible && <Button disabled={busy || pending} onClick={() => void action(() => reextractUnderstandingEvidence(detail))}>重新抽取此经历（使用 AI）</Button>}
          {evidenceDetail(detail) && <Button danger onClick={() => void action(async () => {
            await excludeUnderstandingEvidence(String(detail.id)); setDetail(null)
          })}>从分析和图记忆移除此经历（保留原记录）</Button>}
        </Card>}
        <Collapse items={[{ key: 'jobs', label: pending ? '分析任务正在后台处理，可离开后再查看' : '任务与模型用量', children: <List dataSource={data.jobs} renderItem={j => <List.Item key={j.id}><Space direction="vertical"><Typography.Text>{j.task} · {j.status} · {j.usage ? usageText(j.usage) : `模型调用 ${j.calls.length} 次`}{j.result?.error && ` · ${jobErrors[j.result.error] || j.result.error}`}{j.result?.abstention_reason && ` · ${j.result.abstention_reason}`}</Typography.Text>{j.status === 'failed' && <Button disabled={busy || pending} onClick={() => void action(() => retryUnderstandingJob(j.id))}>重试失败任务</Button>}{j.status === 'pending' && j.scheduled_for && <Typography.Text>下次处理时间：{j.scheduled_for}</Typography.Text>}</Space></List.Item>} /> }]} />
      </>}
    </Space>
  </Card>
}

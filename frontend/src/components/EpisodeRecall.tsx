import { Alert, Button, List, Space, Tag, Typography } from 'antd'
import type { MemoryRecall } from '../services/understandingApi'

const reasons: Record<string, string> = {
  graphiti_episodes_disabled: '经历增强未开启，使用原始记录回看',
  graphiti_unavailable: '图服务暂不可用，已回退到原始记录',
  graphiti_no_matching_edges: '图中没有匹配内容，使用原始记录回看',
  episode_projection_pending: '经历尚未完成抽取，使用原始记录回看',
  graph_sources_changed: '图对应的依据已变化，使用当前仍有效的记录',
  preferences_changed_during_retrieval: '设置已变化，本次使用原始记录',
}

export function EpisodeRecall({ result, onEvidence }: { result: MemoryRecall; onEvidence: (id: string) => void }) {
  const byId = new Map(result.experiences.map(e => [e.id, e]))
  const entries = result.timeline.map(e => byId.get(e.id)).filter(e => e != null)
  const entities = [...new Set(result.connections.map(c => c.entity))]
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Alert type="info" message={result.backend === 'graphiti_episode' ? '已通过图中的实体与关系回看相关经历，以下按时间展示原始记录。' : reasons[result.reason] || '当前使用原始记录回看'} />
    <Typography.Text>相同主题下的方法和结果可能变化；这些记录不代表永久特性，也不能单凭先后顺序判断因果。</Typography.Text>
    {result.graph_scope_truncated && <Typography.Text>本次图检索只覆盖最近一部分已抽取经历，并非全部历史。</Typography.Text>}
    {entities.length > 0 && <Typography.Text>关联主题：{entities.join('、')}（用于查找相关经历，仍需核对原文）</Typography.Text>}
    <List dataSource={entries} locale={{ emptyText: '目前没有可回看的有效经历' }} renderItem={entry => <List.Item key={entry.id}>
      <Space direction="vertical">
        <Space><Typography.Text>{entry.local_date || entry.occurred_at || `记录于 ${entry.recorded_at || '时间未知'}`}</Typography.Text><Tag>{entry.retrieved_by === 'graphiti_episode' ? '图检索命中' : '原始记录补充'}</Tag></Space>
        <Typography.Text>{entry.text || entry.note || entry.suggestion || '行动记录'}</Typography.Text>
        {entry.outcome && <Typography.Text>记录结果：{entry.outcome}</Typography.Text>}
        <Button onClick={() => onEvidence(entry.id)}>查看原始依据</Button>
      </Space>
    </List.Item>} />
  </Space>
}

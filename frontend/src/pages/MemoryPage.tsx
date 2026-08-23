import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, List, Space, Tag, Modal, Input, InputNumber, message, Checkbox } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  correctMemory,
  deleteMemory,
  listMemoryConflicts,
  listMemoryDeclarations,
  listMemories,
  reviewMemoryCandidate,
  updateMemory,
  type MemoryConflict,
  type MemoryDeclaration,
  type MemoryItem,
} from '../services/memoryApi'

const { Header, Content } = Layout

const declarationStatus = (status: string) => {
  switch (status) {
    case 'confirmed': return { label: '已确认', color: 'green' }
    case 'staged': return { label: '待你确认', color: 'gold' }
    case 'ignored': return { label: '已忽略', color: 'default' }
    case 'inaccurate': return { label: '已标记不准确', color: 'red' }
    case 'expired': return { label: '已自动失效', color: 'orange' }
    case 'superseded': return { label: '已被新事实替代', color: 'default' }
    default: return { label: '已被修订', color: 'default' }
  }
}

const declarationCreator = (createdBy: string) => ({
  user: '你',
  model: '自动提炼',
  agent: 'Agent',
  system: '系统',
}[createdBy] || createdBy)

export function MemoryPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<MemoryItem[]>([])
  const [editing, setEditing] = useState<MemoryItem | null>(null)
  const [val, setVal] = useState('')
  const [cat, setCat] = useState('preference')
  const [conf, setConf] = useState<number>(0.7)
  const [expiry, setExpiry] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([])
  const [reviewingId, setReviewingId] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [declarationMemory, setDeclarationMemory] = useState<MemoryItem | null>(null)
  const [declarations, setDeclarations] = useState<MemoryDeclaration[]>([])
  const [declarationsLoading, setDeclarationsLoading] = useState(false)

  const load = async () => {
    const [nextItems, nextConflicts] = await Promise.all([listMemories(), listMemoryConflicts()])
    setItems(nextItems)
    setConflicts(nextConflicts)
  }

  useEffect(() => {
    void load()
  }, [])

  const openEdit = (m: MemoryItem) => {
    setEditing(m)
    setVal(m.memory_value)
    setCat(m.category)
    setConf(Number(m.confidence || 0.7))
    setExpiry(m.expires_at ? dayjs(m.expires_at).format('YYYY-MM-DDTHH:mm') : '')
    setCorrectionReason('')
  }

  const saveEdit = async () => {
    if (!editing) return
    const nextExpiry = expiry ? dayjs(expiry).format('YYYY-MM-DDTHH:mm:ss') : null
    const currentExpiry = editing.expires_at ? dayjs(editing.expires_at).format('YYYY-MM-DDTHH:mm:ss') : null
    const semanticChanged = editing.memory_value !== val
      || editing.category !== cat
      || Number(editing.confidence || 0.7) !== conf
      || nextExpiry !== currentExpiry
    const updated = semanticChanged
      ? await correctMemory(editing.id, {
        memory_value: val,
        category: cat,
        confidence: conf,
        expires_at: nextExpiry,
        reason: correctionReason.trim() || '用户在记忆管理页面修正事实或有效期',
      })
      : await updateMemory(editing.id, {
        memory_value: val,
        category: cat,
        confidence: conf,
        status: editing.status,
        is_locked: editing.is_locked,
      })
    if (!updated) {
      message.error('更新记忆失败')
      return
    }
    message.success(semanticChanged ? '修订已保存，并已防止自动覆盖' : '记忆已更新')
    setEditing(null)
    await load()
  }

  const openDeclarations = async (m: MemoryItem) => {
    setDeclarationMemory(m)
    setDeclarations([])
    setDeclarationsLoading(true)
    try {
      setDeclarations(await listMemoryDeclarations(m.id))
    } finally {
      setDeclarationsLoading(false)
    }
  }

  const remove = (m: MemoryItem) => {
    Modal.confirm({
      title: '删除记忆',
      content: `确定删除记忆键 ${m.memory_key} 吗？`,
      okType: 'danger',
      onOk: async () => {
        const ok = await deleteMemory(m.id)
        if (!ok) {
          message.error('删除失败')
          return
        }
        message.success('已删除')
        await load()
      },
    })
  }

  const reviewCandidate = async (
    memoryId: number,
    decision: 'confirm' | 'ignore' | 'inaccurate',
  ) => {
    setReviewingId(memoryId)
    try {
      const reviewed = await reviewMemoryCandidate(memoryId, decision, decision === 'confirm')
      if (!reviewed) {
        message.error('处理记忆候选失败，可能已过期或被其他操作更新')
        return
      }
      message.success(decision === 'confirm' ? '新事实已生效，旧事实已保留在历史中' : '已保留原事实并关闭候选')
      await load()
    } finally {
      setReviewingId(null)
    }
  }

  const quickToggleLock = async (m: MemoryItem) => {
    const next = (m.is_locked || 0) === 1 ? 0 : 1
    const updated = await updateMemory(m.id, {
      memory_value: m.memory_value,
      category: m.category,
      confidence: m.confidence,
      status: m.status || 'active',
      is_locked: next,
    })
    if (!updated) {
      message.error('更新锁定状态失败')
      return
    }
    message.success(next === 1 ? '已锁定' : '已解锁')
    await load()
  }

  const quickToggleIgnored = async (m: MemoryItem) => {
    const next = (m.status || 'active') === 'ignored' ? 'active' : 'ignored'
    const updated = await updateMemory(m.id, {
      memory_value: m.memory_value,
      category: m.category,
      confidence: m.confidence,
      status: next,
      is_locked: m.is_locked || 0,
    })
    if (!updated) {
      message.error('更新状态失败')
      return
    }
    message.success(next === 'ignored' ? '已设为忽略' : '已恢复激活')
    await load()
  }

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const bulkIgnore = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    await Promise.all(
      ids.map((id) => {
        const m = items.find((x) => x.id === id)
        if (!m) return Promise.resolve()
        return updateMemory(id, {
          memory_value: m.memory_value,
          category: m.category,
          confidence: m.confidence,
          status: 'ignored',
          is_locked: m.is_locked || 0,
        })
      })
    )
    message.success(`已忽略 ${ids.length} 条`)
    setSelectedIds(new Set())
    await load()
  }

  const bulkDelete = () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    Modal.confirm({
      title: '批量删除记忆',
      content: `确定删除选中的 ${ids.length} 条记忆吗？`,
      okType: 'danger',
      onOk: async () => {
        await Promise.all(ids.map((id) => deleteMemory(id)))
        message.success(`已删除 ${ids.length} 条`)
        setSelectedIds(new Set())
        await load()
      },
    })
  }

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Header style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', paddingInline: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', height: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>AI 记忆管理</span>
          </Space>
          <Space>
            <Tag color="blue">{items.length} 条</Tag>
            <Tag>{selectedIds.size} 已选</Tag>
            <Button size="small" onClick={bulkIgnore} disabled={selectedIds.size === 0}>批量忽略</Button>
            <Button size="small" danger onClick={bulkDelete} disabled={selectedIds.size === 0}>批量删除</Button>
          </Space>
        </div>
      </Header>
      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          {conflicts.length > 0 && (
            <Card
              size="small"
              title={<Space><span>需要你确认的事实冲突</span><Tag color="gold">{conflicts.length} 条</Tag></Space>}
              style={{ marginBottom: 16 }}
            >
              <List
                dataSource={conflicts}
                renderItem={(conflict) => (
                  <List.Item
                    actions={[
                      <Button
                        key="accept"
                        type="primary"
                        loading={reviewingId === conflict.candidate_memory_id}
                        onClick={() => void reviewCandidate(conflict.candidate_memory_id, 'confirm')}
                      >采用新事实</Button>,
                      <Button
                        key="reject"
                        disabled={reviewingId === conflict.candidate_memory_id}
                        onClick={() => void reviewCandidate(conflict.candidate_memory_id, 'inaccurate')}
                      >保留原事实</Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Space><Tag color="blue">{conflict.fact_key}</Tag><span>同一事实出现不同说法</span></Space>}
                      description={
                        <div>
                          <div><Tag color="green">当前有效</Tag>{conflict.current.value}</div>
                          <div style={{ marginTop: 6 }}><Tag color="gold">待你确认</Tag>{conflict.candidate.value}</div>
                        </div>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          )}
          <Card size="small" title="长期记忆条目">
            <List
              dataSource={items}
              locale={{ emptyText: '暂无记忆条目' }}
              renderItem={(m) => (
                <List.Item
                  onClick={() => toggleSelect(m.id)}
                  style={{ cursor: 'pointer' }}
                  actions={[
                    ...(m.review_status === 'staged' ? [
                      <Button key="confirm" size="small" type="primary" loading={reviewingId === m.id} onClick={() => void reviewCandidate(m.id, 'confirm')}>确认</Button>,
                      <Button key="reject" size="small" disabled={reviewingId === m.id} onClick={() => void reviewCandidate(m.id, 'inaccurate')}>不准确</Button>,
                    ] : []),
                    <Button key="l" size="small" onClick={() => quickToggleLock(m)}>
                      {(m.is_locked || 0) === 1 ? '解锁' : '锁定'}
                    </Button>,
                    <Button key="i" size="small" onClick={() => quickToggleIgnored(m)}>
                      {(m.status || 'active') === 'ignored' ? '恢复' : '忽略'}
                    </Button>,
                    <Button key="p" size="small" onClick={() => void openDeclarations(m)}>查看依据</Button>,
                    <Button key="e" size="small" icon={<EditOutlined />} onClick={() => openEdit(m)}>编辑</Button>,
                    <Button key="d" size="small" danger icon={<DeleteOutlined />} onClick={() => remove(m)}>删除</Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={<Space wrap><Checkbox checked={selectedIds.has(m.id)} onChange={() => toggleSelect(m.id)} onClick={(e) => e.stopPropagation()} /><Tag>{m.category}</Tag><span>{m.memory_key}</span>{(m.is_locked || 0) === 1 && <Tag color="gold">锁定</Tag>}{m.review_status === 'staged' && <Tag color="gold">待确认</Tag>}{m.conflicts_with_id && <Tag color="volcano">与当前事实冲突</Tag>}{m.status === 'superseded' && <Tag>已替代</Tag>}{m.status === 'expired' && <Tag color="orange">已过期</Tag>}{(m.status || 'active') === 'ignored' && <Tag>已忽略</Tag>}</Space>}
                    description={
                      <div>
                        <div>{m.memory_value}</div>
                        <div style={{ color: '#999', fontSize: 12 }}>
                          置信度 {Number(m.confidence || 0).toFixed(2)} · 最近更新 {m.last_seen_at ? dayjs(m.last_seen_at).format('YYYY-MM-DD HH:mm') : '-'}
                          {m.source_conversation_id ? ` · 来源对话 #${m.source_conversation_id}` : ''}
                          {m.source_type ? ` · 来源 ${m.source_type}` : ''}
                          {m.review_status ? ` · 审核 ${m.review_status}` : ''}
                          {m.expires_at ? ` · 有效至 ${dayjs(m.expires_at).format('YYYY-MM-DD HH:mm')}` : ''}
                        </div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </div>
      </Content>

      <Modal
        title="编辑记忆"
        open={!!editing}
        onOk={saveEdit}
        onCancel={() => setEditing(null)}
        okText="保存"
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>记忆值</div>
          <Input value={val} onChange={(e) => setVal(e.target.value)} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>类别</div>
          <Input value={cat} onChange={(e) => setCat(e.target.value)} />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>置信度 (0-1)</div>
          <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} value={conf} onChange={(v) => setConf(Number(v ?? 0.7))} />
        </div>
        <div style={{ marginTop: 10 }}>
          <div style={{ marginBottom: 4 }}>有效截止时间，留空表示长期有效</div>
          <Input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
        </div>
        <div style={{ marginTop: 10 }}>
          <div style={{ marginBottom: 4 }}>修正原因，可选</div>
          <Input.TextArea value={correctionReason} maxLength={255} rows={2} onChange={(event) => setCorrectionReason(event.target.value)} />
        </div>
      </Modal>

      <Modal
        title={declarationMemory ? `记忆依据：${declarationMemory.memory_key}` : '记忆依据'}
        open={!!declarationMemory}
        onCancel={() => setDeclarationMemory(null)}
        footer={<Button onClick={() => setDeclarationMemory(null)}>关闭</Button>}
        width={720}
      >
        <List
          loading={declarationsLoading}
          dataSource={declarations}
          locale={{ emptyText: '这条旧记忆尚未有可用的声明记录。之后的手动创建和修订会显示在这里。' }}
          renderItem={(declaration) => {
            const status = declarationStatus(declaration.review_status)
            const availability = declaration.valid_to
              ? `于 ${dayjs(declaration.valid_to).format('YYYY-MM-DD HH:mm')} 结束有效`
              : declaration.review_status === 'staged'
                ? '等待你的确认，不会用于聊天'
                : declaration.review_status === 'confirmed'
                  ? '当前有效'
                  : '不会用于聊天'
            return (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space wrap>
                      <Tag color={status.color}>{status.label}</Tag>
                      <Tag>{declaration.predicate}</Tag>
                      {declaration.conflicts_with_id && <Tag color="volcano">存在事实冲突</Tag>}
                      <span>由 {declarationCreator(declaration.created_by)} 记录</span>
                    </Space>
                  }
                  description={
                    <div>
                      <div>{declaration.value}</div>
                      <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
                        记录时间 {declaration.observed_at ? dayjs(declaration.observed_at).format('YYYY-MM-DD HH:mm') : '-'}
                        {` · ${availability}`}
                        {declaration.source_type ? ` · 来源 ${declaration.source_type}` : ''}
                        {declaration.resolution_reason ? ` · 处理原因 ${declaration.resolution_reason}` : ''}
                        {declaration.supersedes_id ? ` · 替代声明 #${declaration.supersedes_id}` : ''}
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )
          }}
        />
      </Modal>
    </Layout>
  )
}

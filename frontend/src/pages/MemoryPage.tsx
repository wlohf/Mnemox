import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, List, Space, Tag, Modal, Input, InputNumber, message, Checkbox } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { listMemories, updateMemory, deleteMemory, type MemoryItem } from '../services/memoryApi'

const { Header, Content } = Layout

export function MemoryPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<MemoryItem[]>([])
  const [editing, setEditing] = useState<MemoryItem | null>(null)
  const [val, setVal] = useState('')
  const [cat, setCat] = useState('preference')
  const [conf, setConf] = useState<number>(0.7)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const load = async () => {
    const data = await listMemories()
    setItems(data)
  }

  useEffect(() => {
    void load()
  }, [])

  const openEdit = (m: MemoryItem) => {
    setEditing(m)
    setVal(m.memory_value)
    setCat(m.category)
    setConf(Number(m.confidence || 0.7))
  }

  const saveEdit = async () => {
    if (!editing) return
    const updated = await updateMemory(editing.id, {
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
    message.success('记忆已更新')
    setEditing(null)
    await load()
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
          <Card size="small" title="长期记忆条目">
            <List
              dataSource={items}
              locale={{ emptyText: '暂无记忆条目' }}
              renderItem={(m) => (
                <List.Item
                  onClick={() => toggleSelect(m.id)}
                  style={{ cursor: 'pointer' }}
                  actions={[
                    <Button key="l" size="small" onClick={() => quickToggleLock(m)}>
                      {(m.is_locked || 0) === 1 ? '解锁' : '锁定'}
                    </Button>,
                    <Button key="i" size="small" onClick={() => quickToggleIgnored(m)}>
                      {(m.status || 'active') === 'ignored' ? '恢复' : '忽略'}
                    </Button>,
                    <Button key="e" size="small" icon={<EditOutlined />} onClick={() => openEdit(m)}>编辑</Button>,
                    <Button key="d" size="small" danger icon={<DeleteOutlined />} onClick={() => remove(m)}>删除</Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={<Space><Checkbox checked={selectedIds.has(m.id)} onChange={() => toggleSelect(m.id)} onClick={(e) => e.stopPropagation()} /><Tag>{m.category}</Tag><span>{m.memory_key}</span>{(m.is_locked || 0) === 1 && <Tag color="gold">锁定</Tag>}{(m.status || 'active') === 'ignored' && <Tag>已忽略</Tag>}</Space>}
                    description={
                      <div>
                        <div>{m.memory_value}</div>
                        <div style={{ color: '#999', fontSize: 12 }}>
                          置信度 {Number(m.confidence || 0).toFixed(2)} · 最近更新 {m.last_seen_at ? dayjs(m.last_seen_at).format('YYYY-MM-DD HH:mm') : '-'}
                          {m.source_conversation_id ? ` · 来源对话 #${m.source_conversation_id}` : ''}
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
      </Modal>
    </Layout>
  )
}

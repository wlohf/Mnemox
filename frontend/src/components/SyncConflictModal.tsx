import { useMemo, useState } from 'react'
import { useLiveQuery } from 'dexie-react-hooks'
import { Alert, Button, Col, List, Modal, Row, Space, Tag, Typography, message } from 'antd'
import { CloudOutlined, LaptopOutlined } from '@ant-design/icons'
import { db, type ModuleName } from '../db/studyDb'
import { syncEngine } from '../sync/SyncEngine'

const { Paragraph, Text } = Typography

type SyncConflict = Record<string, unknown> & {
  _localId: string
  _conflictAt: string | null
  _conflictServerData: string | null
}

interface ConflictEntry {
  module: ModuleName
  item: SyncConflict
  server: Record<string, unknown> | null
}

const MODULE_META: Record<ModuleName, { label: string; title: (item: SyncConflict) => string }> = {
  notes: { label: '笔记', title: (item) => asText(item.title, '未命名笔记') },
  goals: { label: '目标', title: (item) => asText(item.title, '未命名目标') },
  goalTasks: { label: '任务', title: (item) => asText(item.title, '未命名任务') },
  ankiCards: { label: '记忆卡', title: (item) => asText(item.front, '未命名记忆卡') },
  wrongQuestions: { label: '错题', title: (item) => asText(item.content, '未命名错题') },
}

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function parseServerData(value: string | null): Record<string, unknown> | null {
  if (!value) return null
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function preview(item: Record<string, unknown>, module: ModuleName): string {
  const primary = module === 'ankiCards'
    ? asText(item.front)
    : module === 'wrongQuestions'
      ? asText(item.content)
      : asText(item.title)
  const body = module === 'notes'
    ? asText(item.content)
    : module === 'ankiCards'
      ? asText(item.back)
      : asText(item.description ?? item.explanation)
  return [primary, body].filter(Boolean).join('：') || '无可预览内容'
}

function formatDetectedAt(value: string | null): string {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '刚刚' : date.toLocaleString('zh-CN', { hour12: false })
}

interface SyncConflictModalProps {
  open: boolean
  onClose: () => void
}

export function SyncConflictModal({ open, onClose }: SyncConflictModalProps) {
  const liveConflicts = useLiveQuery(async (): Promise<ConflictEntry[]> => {
    const modules = Object.keys(MODULE_META) as ModuleName[]
    const records: ConflictEntry[][] = await Promise.all(modules.map(async (module) => {
      const rows = await db.table(module).toArray() as SyncConflict[]
      return rows
        .filter((row) => row._syncStatus === 'conflicted')
        .map((row) => ({ module, item: row, server: parseServerData(row._conflictServerData) }))
    }))
    return records.flat()
  }, [])
  const conflicts = liveConflicts ?? []
  const [resolvingKey, setResolvingKey] = useState<string | null>(null)

  const conflictCount = conflicts.length
  const title = useMemo(
    () => `处理同步冲突${conflictCount ? `（${conflictCount}）` : ''}`,
    [conflictCount],
  )

  const resolve = async (
    module: ModuleName,
    localId: string,
    strategy: 'keep_local' | 'use_server',
  ) => {
    const key = `${module}:${localId}:${strategy}`
    setResolvingKey(key)
    try {
      await syncEngine.resolveConflict(module, localId, strategy)
      message.success(strategy === 'keep_local' ? '已保留本机版本并重新同步' : '已采用云端版本')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '冲突处理失败，请重试')
    } finally {
      setResolvingKey(null)
    }
  }

  return (
    <Modal title={title} open={open} onCancel={onClose} footer={null} width={760} destroyOnHidden>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          message="同一条内容在本机离线期间和云端都被修改过"
          description="系统没有自动覆盖任何一边。请核对摘要后选择保留本机版本，或采用云端版本。采用云端会丢弃这次未同步的本机修改。"
        />
        <List
          dataSource={conflicts}
          locale={{ emptyText: '没有待处理的同步冲突' }}
          renderItem={({ module, item, server }) => {
            const meta = MODULE_META[module]
            const titleText = meta.title(item)
            const key = `${module}:${item._localId}`
            return (
              <List.Item key={key} style={{ alignItems: 'stretch' }}>
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag color="gold">{meta.label}</Tag>
                    <Text strong style={{ overflowWrap: 'anywhere' }}>{titleText}</Text>
                    <Text type="secondary">发现于 {formatDetectedAt(item._conflictAt)}</Text>
                  </Space>
                  <Row gutter={[12, 12]}>
                    <Col xs={24} sm={12} style={{ minWidth: 0 }}>
                      <Text strong><LaptopOutlined /> 本机未同步版本</Text>
                      <Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }} style={{ margin: '4px 0 0', overflowWrap: 'anywhere' }}>
                        {preview(item, module)}
                      </Paragraph>
                    </Col>
                    <Col xs={24} sm={12} style={{ minWidth: 0 }}>
                      <Text strong><CloudOutlined /> 云端版本</Text>
                      <Paragraph ellipsis={{ rows: 3, expandable: true, symbol: '展开' }} style={{ margin: '4px 0 0', overflowWrap: 'anywhere' }}>
                        {server ? preview(server, module) : '云端版本摘要不可用；仍可采用后重新拉取。'}
                      </Paragraph>
                    </Col>
                  </Row>
                  <Space wrap>
                    <Button
                      type="primary"
                      loading={resolvingKey === `${key}:keep_local`}
                      onClick={() => void resolve(module, item._localId, 'keep_local')}
                    >
                      保留本机并同步
                    </Button>
                    <Button
                      danger
                      loading={resolvingKey === `${key}:use_server`}
                      onClick={() => void resolve(module, item._localId, 'use_server')}
                    >
                      采用云端版本
                    </Button>
                  </Space>
                </Space>
              </List.Item>
            )
          }}
        />
      </Space>
    </Modal>
  )
}

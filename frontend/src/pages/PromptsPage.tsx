import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Layout, Card, List, Button, Tag, message, Spin, Typography,
  Space, Tooltip, Badge, Input, Divider
} from 'antd'
import {
  EditOutlined, ReloadOutlined, CheckOutlined, ArrowLeftOutlined,
  InfoCircleOutlined, SaveOutlined
} from '@ant-design/icons'
import { PageShell } from '../components/PageShell'
import {
  listPrompts, updatePrompt, resetPrompt,
  type PromptTemplate
} from '../services/promptApi'

const { TextArea } = Input
const { Text, Paragraph } = Typography

// 每种模式的使用说明
const MODE_DESCRIPTIONS: Record<string, { desc: string; variables?: string[] }> = {
  coach:      { desc: '主对话教练人格，所有对话都会注入此 Prompt', variables: [] },
  feynman:    { desc: '费曼学习法评估，用于用户用自己的话解释知识点时', variables: ['{knowledge_point}', '{user_explanation}'] },
  socratic:   { desc: '苏格拉底式提问，通过追问引导深度思考', variables: ['{topic}', '{user_response}'] },
  review:     { desc: '复习引导，提出问题检测用户对知识点的记忆', variables: ['{knowledge_points}'] },
  quiz:       { desc: '出题模式，根据学习资料生成练习题', variables: ['{material_content}', '{num_questions}'] },
  error:      { desc: '错题分析，帮助用户理解错误原因', variables: ['{question}', '{correct_answer}', '{user_answer}'] },
  summary:    { desc: '总结引导，帮助用户提炼今天所学', variables: ['{session_content}'] },
  explain:    { desc: '概念讲解，用大白话解释复杂概念', variables: ['{content}'] },
  distracted_care: { desc: '走神关怀，当用户番茄钟因状态不好中断时的 AI 回应风格', variables: [] },
  okr:        { desc: 'OKR 目标拆解，将学习目标拆解为可执行任务', variables: ['{goal_description}', '{material_info}', '{deadline}'] },
}

export function PromptsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedKey, setSelectedKey] = useState<string>('')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [dirty, setDirty] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const data = await listPrompts()
    if (data) {
      setTemplates(data.templates)
      // 支持 URL 参数 ?mode=feynman 直接定位
      const modeParam = searchParams.get('mode')
      const defaultKey = modeParam && data.templates.find(t => t.mode_key === modeParam)
        ? modeParam
        : data.templates[0]?.mode_key ?? ''
      setSelectedKey(defaultKey)
      const tpl = data.templates.find(t => t.mode_key === defaultKey)
      setEditContent(tpl?.content ?? '')
    }
    setLoading(false)
  }, [searchParams])

  useEffect(() => { void load() }, [load])

  const handleSelect = (key: string) => {
    setSelectedKey(key)
    const tpl = templates.find(t => t.mode_key === key)
    setEditContent(tpl?.content ?? '')
    setDirty(false)
  }

  const handleSave = async () => {
    if (!selectedKey) return
    setSaving(true)
    const ok = await updatePrompt(selectedKey, editContent)
    if (ok) {
      message.success('已保存')
      setTemplates(prev => prev.map(t =>
        t.mode_key === selectedKey ? { ...t, content: editContent, is_custom: true } : t
      ))
      setDirty(false)
    } else {
      message.error('保存失败')
    }
    setSaving(false)
  }

  const handleReset = async () => {
    if (!selectedKey) return
    setResetting(true)
    const ok = await resetPrompt(selectedKey)
    if (ok) {
      message.success('已恢复默认')
      // 重新加载以获取默认内容
      const data = await listPrompts()
      if (data) {
        setTemplates(data.templates)
        const tpl = data.templates.find(t => t.mode_key === selectedKey)
        setEditContent(tpl?.content ?? '')
      }
      setDirty(false)
    } else {
      message.error('恢复失败')
    }
    setResetting(false)
  }

  const selected = templates.find(t => t.mode_key === selectedKey)
  const modeInfo = MODE_DESCRIPTIONS[selectedKey] ?? { desc: '', variables: [] }

  return (
    <PageShell title="Prompt 模板管理" onBack={() => navigate('/')}>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : (
        <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 120px)' }}>

          {/* 左侧：模式列表 */}
          <Card
            style={{ width: 240, flexShrink: 0, overflow: 'auto' }}
            bodyStyle={{ padding: 0 }}
            title={<span style={{ fontSize: 13 }}>学习模式</span>}
          >
            <List
              dataSource={templates}
              renderItem={(tpl) => (
                <List.Item
                  style={{
                    padding: '10px 16px',
                    cursor: 'pointer',
                    background: tpl.mode_key === selectedKey ? 'var(--bg-hover, #f5f0e8)' : 'transparent',
                    borderLeft: tpl.mode_key === selectedKey ? '3px solid var(--primary, #d4a96a)' : '3px solid transparent',
                    transition: 'all 0.15s',
                  }}
                  onClick={() => handleSelect(tpl.mode_key)}
                >
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text style={{ fontSize: 13, fontWeight: tpl.mode_key === selectedKey ? 600 : 400 }}>
                        {tpl.mode_name}
                      </Text>
                      {tpl.is_custom && (
                        <Badge dot color="blue" />
                      )}
                    </div>
                  </div>
                </List.Item>
              )}
            />
          </Card>

          {/* 右侧：编辑器 */}
          <Card
            style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
            bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 20 }}
            title={
              <Space>
                <EditOutlined />
                <span>{selected?.mode_name ?? ''}</span>
                {selected?.is_custom && <Tag color="blue">已自定义</Tag>}
                {dirty && <Tag color="orange">未保存</Tag>}
              </Space>
            }
            extra={
              <Space>
                <Tooltip title="恢复为系统默认 Prompt">
                  <Button
                    icon={<ReloadOutlined />}
                    size="small"
                    loading={resetting}
                    onClick={handleReset}
                    disabled={!selected?.is_custom}
                  >
                    恢复默认
                  </Button>
                </Tooltip>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  size="small"
                  loading={saving}
                  onClick={handleSave}
                  disabled={!dirty}
                >
                  保存
                </Button>
              </Space>
            }
          >
            {/* 说明 */}
            {modeInfo.desc && (
              <div style={{
                background: 'var(--bg-secondary, #faf5ed)',
                border: '1px solid var(--border-color, #e8e0d4)',
                borderRadius: 6,
                padding: '8px 12px',
                marginBottom: 12,
                fontSize: 12,
                color: 'var(--text-secondary)',
              }}>
                <InfoCircleOutlined style={{ marginRight: 6 }} />
                {modeInfo.desc}
                {modeInfo.variables && modeInfo.variables.length > 0 && (
                  <span style={{ marginLeft: 8 }}>
                    可用变量：{modeInfo.variables.map(v => (
                      <Tag key={v} style={{ fontSize: 11, margin: '0 2px' }}>{v}</Tag>
                    ))}
                  </span>
                )}
              </div>
            )}

            {/* 文本编辑器 */}
            <TextArea
              value={editContent}
              onChange={(e) => { setEditContent(e.target.value); setDirty(true) }}
              style={{
                flex: 1,
                fontFamily: 'monospace',
                fontSize: 13,
                lineHeight: 1.6,
                resize: 'none',
                border: '1px solid var(--border-color, #e8e0d4)',
                borderRadius: 6,
              }}
              placeholder="在此输入自定义 Prompt..."
            />

            <Divider style={{ margin: '12px 0' }} />
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'right' }}>
              {selected?.updated_at
                ? `上次修改：${new Date(selected.updated_at).toLocaleString('zh-CN')}`
                : '使用系统默认 Prompt'}
            </div>
          </Card>
        </div>
      )}
    </PageShell>
  )
}

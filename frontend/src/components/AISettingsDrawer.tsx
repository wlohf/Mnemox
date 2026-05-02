import { useState, useEffect } from 'react'
import {
  Drawer,
  Select,
  Card,
  Input,
  InputNumber,
  Button,
  message,
  Space,
  Tag,
  Spin,
} from 'antd'
import {
  CheckCircleOutlined,
  ApiOutlined,
  SaveOutlined,
  LoadingOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import {
  getAllProviders,
  getRoutingSettings,
  updateProvider,
  updateRoutingSetting,
  setActiveProvider,
  testProvider,
  createProvider,
  deleteProvider,
  getRagSettings,
  updateRagSettings,
  testRagEmbedding,
  type AIProvider,
  type AIRoutingItem,
  type RagSettings,
} from '../services/aiSettingsApi'

interface AISettingsDrawerProps {
  open: boolean
  onClose: () => void
}

interface EditState {
  api_key: string
  base_url: string
  model: string
}

export function AISettingsDrawer({ open, onClose }: AISettingsDrawerProps) {
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)
  const [editStates, setEditStates] = useState<Record<string, EditState>>({})
  const [savingProvider, setSavingProvider] = useState<string | null>(null)
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  const [routingSettings, setRoutingSettings] = useState<AIRoutingItem[]>([])
  const [savingScenario, setSavingScenario] = useState<string | null>(null)
  const [creatingProvider, setCreatingProvider] = useState(false)
  const [newProvider, setNewProvider] = useState({
    display_name: '',
    provider_name: '',
    provider_type: 'openai',
    api_key: '',
    base_url: '',
    model: '',
  })

  // RAG settings state
  const [ragSettings, setRagSettings] = useState<RagSettings | null>(null)
  const [ragEdit, setRagEdit] = useState({
    api_key: '',
    base_url: '',
    model: '',
    chunk_size: 512,
    chunk_overlap: 64,
    top_k: 5,
    similarity_threshold: 0.3,
  })
  const [savingRag, setSavingRag] = useState(false)
  const [testingRag, setTestingRag] = useState(false)

  const loadProviders = async () => {
    setLoading(true)
    const data = await getAllProviders()
    const routeData = await getRoutingSettings()
    const ragData = await getRagSettings()
    if (data) {
      setProviders(data)
      const states: Record<string, EditState> = {}
      for (const p of data) {
        states[p.provider_name] = {
          api_key: '',
          base_url: p.base_url,
          model: p.model,
        }
      }
      setEditStates(states)
    }
    if (routeData) {
      setRoutingSettings(routeData)
    }
    if (ragData) {
      setRagSettings(ragData)
      setRagEdit({
        api_key: '',
        base_url: ragData.base_url,
        model: ragData.model,
        chunk_size: ragData.chunk_size ?? 512,
        chunk_overlap: ragData.chunk_overlap ?? 64,
        top_k: ragData.top_k ?? 5,
        similarity_threshold: ragData.similarity_threshold ?? 0.3,
      })
    }
    setLoading(false)
  }

  useEffect(() => {
    if (open) loadProviders()
  }, [open])

  const activeProvider = providers.find((p) => p.is_active)
  const builtInProviders = new Set(['deepseek', 'openai', 'claude', 'gemini', 'qwen'])
  const providerBasePlaceholder =
    newProvider.provider_type === 'anthropic'
      ? 'https://api.ikuncode.cc/v1/messages'
      : newProvider.provider_type === 'gemini'
        ? 'https://api.ikuncode.cc/v1beta/models'
        : 'https://api.openai.com/v1'

  const handleActiveChange = async (providerName: string) => {
    const result = await setActiveProvider(providerName)
    if (result) {
      setProviders((prev) =>
        prev.map((p) => ({ ...p, is_active: p.provider_name === providerName }))
      )
      message.success('已切换 AI 提供商')
    } else {
      message.error('切换失败')
    }
  }

  const handleSave = async (providerName: string) => {
    const edit = editStates[providerName]
    if (!edit) return

    setSavingProvider(providerName)
    const updateData: Record<string, string> = {}
    if (edit.api_key) updateData.api_key = edit.api_key
    updateData.base_url = edit.base_url
    updateData.model = edit.model

    const result = await updateProvider(providerName, updateData)
    if (result) {
      setProviders((prev) =>
        prev.map((p) => (p.provider_name === providerName ? result : p))
      )
      setEditStates((prev) => ({
        ...prev,
        [providerName]: { ...prev[providerName], api_key: '' },
      }))
      message.success('保存成功')
    } else {
      message.error('保存失败')
    }
    setSavingProvider(null)
  }

  const handleTest = async (providerName: string) => {
    setTestingProvider(providerName)
    const result = await testProvider(providerName)
    if (result) {
      if (result.success) {
        message.success(result.message)
      } else {
        message.error(result.message)
      }
    } else {
      message.error('测试请求失败，请检查后端是否运行')
    }
    setTestingProvider(null)
  }

  const updateEditState = (providerName: string, field: keyof EditState, value: string) => {
    setEditStates((prev) => ({
      ...prev,
      [providerName]: { ...prev[providerName], [field]: value },
    }))
  }

  const handleRoutingChange = async (scenario: string, providerName?: string) => {
    setSavingScenario(scenario)
    const result = await updateRoutingSetting(scenario, providerName || null)
    if (result) {
      setRoutingSettings((prev) => prev.map((r) => (r.scenario === scenario ? result : r)))
      message.success('场景路由已更新')
    } else {
      message.error('更新场景路由失败')
    }
    setSavingScenario(null)
  }

  const handleRagSave = async () => {
    setSavingRag(true)
    const updateData: Record<string, any> = {}
    if (ragEdit.api_key) updateData.api_key = ragEdit.api_key
    updateData.base_url = ragEdit.base_url
    updateData.model = ragEdit.model
    updateData.chunk_size = ragEdit.chunk_size
    updateData.chunk_overlap = ragEdit.chunk_overlap
    updateData.top_k = ragEdit.top_k
    updateData.similarity_threshold = ragEdit.similarity_threshold

    const result = await updateRagSettings(updateData)
    if (result?.ok) {
      setRagSettings((prev) =>
        prev
          ? {
              ...prev,
              api_key_masked: result.api_key_masked,
              base_url: result.base_url,
              model: result.model,
              initialized: true,
            }
          : prev
      )
      setRagEdit((prev) => ({ ...prev, api_key: '' }))
      message.success('RAG 设置已保存并生效')
    } else {
      message.error('RAG 设置保存失败')
    }
    setSavingRag(false)
  }

  const handleRagTest = async () => {
    setTestingRag(true)
    const result = await testRagEmbedding()
    if (result) {
      if (result.success) {
        message.success(result.message)
      } else {
        message.error(result.message)
      }
    } else {
      message.error('测试请求失败，请检查后端是否运行')
    }
    setTestingRag(false)
  }

  const handleCreateProvider = async () => {
    const displayName = newProvider.display_name.trim()
    if (!displayName) {
      message.error('请输入提供商显示名称')
      return
    }

    setCreatingProvider(true)
    const result = await createProvider({
      display_name: displayName,
      provider_name: newProvider.provider_name.trim() || undefined,
      provider_type: newProvider.provider_type,
      api_key: newProvider.api_key.trim() || undefined,
      base_url: newProvider.base_url.trim() || undefined,
      model: newProvider.model.trim() || undefined,
    })

    if (result) {
      setProviders((prev) => [...prev, result])
      setEditStates((prev) => ({
        ...prev,
        [result.provider_name]: {
          api_key: '',
          base_url: result.base_url,
          model: result.model,
        },
      }))
      setNewProvider({
        display_name: '',
        provider_name: '',
        provider_type: 'openai',
        api_key: '',
        base_url: '',
        model: '',
      })
      message.success('已添加自定义提供商')
    } else {
      message.error('添加失败')
    }
    setCreatingProvider(false)
  }

  const handleDeleteProvider = async (providerName: string) => {
    const ok = await deleteProvider(providerName)
    if (ok) {
      await loadProviders()
      message.success('已删除提供商')
    } else {
      message.error('删除失败')
    }
  }

  return (
    <Drawer
      title="AI 提供商设置"
      placement="right"
      width={520}
      open={open}
      onClose={onClose}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin indicator={<LoadingOutlined style={{ fontSize: 24 }} />} />
        </div>
      ) : (
        <>
          {/* 激活提供商选择 */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ marginBottom: 8, fontSize: 13, color: '#666' }}>
              当前使用的 AI 提供商
            </div>
            <Select
              style={{ width: '100%' }}
              value={activeProvider?.provider_name}
              onChange={handleActiveChange}
              options={providers.map((p) => ({
                label: p.display_name,
                value: p.provider_name,
              }))}
            />
          </div>

          <Card size="small" style={{ marginBottom: 16 }} title="按场景路由（可用低成本模型处理重复任务）">
            <div style={{ display: 'grid', gap: 12 }}>
              {routingSettings.map((item) => (
                <div key={item.scenario}>
                  <div style={{ marginBottom: 6, fontSize: 12, color: '#666' }}>{item.label}</div>
                  <Select
                    style={{ width: '100%' }}
                    value={item.provider_name || '__active__'}
                    loading={savingScenario === item.scenario}
                    onChange={(v) => void handleRoutingChange(item.scenario, v === '__active__' ? undefined : v)}
                    options={[
                      { label: '跟随全局激活提供商', value: '__active__' },
                      ...providers.map((p) => ({ label: p.display_name, value: p.provider_name })),
                    ]}
                  />
                </div>
              ))}
            </div>
          </Card>

          <Card size="small" style={{ marginBottom: 16 }} title="添加自定义提供商">
            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>显示名称</div>
              <Input
                placeholder="例如 My Proxy / 自建中转"
                value={newProvider.display_name}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, display_name: e.target.value }))
                }
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>协议类型</div>
              <Select
                style={{ width: '100%' }}
                value={newProvider.provider_type}
                onChange={(value) =>
                  setNewProvider((prev) => ({ ...prev, provider_type: value }))
                }
                options={[
                  { label: 'OpenAI 兼容', value: 'openai' },
                  { label: 'Anthropic (Claude)', value: 'anthropic' },
                  { label: 'Gemini', value: 'gemini' },
                ]}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>标识（可选）</div>
              <Input
                placeholder="留空自动生成，例如 my-proxy"
                value={newProvider.provider_name}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, provider_name: e.target.value }))
                }
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>API Key</div>
              <Input.Password
                placeholder="输入 API Key（可留空稍后填写）"
                value={newProvider.api_key}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, api_key: e.target.value }))
                }
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Base URL</div>
              <Input
                placeholder={providerBasePlaceholder}
                value={newProvider.base_url}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, base_url: e.target.value }))
                }
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>模型名称</div>
              <Input
                placeholder="例如 gpt-4o, deepseek-chat"
                value={newProvider.model}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, model: e.target.value }))
                }
              />
            </div>

            <div style={{ marginBottom: 8 }}>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={creatingProvider}
                onClick={handleCreateProvider}
              >
                添加提供商
              </Button>
            </div>

            <div style={{ fontSize: 12, color: '#999' }}>
              自定义提供商按 OpenAI 兼容接口处理。
            </div>
          </Card>

          {/* RAG 知识库 Embedding 设置 */}
          <Card
            size="small"
            style={{ marginBottom: 16 }}
            title={
              <Space>
                <DatabaseOutlined />
                <span>RAG 知识库 (Embedding)</span>
                {ragSettings?.initialized && ragSettings.embedding_enabled ? (
                  <Tag color="green">在线 · {ragSettings.total_chunks} chunks</Tag>
                ) : ragSettings?.initialized ? (
                  <Tag color="orange">Fallback · 未配置 Embedding</Tag>
                ) : (
                  <Tag color="default">未初始化</Tag>
                )}
              </Space>
            }
          >
            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                API Key
                {ragSettings?.api_key_masked && (
                  <span style={{ marginLeft: 8, color: '#999' }}>
                    (当前: {ragSettings.api_key_masked})
                  </span>
                )}
              </div>
              <Input.Password
                placeholder="输入 Embedding API Key（留空则不修改）"
                value={ragEdit.api_key}
                onChange={(e) => setRagEdit((prev) => ({ ...prev, api_key: e.target.value }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Base URL</div>
              <Input
                placeholder="https://api.openai.com/v1"
                value={ragEdit.base_url}
                onChange={(e) => setRagEdit((prev) => ({ ...prev, base_url: e.target.value }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Embedding 模型</div>
              <Input
                placeholder="text-embedding-3-small"
                value={ragEdit.model}
                onChange={(e) => setRagEdit((prev) => ({ ...prev, model: e.target.value }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Chunk Size（分块大小）</div>
              <InputNumber
                min={64}
                max={4096}
                step={64}
                style={{ width: '100%' }}
                value={ragEdit.chunk_size}
                onChange={(v) => setRagEdit((prev) => ({ ...prev, chunk_size: v ?? 512 }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Chunk Overlap（分块重叠）</div>
              <InputNumber
                min={0}
                max={1024}
                step={16}
                style={{ width: '100%' }}
                value={ragEdit.chunk_overlap}
                onChange={(v) => setRagEdit((prev) => ({ ...prev, chunk_overlap: v ?? 64 }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Top K（检索结果数）</div>
              <InputNumber
                min={1}
                max={50}
                step={1}
                style={{ width: '100%' }}
                value={ragEdit.top_k}
                onChange={(v) => setRagEdit((prev) => ({ ...prev, top_k: v ?? 5 }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Similarity Threshold（相似度阈值）</div>
              <InputNumber
                min={0}
                max={1}
                step={0.05}
                style={{ width: '100%' }}
                value={ragEdit.similarity_threshold}
                onChange={(v) => setRagEdit((prev) => ({ ...prev, similarity_threshold: v ?? 0.3 }))}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={savingRag}
                  onClick={handleRagSave}
                >
                  保存
                </Button>
                <Button
                  icon={<ApiOutlined />}
                  loading={testingRag}
                  onClick={handleRagTest}
                >
                  测试连接
                </Button>
              </Space>
            </div>

            <div style={{ fontSize: 12, color: '#999' }}>
              需要 OpenAI 兼容的 /v1/embeddings 接口。大部分中转站选 "OpenAI compatible" 格式即可。
            </div>
            {ragSettings?.last_retrieval_status?.message && (
              <div style={{ marginTop: 8, fontSize: 12, color: ragSettings.fallback_active ? '#fa8c16' : '#52c41a' }}>
                最近检索状态：{ragSettings.last_retrieval_status.message}
              </div>
            )}
            {ragSettings?.last_error && (
              <div style={{ marginTop: 4, fontSize: 12, color: '#ff4d4f' }}>
                最近错误：{ragSettings.last_error}
              </div>
            )}
          </Card>

          {/* 提供商列表 */}
          {providers.map((provider) => {
            const isExpanded = expandedProvider === provider.provider_name
            const edit = editStates[provider.provider_name]
            const isCustom = !builtInProviders.has(provider.provider_name)

            return (
              <Card
                key={provider.provider_name}
                size="small"
                style={{
                  marginBottom: 12,
                  border: provider.is_active
                    ? '1px solid #1890ff'
                    : '1px solid #f0f0f0',
                }}
                title={
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                    }}
                    onClick={() =>
                      setExpandedProvider(isExpanded ? null : provider.provider_name)
                    }
                  >
                    <Space>
                      <span>{provider.display_name}</span>
                      {provider.is_active && (
                        <Tag color="blue" icon={<CheckCircleOutlined />}>
                          使用中
                        </Tag>
                      )}
                    </Space>
                    <span style={{ fontSize: 12, color: '#999' }}>
                      {provider.api_key_masked || '未配置'}
                      {provider.model ? ` · ${provider.model}` : ''}
                    </span>
                  </div>
                }
              >
                {isExpanded && edit && (
                  <div>
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        API Key
                        {provider.api_key_masked && (
                          <span style={{ marginLeft: 8, color: '#999' }}>
                            (当前: {provider.api_key_masked})
                          </span>
                        )}
                      </div>
                      <Input.Password
                        placeholder="输入新的 API Key（留空则不修改）"
                        value={edit.api_key}
                        onChange={(e) =>
                          updateEditState(provider.provider_name, 'api_key', e.target.value)
                        }
                      />
                    </div>

                    <div style={{ marginBottom: 12 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        Base URL
                      </div>
                      <Input
                        placeholder="API 地址（如有自定义代理）"
                        value={edit.base_url}
                        onChange={(e) =>
                          updateEditState(provider.provider_name, 'base_url', e.target.value)
                        }
                      />
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        模型名称
                      </div>
                      <Input
                        placeholder="例如 gpt-4, deepseek-chat"
                        value={edit.model}
                        onChange={(e) =>
                          updateEditState(provider.provider_name, 'model', e.target.value)
                        }
                      />
                    </div>

                    <Space>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        loading={savingProvider === provider.provider_name}
                        onClick={() => handleSave(provider.provider_name)}
                      >
                        保存
                      </Button>
                      <Button
                        icon={<ApiOutlined />}
                        loading={testingProvider === provider.provider_name}
                        onClick={() => handleTest(provider.provider_name)}
                      >
                        测试连接
                      </Button>
                      {isCustom && (
                        <Button
                          danger
                          onClick={() => void handleDeleteProvider(provider.provider_name)}
                        >
                          删除
                        </Button>
                      )}
                    </Space>
                  </div>
                )}
              </Card>
            )
          })}
        </>
      )}
    </Drawer>
  )
}

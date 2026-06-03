import { useState, useEffect } from 'react'
import {
  Drawer,
  Select,
  AutoComplete,
  Collapse,
  Card,
  Alert,
  Input,
  InputNumber,
  Button,
  Switch,
  message,
  Space,
  Tag,
  Spin,
  Tooltip,
} from 'antd'
import {
  CheckCircleOutlined,
  ApiOutlined,
  SaveOutlined,
  LoadingOutlined,
  DatabaseOutlined,
  SearchOutlined,
  DeleteOutlined,
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
  searchProviderModels,
  notifyAIProvidersUpdated,
  type AIProvider,
  type AIRoutingItem,
  type RagSettings,
} from '../services/aiSettingsApi'
import { getApiErrorMessage } from '../services/apiClient'

interface AISettingsDrawerProps {
  open: boolean
  onClose: () => void
}

function showApiError(error: unknown, fallback: string) {
  message.error(getApiErrorMessage(error, fallback))
}

interface EditState {
  api_key: string
  clear_api_key: boolean
  base_url: string
  model: string
  available_models: string[]
  test_model: string
}

interface ProviderFeedback {
  type: 'success' | 'error' | 'info'
  title: string
  detail?: string
  providerName?: string
  model?: string
  baseUrl?: string
  timestamp: number
}

function normalizeModels(models: string[]) {
  return Array.from(new Set(models.map((model) => model.trim()).filter(Boolean)))
}

function withDefaultModel(models: string[], model?: string) {
  return normalizeModels([model || '', ...models])
}

function modelOptions(models: string[], model?: string) {
  return withDefaultModel(models, model).map((item) => ({ label: item, value: item }))
}

function resolveValidationModel(
  testModel: string | undefined,
  model: string | undefined,
  availableModels: string[],
) {
  const candidates = withDefaultModel(availableModels, model)
  const preferred = (testModel || '').trim()
  if (preferred && candidates.includes(preferred)) {
    return preferred
  }
  return candidates[0] || ''
}

function buildProviderEditStates(data: AIProvider[]): Record<string, EditState> {
  const states: Record<string, EditState> = {}
  for (const p of data) {
    const availableModels = normalizeModels(p.available_models || [])
    states[p.provider_name] = {
      api_key: '',
      clear_api_key: false,
      base_url: p.base_url,
      model: p.model,
      available_models: availableModels,
      test_model: resolveValidationModel(p.model, p.model, availableModels),
    }
  }
  return states
}

export function AISettingsDrawer({ open, onClose }: AISettingsDrawerProps) {
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)
  const [editStates, setEditStates] = useState<Record<string, EditState>>({})
  const [savingProvider, setSavingProvider] = useState<string | null>(null)
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  const [searchingProvider, setSearchingProvider] = useState<string | null>(null)
  const [providerFeedback, setProviderFeedback] = useState<Record<string, ProviderFeedback>>({})
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
    available_models: [] as string[],
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
    try {
      const [providersResult, routingResult, ragResult] = await Promise.allSettled([
        getAllProviders(),
        getRoutingSettings(),
        getRagSettings(),
      ])

      if (providersResult.status === 'fulfilled') {
        setProviders(providersResult.value)
        setEditStates(buildProviderEditStates(providersResult.value))
      } else {
        showApiError(providersResult.reason, '加载 AI 提供商失败')
      }

      if (routingResult.status === 'fulfilled') {
        setRoutingSettings(routingResult.value)
      } else {
        showApiError(routingResult.reason, '加载场景路由失败')
      }

      if (ragResult.status === 'fulfilled') {
        const ragData = ragResult.value
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
      } else {
        showApiError(ragResult.reason, '加载 RAG 设置失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) loadProviders()
  }, [open])

  const setProviderResult = (providerName: string, feedback: Omit<ProviderFeedback, 'timestamp'>) => {
    setProviderFeedback((prev) => ({
      ...prev,
      [providerName]: {
        ...feedback,
        timestamp: Date.now(),
      },
    }))
  }

  const activeProvider = providers.find((p) => p.is_active)
  const providerBasePlaceholder =
    newProvider.provider_type === 'anthropic'
      ? 'https://api.ikuncode.cc/v1/messages'
      : newProvider.provider_type === 'gemini'
        ? 'https://api.ikuncode.cc/v1beta/models'
        : 'https://api.openai.com/v1'

  const handleActiveChange = async (providerName: string) => {
    try {
      const result = await setActiveProvider(providerName)
      setProviders((prev) =>
        prev.map((p) => ({ ...p, is_active: p.provider_name === providerName }))
      )
      notifyAIProvidersUpdated({
        providerName: result.provider_name,
        model: result.model,
        availableModels: withDefaultModel(result.available_models || [], result.model),
        selectModel: true,
      })
      message.success('已切换 AI 提供商')
    } catch (error) {
      showApiError(error, '切换 AI 提供商失败')
    }
  }

  const handleSave = async (providerName: string) => {
    const edit = editStates[providerName]
    if (!edit) return

    setSavingProvider(providerName)
    const selectedModels = normalizeModels(edit.available_models)
    const defaultModel = edit.model.trim() || selectedModels[0] || ''
    const updateData: Record<string, any> = {}
    if (edit.clear_api_key) {
      updateData.api_key = ''
    } else if (edit.api_key.trim()) {
      updateData.api_key = edit.api_key.trim()
    }
    updateData.base_url = edit.base_url
    updateData.model = defaultModel
    updateData.available_models = selectedModels

    try {
      const result = await updateProvider(providerName, updateData)
      const savedModels = normalizeModels(result.available_models || [])
      setProviders((prev) =>
        prev.map((p) => (p.provider_name === providerName ? result : p))
      )
      setEditStates((prev) => ({
        ...prev,
        [providerName]: {
          api_key: '',
          clear_api_key: false,
          base_url: result.base_url,
          model: result.model,
          available_models: savedModels,
          test_model: resolveValidationModel(edit.test_model, result.model, savedModels),
        },
      }))
      notifyAIProvidersUpdated({
        providerName: result.provider_name,
        model: result.model || savedModels[0],
        availableModels: savedModels,
        selectModel: true,
      })
      setProviderResult(providerName, {
        type: 'success',
        title: '保存成功',
        detail: edit.clear_api_key ? '已清空保存的 API Key。' : '配置已写入当前账户。',
        providerName: result.provider_name,
        model: result.model,
        baseUrl: result.base_url,
      })
      message.success('保存成功')
    } catch (error) {
      setProviderResult(providerName, {
        type: 'error',
        title: '保存失败',
        detail: getApiErrorMessage(error, '保存 AI 提供商失败'),
        providerName,
        model: edit.model,
        baseUrl: edit.base_url,
      })
      showApiError(error, '保存 AI 提供商失败')
    } finally {
      setSavingProvider(null)
    }
  }

  const handleTest = async (providerName: string) => {
    const edit = editStates[providerName]
    if (!edit) return

    const selectedTestModel =
      edit.test_model.trim() || edit.model.trim() || edit.available_models[0] || ''
    if (!selectedTestModel) {
      message.error('请先点击“搜索模型”，再选择一个模型进行验证')
      return
    }

    setTestingProvider(providerName)
    try {
      const apiKeyForTest = edit.clear_api_key
        ? ''
        : edit.api_key.trim()
          ? edit.api_key.trim()
          : undefined
      const result = await testProvider(providerName, {
        api_key: apiKeyForTest,
        base_url: edit.base_url.trim() || undefined,
        model: selectedTestModel,
      })
      if (result.success) {
        setProviderResult(providerName, {
          type: 'success',
          title: '测试通过',
          detail: result.message,
          providerName: result.provider_name || providerName,
          model: result.model || selectedTestModel,
          baseUrl: edit.base_url,
        })
        message.success(result.message)
      } else {
        setProviderResult(providerName, {
          type: 'error',
          title: '测试失败',
          detail: result.message,
          providerName: result.provider_name || providerName,
          model: result.model || selectedTestModel,
          baseUrl: edit.base_url,
        })
        message.error(result.message)
      }
    } catch (error) {
      setProviderResult(providerName, {
        type: 'error',
        title: '测试请求失败',
        detail: getApiErrorMessage(error, '测试请求失败，请检查后端是否运行'),
        providerName,
        model: selectedTestModel,
        baseUrl: edit.base_url,
      })
      showApiError(error, '测试请求失败，请检查后端是否运行')
    } finally {
      setTestingProvider(null)
    }
  }

  const updateEditState = (
    providerName: string,
    field: keyof EditState,
    value: string | string[] | boolean,
  ) => {
    setEditStates((prev) => ({
      ...prev,
      [providerName]: { ...prev[providerName], [field]: value },
    }))
  }

  const updateProviderDefaultModel = (providerName: string, model: string) => {
    setEditStates((prev) => {
      const current = prev[providerName]
      if (!current) return prev
      return {
        ...prev,
        [providerName]: {
          ...current,
          model,
          test_model: resolveValidationModel(current.test_model, model, current.available_models),
        },
      }
    })
  }

  const updateProviderTestModel = (providerName: string, testModel: string) => {
    setEditStates((prev) => {
      const current = prev[providerName]
      if (!current) return prev
      return {
        ...prev,
        [providerName]: {
          ...current,
          test_model: testModel,
        },
      }
    })
  }

  const updateProviderAvailableModels = (providerName: string, models: string[]) => {
    setEditStates((prev) => {
      const current = prev[providerName]
      if (!current) return prev
      const availableModels = normalizeModels(models)
      const nextModel =
        current.model && availableModels.includes(current.model)
          ? current.model
          : availableModels[0] || current.model
      return {
        ...prev,
        [providerName]: {
          ...current,
          available_models: availableModels,
          model: nextModel,
          test_model: resolveValidationModel(current.test_model, nextModel, availableModels),
        },
      }
    })
  }

  const handleSearchModels = async (providerName: string) => {
    const edit = editStates[providerName]
    if (!edit) return

    setSearchingProvider(providerName)
    try {
      const apiKeyForSearch = edit.clear_api_key
        ? ''
        : edit.api_key.trim()
          ? edit.api_key.trim()
          : undefined
      const result = await searchProviderModels(providerName, {
        api_key: apiKeyForSearch,
        base_url: edit.base_url.trim() || undefined,
        model_hint: edit.model.trim() || undefined,
      })
      const discoveredModels = normalizeModels(result.models)
      setEditStates((prev) => ({
        ...prev,
        [providerName]: {
          ...prev[providerName],
          available_models: discoveredModels,
          model: prev[providerName]?.model || discoveredModels[0] || '',
          test_model: resolveValidationModel(
            prev[providerName]?.test_model,
            prev[providerName]?.model || discoveredModels[0] || '',
            discoveredModels,
          ),
        },
      }))
      setProviderResult(providerName, {
        type: 'success',
        title: '模型搜索成功',
        detail: `已发现 ${discoveredModels.length} 个模型。请先选择“验证模型”，确认可用后再保存。`,
        providerName,
        model: edit.model || discoveredModels[0],
        baseUrl: edit.base_url,
      })
      message.success(`已发现 ${discoveredModels.length} 个模型，请先选择模型进行验证`)
    } catch (error) {
      setProviderResult(providerName, {
        type: 'error',
        title: '模型搜索失败',
        detail: getApiErrorMessage(error, '搜索模型失败，请检查 API Key 和 Base URL'),
        providerName,
        model: edit.model,
        baseUrl: edit.base_url,
      })
      showApiError(error, '搜索模型失败，请检查 API Key 和 Base URL')
    } finally {
      setSearchingProvider(null)
    }
  }

  const getModelsForProvider = (providerName?: string | null) => {
    const provider = providers.find((p) => p.provider_name === providerName)
    if (!provider) return []
    return Array.from(new Set([provider.model, ...(provider.available_models || [])].filter(Boolean)))
  }

  const handleRoutingChange = async (scenario: string, providerName?: string | null, model?: string | null) => {
    setSavingScenario(scenario)
    try {
      const result = await updateRoutingSetting(scenario, providerName || null, model || null)
      setRoutingSettings((prev) => prev.map((r) => (r.scenario === scenario ? result : r)))
      message.success('场景路由已更新')
    } catch (error) {
      showApiError(error, '更新场景路由失败')
    } finally {
      setSavingScenario(null)
    }
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

    try {
      const result = await updateRagSettings(updateData)
      if (!result.ok) {
        message.error('RAG 设置保存失败')
        return
      }
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
    } catch (error) {
      showApiError(error, 'RAG 设置保存失败')
    } finally {
      setSavingRag(false)
    }
  }

  const handleRagTest = async () => {
    setTestingRag(true)
    try {
      const result = await testRagEmbedding()
      if (result.success) {
        message.success(result.message)
      } else {
        message.error(result.message)
      }
    } catch (error) {
      showApiError(error, '测试请求失败，请检查后端是否运行')
    } finally {
      setTestingRag(false)
    }
  }

  const handleCreateProvider = async () => {
    const displayName = newProvider.display_name.trim()
    if (!displayName) {
      message.error('请输入提供商显示名称')
      return
    }

    setCreatingProvider(true)
    const selectedModels = normalizeModels(newProvider.available_models)
    const defaultModel = newProvider.model.trim() || selectedModels[0] || ''
    try {
      const result = await createProvider({
        display_name: displayName,
        provider_name: newProvider.provider_name.trim() || undefined,
        provider_type: newProvider.provider_type,
        api_key: newProvider.api_key.trim() || undefined,
        base_url: newProvider.base_url.trim() || undefined,
        model: defaultModel || undefined,
        available_models: selectedModels,
      })
      const savedModels = normalizeModels(result.available_models || [])
      setProviders((prev) => [...prev, result])
      setEditStates((prev) => ({
        ...prev,
        [result.provider_name]: {
          api_key: '',
          clear_api_key: false,
          base_url: result.base_url,
          model: result.model,
          available_models: savedModels,
          test_model: resolveValidationModel(result.model, result.model, savedModels),
        },
      }))
      setNewProvider({
        display_name: '',
        provider_name: '',
        provider_type: 'openai',
        api_key: '',
        base_url: '',
        model: '',
        available_models: [],
      })
      notifyAIProvidersUpdated({
        providerName: result.provider_name,
        model: result.model || savedModels[0],
        availableModels: savedModels,
        selectModel: true,
      })
      message.success('已添加自定义提供商')
    } catch (error) {
      showApiError(error, '添加 AI 提供商失败')
    } finally {
      setCreatingProvider(false)
    }
  }

  const handleDeleteProvider = async (providerName: string) => {
    try {
      await deleteProvider(providerName)
      setProviderFeedback((prev) => {
        const next = { ...prev }
        delete next[providerName]
        return next
      })
      await loadProviders()
      notifyAIProvidersUpdated({ resetChatModel: true })
      message.success('已删除提供商')
    } catch (error) {
      showApiError(error, '删除 AI 提供商失败')
    }
  }

  return (
    <Drawer
      title={null}
      placement="right"
      width={560}
      open={open}
      onClose={onClose}
      className="mnemox-ai-settings-drawer"
    >
      <div className="mnemox-ai-drawer-header">
        <div>
          <div className="mnemox-settings-eyebrow">Model routing</div>
          <h2>AI 提供商设置</h2>
        </div>
        <p>管理默认模型、场景路由、RAG Embedding 和自定义中转。</p>
      </div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin indicator={<LoadingOutlined style={{ fontSize: 24 }} />} />
        </div>
      ) : (
        <>
          <div className="mnemox-ai-section mnemox-ai-section-primary">
            <div className="mnemox-ai-field-label">
              默认提供商（路由未指定时使用）
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

          <Collapse
            size="small"
            className="mnemox-ai-collapse"
            items={[{
              key: 'routing',
              label: '按场景路由',
              children: (
                <div style={{ display: 'grid', gap: 14 }}>
              {routingSettings.map((item) => {
                const effectiveProviderName = item.provider_name || activeProvider?.provider_name
                const routeModelOptions = getModelsForProvider(effectiveProviderName)
                return (
                  <div key={item.scenario}>
                    <div style={{ marginBottom: 6, fontSize: 12, color: '#666' }}>{item.label}</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8 }}>
                      <Select
                        style={{ width: '100%' }}
                        value={item.provider_name || '__active__'}
                        loading={savingScenario === item.scenario}
                        onChange={(v) => void handleRoutingChange(item.scenario, v === '__active__' ? null : v, null)}
                        options={[
                          { label: '跟随全局提供商', value: '__active__' },
                          ...providers.map((p) => ({ label: p.display_name, value: p.provider_name })),
                        ]}
                      />
                      <Select
                        style={{ width: '100%' }}
                        value={item.model || '__provider_default__'}
                        loading={savingScenario === item.scenario}
                        onChange={(v) => void handleRoutingChange(
                          item.scenario,
                          item.provider_name || null,
                          v === '__provider_default__' ? null : v
                        )}
                        options={[
                          { label: '使用提供商默认模型', value: '__provider_default__' },
                          ...routeModelOptions.map((model) => ({ label: model, value: model })),
                        ]}
                        popupMatchSelectWidth={false}
                      />
                    </div>
                  </div>
                )
              })}
                </div>
              ),
            }]}
          />

          <Collapse
            size="small"
            className="mnemox-ai-collapse"
            items={[{
              key: 'create-provider',
              label: '添加自定义提供商',
              children: (
                <>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>显示名称</div>
              <Input
                placeholder="例如 My Proxy / 自建中转"
                value={newProvider.display_name}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, display_name: e.target.value }))
                }
              />
            </div>

            <div>
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
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>标识（可选）</div>
              <Input
                placeholder="留空自动生成，例如 my-proxy"
                value={newProvider.provider_name}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, provider_name: e.target.value }))
                }
              />
            </div>

            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>API Key</div>
              <Input.Password
                placeholder="输入 API Key（可留空稍后填写）"
                value={newProvider.api_key}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, api_key: e.target.value }))
                }
              />
            </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Base URL</div>
              <Input
                placeholder={providerBasePlaceholder}
                value={newProvider.base_url}
                onChange={(e) =>
                  setNewProvider((prev) => ({ ...prev, base_url: e.target.value }))
                }
              />
            </div>

            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>默认模型</div>
              <AutoComplete
                style={{ width: '100%' }}
                placeholder="选择或输入默认模型，例如 gpt-4o"
                value={newProvider.model}
                onChange={(value) =>
                  setNewProvider((prev) => ({
                    ...prev,
                    model: value,
                  }))
                }
                onSelect={(value) =>
                  setNewProvider((prev) => ({
                    ...prev,
                    model: value,
                  }))
                }
                options={modelOptions(newProvider.available_models, newProvider.model)}
                filterOption={(inputValue, option) =>
                  String(option?.value || '').toLowerCase().includes(inputValue.toLowerCase())
                }
              />
            </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>可用模型（会出现在对话模型切换中）</div>
              <Select
                mode="tags"
                style={{ width: '100%' }}
                tokenSeparators={[',', '，', ' ']}
                placeholder="输入模型名后回车，可添加多个"
                value={newProvider.available_models}
                onChange={(models) =>
                  setNewProvider((prev) => {
                    const nextModels = normalizeModels(models)
                    const nextModel =
                      prev.model && nextModels.includes(prev.model)
                        ? prev.model
                        : nextModels[0] || prev.model
                    return {
                      ...prev,
                      available_models: nextModels,
                      model: nextModel,
                    }
                  })
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
                </>
              ),
            }]}
          />

          {/* RAG 知识库 Embedding 设置 */}
          <Collapse
            size="small"
            className="mnemox-ai-collapse"
            items={[{
              key: 'rag',
              label: (
                <Space>
                  <DatabaseOutlined />
                  <span>RAG 知识库</span>
                  {ragSettings?.initialized && ragSettings.embedding_enabled ? (
                    <Tag color="green">在线</Tag>
                  ) : ragSettings?.initialized ? (
                    <Tag color="orange">Fallback</Tag>
                  ) : (
                    <Tag color="default">未初始化</Tag>
                  )}
                </Space>
              ),
              children: (
                <>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <div>
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

            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Base URL</div>
              <Input
                placeholder="https://api.openai.com/v1"
                value={ragEdit.base_url}
                onChange={(e) => setRagEdit((prev) => ({ ...prev, base_url: e.target.value }))}
              />
            </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>Embedding 模型</div>
              <Input
                placeholder="text-embedding-3-small"
                value={ragEdit.model}
                onChange={(e) => setRagEdit((prev) => ({ ...prev, model: e.target.value }))}
              />
            </div>

            <div>
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
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12, marginBottom: 12 }}>
            <div>
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

            <div>
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

            <div>
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
            </div>

            <div className="mnemox-ai-collapse">
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
                </>
              ),
            }]}
          />

          {/* 提供商列表 */}
          <Collapse
            size="small"
            defaultActiveKey={['providers']}
            className="mnemox-ai-collapse"
            items={[{
              key: 'providers',
              label: '供应商配置',
              children: (
                <>
          {providers.map((provider) => {
            const isExpanded = expandedProvider === provider.provider_name
            const edit = editStates[provider.provider_name]
            const feedback = providerFeedback[provider.provider_name]

            return (
              <Card
                key={provider.provider_name}
                size="small"
                className={`mnemox-provider-card${provider.is_active ? ' is-active' : ''}`}
                bodyStyle={{
                  display: isExpanded ? undefined : 'none',
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
                    <div className="mnemox-ai-collapse">
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        API Key
                        {provider.api_key_masked && (
                          <span style={{ marginLeft: 8, color: '#999' }}>
                            (当前: {provider.api_key_masked})
                          </span>
                        )}
                      </div>
                      <Space.Compact style={{ width: '100%' }}>
                        <Input.Password
                          placeholder={
                            edit.clear_api_key
                              ? '保存后清空当前 Key'
                              : provider.api_key_masked
                                ? `留空使用已保存 Key（${provider.api_key_masked}）`
                                : '输入 API Key'
                          }
                          value={edit.api_key}
                          disabled={edit.clear_api_key}
                          onChange={(e) => {
                            updateEditState(provider.provider_name, 'api_key', e.target.value)
                            if (e.target.value) {
                              updateEditState(provider.provider_name, 'clear_api_key', false)
                            }
                          }}
                        />
                        <Tooltip title="清空已保存 Key">
                          <Button
                            danger={edit.clear_api_key}
                            icon={<DeleteOutlined />}
                            disabled={!provider.api_key_masked}
                            onClick={() => {
                              updateEditState(provider.provider_name, 'api_key', '')
                              updateEditState(provider.provider_name, 'clear_api_key', !edit.clear_api_key)
                            }}
                          />
                        </Tooltip>
                      </Space.Compact>
                      {edit.clear_api_key && (
                        <div style={{ marginTop: 6, fontSize: 12, color: '#ff4d4f' }}>
                          保存后会删除此供应商的已保存 Key。
                        </div>
                      )}
                    </div>

                    <div className="mnemox-ai-collapse">
                      <Space>
                        <Switch
                          checked={provider.enabled}
                          onChange={(checked) => {
                            setProviders((prev) =>
                              prev.map((p) =>
                                p.provider_name === provider.provider_name ? { ...p, enabled: checked } : p
                              )
                            )
                            void updateProvider(provider.provider_name, { enabled: checked }).catch((error) => {
                              showApiError(error, '更新供应商启用状态失败')
                              setProviders((prev) =>
                                prev.map((p) =>
                                  p.provider_name === provider.provider_name ? { ...p, enabled: !checked } : p
                                )
                              )
                            })
                          }}
                        />
                        <span style={{ fontSize: 12, color: '#666' }}>
                          {provider.enabled ? '已启用' : '已停用，不会出现在对话模型切换中'}
                        </span>
                      </Space>
                    </div>

                    <div className="mnemox-ai-collapse">
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

                    <div className="mnemox-ai-collapse">
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        默认模型（不限制对话切换）
                      </div>
                      <AutoComplete
                        style={{ width: '100%' }}
                        placeholder="选择或输入默认模型"
                        value={edit.model}
                        onChange={(value) => updateProviderDefaultModel(provider.provider_name, value)}
                        onSelect={(value) => updateProviderDefaultModel(provider.provider_name, value)}
                        onBlur={() => updateProviderAvailableModels(provider.provider_name, edit.available_models)}
                        options={modelOptions(edit.available_models || [], edit.model)}
                        filterOption={(inputValue, option) =>
                          String(option?.value || '').toLowerCase().includes(inputValue.toLowerCase())
                        }
                      />
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        可用模型（会出现在对话模型切换中）
                      </div>
                      <Select
                        mode="tags"
                        style={{ width: '100%' }}
                        tokenSeparators={[',', '，', ' ']}
                        placeholder="搜索后会自动填充，也可以手动补充模型名"
                        value={edit.available_models}
                        options={modelOptions(edit.available_models || [], edit.model)}
                        onChange={(models) => {
                          updateProviderAvailableModels(provider.provider_name, models)
                        }}
                        popupMatchSelectWidth={false}
                      />
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        验证模型
                      </div>
                      <Select
                        mode="tags"
                        style={{ width: '100%' }}
                        tokenSeparators={[',', '，', ' ']}
                        placeholder="搜索后会自动填充，也可以手动补充模型名"
                        value={edit.available_models}
                        options={modelOptions(edit.available_models || [], edit.model)}
                        onChange={(models) => {
                          updateProviderAvailableModels(provider.provider_name, models)
                        }}
                        popupMatchSelectWidth={false}
                      />
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>
                        验证模型
                      </div>
                      <Space.Compact style={{ width: '100%' }}>
                        <Select
                          style={{ width: '100%' }}
                          showSearch
                          placeholder={
                            edit.available_models.length > 0
                              ? '从已搜索的模型中选择一个进行验证'
                              : '先点击“搜索模型”获取当前供应商支持的模型'
                          }
                          value={edit.test_model || undefined}
                          options={modelOptions(edit.available_models || [], edit.model)}
                          onChange={(value) => updateProviderTestModel(provider.provider_name, value)}
                          optionFilterProp="label"
                          popupMatchSelectWidth={false}
                        />
                        <Button
                          icon={<SearchOutlined />}
                          loading={searchingProvider === provider.provider_name}
                          onClick={() => void handleSearchModels(provider.provider_name)}
                        >
                          搜索模型
                        </Button>
                        <Button
                          icon={<ApiOutlined />}
                          loading={testingProvider === provider.provider_name}
                          onClick={() => handleTest(provider.provider_name)}
                        >
                          验证
                        </Button>
                      </Space.Compact>
                      <div style={{ marginTop: 6, fontSize: 12, color: '#999' }}>
                        模型搜索、验证和联网搜索默认都使用当前供应商的 API Key，不需要单独配置搜索 Key。
                      </div>
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
                        danger
                        onClick={() => void handleDeleteProvider(provider.provider_name)}
                      >
                        删除
                      </Button>
                    </Space>

                    {feedback && (
                      <Alert
                        style={{ marginTop: 16 }}
                        type={feedback.type}
                        showIcon
                        message={feedback.title}
                        description={
                          <div style={{ display: 'grid', gap: 4 }}>
                            {feedback.detail && <div>{feedback.detail}</div>}
                            <div style={{ fontSize: 12, color: '#666' }}>
                              供应商：{feedback.providerName || provider.display_name}
                              {feedback.model ? ` · 模型：${feedback.model}` : ''}
                              {feedback.baseUrl ? ` · Base URL：${feedback.baseUrl}` : ''}
                            </div>
                          </div>
                        }
                      />
                    )}
                  </div>
                )}
              </Card>
            )
          })}
                </>
              ),
            }]}
          />
        </>
      )}
    </Drawer>
  )
}

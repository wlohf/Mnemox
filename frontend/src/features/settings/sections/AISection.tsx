import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Plus, Search, Trash2, Zap } from 'lucide-react'
import {
  Badge,
  Button,
  Confirm,
  Dialog,
  Field,
  Input,
  Notice,
  Select,
  SwitchField,
  toast,
} from '../../../ui'
import {
  createProvider,
  deleteProvider,
  getAllProviders,
  getRagSettings,
  getRoutingSettings,
  getSearchSettings,
  notifyAIProvidersUpdated,
  reindexAllRagMaterials,
  searchProviderModels,
  setActiveProvider,
  setStoredWebSearchMode,
  testProvider,
  testRagEmbedding,
  testSearchSettings,
  updateProvider,
  updateRagSettings,
  updateRoutingSetting,
  updateSearchSettings,
  type AIProvider,
  type SearchSettings,
  type TestResult,
  type WebSearchMode,
} from '../../../services/aiSettingsApi'
import { getApiErrorMessage } from '../../../services/apiClient'
import { qk } from '../../../app/queryClient'
import { Group, Row, Rows, settingsStyles as s } from '../SettingsDialog'

const WEB_MODES: Array<{ value: WebSearchMode; label: string }> = [
  { value: 'auto', label: '自动（Tavily 优先，失败后兜底）' },
  { value: 'tavily', label: 'Tavily 优先' },
  { value: 'provider_hosted', label: '模型内置联网（Responses）' },
  { value: 'app_search', label: '后端检索后注入' },
  { value: 'grok_summary', label: 'Grok 先搜索总结' },
  { value: 'local_fallback', label: 'DuckDuckGo / Bing' },
]

const splitModels = (v: string) =>
  Array.from(new Set(v.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean)))

function numOrNull(v: string): number | null {
  const n = Number(v)
  return v.trim() && Number.isFinite(n) && n > 0 ? n : null
}

export function AISection() {
  const qc = useQueryClient()
  const providers = useQuery({ queryKey: qk.providers, queryFn: getAllProviders })
  const routing = useQuery({ queryKey: ['ai-settings', 'routing'], queryFn: getRoutingSettings })
  const [openName, setOpenName] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const refresh = async (detail?: Parameters<typeof notifyAIProvidersUpdated>[0]) => {
    await qc.invalidateQueries({ queryKey: qk.providers })
    notifyAIProvidersUpdated(detail)
  }

  const list = providers.data ?? []
  const active = list.find(p => p.is_active)
  const configured = list.filter(p => p.enabled && p.api_key_masked)

  return (
    <>
      {providers.isError && (
        <Notice tone="danger" title="没能读取模型配置">
          {getApiErrorMessage(providers.error, '请确认本地服务已启动')}
        </Notice>
      )}

      <Group title="默认模型供应商" desc="场景没有单独指定时，教练会使用这里的供应商和它的默认模型。">
        <Rows>
          <Row label="默认供应商" hint={configured.length === 0 ? '还没有配置好的供应商。先在下面填入 API Key。' : undefined}>
            <div style={{ width: 240 }}>
              <Select
                ariaLabel="默认供应商"
                value={active?.provider_name}
                placeholder="选择供应商"
                onValueChange={async v => {
                  try {
                    await setActiveProvider(v)
                    await refresh({ resetChatModel: false })
                    toast.success('默认供应商已切换')
                  } catch (e) {
                    toast.error(getApiErrorMessage(e, '切换失败'))
                  }
                }}
                options={list
                  .filter(p => p.enabled || p.is_active)
                  .map(p => ({ value: p.provider_name, label: p.display_name, hint: p.api_key_masked ? p.model : '未配置 Key', disabled: !p.api_key_masked && !p.is_active }))}
              />
            </div>
          </Row>
        </Rows>
      </Group>

      <Group title="供应商" desc="填入 API Key 并验证连接后，就能在对话里选择它的模型。">
        <div className={s.providers}>
          {list.map(p => (
            <ProviderCard
              key={p.provider_name}
              provider={p}
              open={openName === p.provider_name}
              onToggle={() => setOpenName(n => (n === p.provider_name ? null : p.provider_name))}
              onSaved={refresh}
            />
          ))}
          <Button variant="ghost" icon={<Plus />} onClick={() => setAdding(true)} style={{ alignSelf: 'flex-start' }}>
            添加自定义供应商（OpenAI 兼容等）
          </Button>
        </div>
      </Group>

      <Group title="按场景指定模型" desc="比如用便宜的模型做错题检测，用更强的模型做主对话。留空则跟随默认供应商。">
        <Rows>
          <div className={s.routing}>
            {(routing.data ?? []).map(r => {
              const prov = list.find(p => p.provider_name === r.provider_name)
              const models = prov ? Array.from(new Set([prov.model, ...(prov.available_models ?? [])].filter(Boolean))) : []
              return (
                <div key={r.scenario} className={s.routeRow}>
                  <span className={s.routeLabel}>{r.label}</span>
                  <Select
                    size="sm"
                    ariaLabel={`${r.label}使用的供应商`}
                    value={r.provider_name ?? '__active__'}
                    onValueChange={async v => {
                      try {
                        await updateRoutingSetting(r.scenario, v === '__active__' ? null : v, null)
                        await qc.invalidateQueries({ queryKey: ['ai-settings', 'routing'] })
                      } catch (e) {
                        toast.error(getApiErrorMessage(e, '保存失败'))
                      }
                    }}
                    options={[{ value: '__active__', label: '跟随默认供应商' }, ...configured.map(p => ({ value: p.provider_name, label: p.display_name }))]}
                  />
                  <Select
                    size="sm"
                    ariaLabel={`${r.label}使用的模型`}
                    disabled={!r.provider_name}
                    value={r.model ?? '__provider_default__'}
                    onValueChange={async v => {
                      try {
                        await updateRoutingSetting(r.scenario, r.provider_name, v === '__provider_default__' ? null : v)
                        await qc.invalidateQueries({ queryKey: ['ai-settings', 'routing'] })
                      } catch (e) {
                        toast.error(getApiErrorMessage(e, '保存失败'))
                      }
                    }}
                    options={[{ value: '__provider_default__', label: '供应商默认模型' }, ...models.map(m => ({ value: m, label: m }))]}
                  />
                </div>
              )
            })}
          </div>
        </Rows>
      </Group>

      <WebSearchGroup />
      <RagGroup />

      <AddProviderDialog open={adding} onOpenChange={setAdding} onCreated={async p => { await refresh({ providerName: p.provider_name, model: p.model, availableModels: p.available_models }); setOpenName(p.provider_name) }} />
    </>
  )
}

/* ---------------------------------------------------------------------------
   Provider card
--------------------------------------------------------------------------- */
function ProviderCard({
  provider,
  open,
  onToggle,
  onSaved,
}: {
  provider: AIProvider
  open: boolean
  onToggle: () => void
  onSaved: (detail?: Parameters<typeof notifyAIProvidersUpdated>[0]) => Promise<void>
}) {
  const [apiKey, setApiKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [baseUrl, setBaseUrl] = useState(provider.base_url)
  const [model, setModel] = useState(provider.model)
  const [models, setModels] = useState((provider.available_models ?? []).join(', '))
  const [ctxTokens, setCtxTokens] = useState(provider.max_context_tokens ? String(provider.max_context_tokens) : '')
  const [outTokens, setOutTokens] = useState(provider.max_output_tokens ? String(provider.max_output_tokens) : '')
  const [inPrice, setInPrice] = useState(provider.input_price_per_million != null ? String(provider.input_price_per_million) : '')
  const [outPrice, setOutPrice] = useState(provider.output_price_per_million != null ? String(provider.output_price_per_million) : '')
  const [busy, setBusy] = useState<'save' | 'test' | 'search' | 'toggle' | null>(null)
  const [result, setResult] = useState<TestResult | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    setBaseUrl(provider.base_url)
    setModel(provider.model)
    setModels((provider.available_models ?? []).join(', '))
  }, [provider.base_url, provider.model, provider.available_models])

  const keyPayload = () => (clearKey ? { api_key: '' } : apiKey.trim() ? { api_key: apiKey.trim() } : {})

  const save = async () => {
    setBusy('save')
    try {
      const available = splitModels(models)
      const saved = await updateProvider(provider.provider_name, {
        ...keyPayload(),
        base_url: baseUrl.trim(),
        model: model.trim(),
        available_models: available,
        max_context_tokens: numOrNull(ctxTokens),
        max_output_tokens: numOrNull(outTokens),
        input_price_per_million: inPrice.trim() ? Number(inPrice) : null,
        output_price_per_million: outPrice.trim() ? Number(outPrice) : null,
      })
      setApiKey('')
      setClearKey(false)
      await onSaved({ providerName: saved.provider_name, model: saved.model, availableModels: saved.available_models })
      toast.success(`${provider.display_name} 已保存`)
    } catch (e) {
      toast.error(getApiErrorMessage(e, '保存失败'))
    } finally {
      setBusy(null)
    }
  }

  const test = async () => {
    setBusy('test')
    setResult(null)
    try {
      const r = await testProvider(provider.provider_name, { ...keyPayload(), base_url: baseUrl.trim() || undefined, model: model.trim() || undefined })
      setResult(r)
    } catch (e) {
      setResult({ success: false, message: getApiErrorMessage(e, '连接失败') })
    } finally {
      setBusy(null)
    }
  }

  const search = async () => {
    setBusy('search')
    try {
      const r = await searchProviderModels(provider.provider_name, { ...keyPayload(), base_url: baseUrl.trim() || undefined, model_hint: model.trim() || undefined })
      const merged = Array.from(new Set([...splitModels(models), ...r.models]))
      setModels(merged.join(', '))
      toast.success(`找到 ${r.models.length} 个模型`, { description: '保存后才会出现在对话的模型列表里。' })
    } catch (e) {
      toast.error(getApiErrorMessage(e, '搜索模型失败'))
    } finally {
      setBusy(null)
    }
  }

  const toggleEnabled = async (enabled: boolean) => {
    setBusy('toggle')
    try {
      await updateProvider(provider.provider_name, { enabled })
      await onSaved({ resetChatModel: !enabled })
    } catch (e) {
      toast.error(getApiErrorMessage(e, '操作失败'))
    } finally {
      setBusy(null)
    }
  }

  const configured = Boolean(provider.api_key_masked)
  return (
    <div className={s.provider} data-open={open || undefined}>
      <button type="button" className={s.providerHead} onClick={onToggle} aria-expanded={open}>
        <span className={s.providerDot} data-on={(configured && provider.enabled) || undefined} aria-hidden />
        <span className={s.providerName}>
          <strong>{provider.display_name}</strong>
          <span>{configured ? `${provider.model || '未设置默认模型'} · Key ${provider.api_key_masked}` : '未配置 API Key'}</span>
        </span>
        {provider.is_active && <Badge tone="ink">默认</Badge>}
        {configured && !provider.enabled && <Badge>已停用</Badge>}
        <ChevronDown className={s.providerChevron} aria-hidden />
      </button>
      {open && (
        <div className={s.providerBody}>
          <SwitchField label="启用" description="停用后不会出现在对话的模型列表里，已保存的配置保留。" checked={provider.enabled} disabled={busy === 'toggle'} onCheckedChange={v => void toggleEnabled(v)} />
          <Field
            label="API Key"
            htmlFor={`key-${provider.provider_name}`}
            hint={configured ? `已保存：${provider.api_key_masked}。留空表示不修改。` : '只保存在本地数据库，加密存储。'}
            aside={
              configured && (
                <Button size="sm" variant={clearKey ? 'soft' : 'ghost'} icon={<Trash2 />} onClick={() => setClearKey(v => !v)}>
                  {clearKey ? '保存时清除 Key' : '清除 Key'}
                </Button>
              )
            }
          >
            <Input id={`key-${provider.provider_name}`} type="password" autoComplete="off" value={apiKey} disabled={clearKey} placeholder={configured ? '••••••••' : 'sk-…'} onChange={e => setApiKey(e.target.value)} />
          </Field>
          <Field label="Base URL" htmlFor={`url-${provider.provider_name}`}>
            <Input id={`url-${provider.provider_name}`} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} />
          </Field>
          <div className={s.grid2}>
            <Field label="默认模型" htmlFor={`model-${provider.provider_name}`}>
              <Input id={`model-${provider.provider_name}`} value={model} onChange={e => setModel(e.target.value)} />
            </Field>
            <Field label="可选模型" hint="逗号分隔；会出现在对话的模型菜单里" htmlFor={`models-${provider.provider_name}`}>
              <Input
                id={`models-${provider.provider_name}`}
                value={models}
                onChange={e => setModels(e.target.value)}
                suffix={
                  <Button size="sm" variant="ghost" icon={<Search />} loading={busy === 'search'} onClick={() => void search()}>
                    搜索
                  </Button>
                }
              />
            </Field>
          </div>
          <div className={s.grid2}>
            <Field label="上下文上限（tokens）" optional htmlFor={`ctx-${provider.provider_name}`}>
              <Input id={`ctx-${provider.provider_name}`} inputMode="numeric" placeholder="32000" value={ctxTokens} onChange={e => setCtxTokens(e.target.value)} />
            </Field>
            <Field label="输出上限（tokens）" optional htmlFor={`out-${provider.provider_name}`}>
              <Input id={`out-${provider.provider_name}`} inputMode="numeric" placeholder="4096" value={outTokens} onChange={e => setOutTokens(e.target.value)} />
            </Field>
            <Field label="输入价格（美元 / 百万 tokens）" optional htmlFor={`inp-${provider.provider_name}`}>
              <Input id={`inp-${provider.provider_name}`} inputMode="decimal" value={inPrice} onChange={e => setInPrice(e.target.value)} />
            </Field>
            <Field label="输出价格（美元 / 百万 tokens）" optional htmlFor={`outp-${provider.provider_name}`}>
              <Input id={`outp-${provider.provider_name}`} inputMode="decimal" value={outPrice} onChange={e => setOutPrice(e.target.value)} />
            </Field>
          </div>
          {result && (
            <Notice tone={result.success ? 'success' : 'danger'} title={result.success ? '连接正常' : '连接失败'} className={s.testResult} role="status">
              {result.message}
              {result.model ? ` · 模型 ${result.model}` : ''}
            </Notice>
          )}
          <div className={s.actions}>
            <Button variant="primary" loading={busy === 'save'} onClick={() => void save()}>
              保存
            </Button>
            <Button icon={<Zap />} loading={busy === 'test'} onClick={() => void test()}>
              验证连接
            </Button>
            <span style={{ flex: 1 }} />
            <Button variant="danger" icon={<Trash2 />} onClick={() => setDeleting(true)}>
              删除供应商
            </Button>
          </div>
        </div>
      )}
      <Confirm
        open={deleting}
        onOpenChange={setDeleting}
        tone="danger"
        title={`删除 ${provider.display_name}？`}
        description="保存的 Key 和模型列表会被删除，使用它的场景会改为跟随默认供应商。"
        confirmLabel="删除"
        onConfirm={async () => {
          try {
            await deleteProvider(provider.provider_name)
            await onSaved({ resetChatModel: true })
            toast.success('已删除')
          } catch (e) {
            toast.error(getApiErrorMessage(e, '删除失败'))
            throw e
          }
        }}
      />
    </div>
  )
}

/* ---------------------------------------------------------------------------
   Add provider
--------------------------------------------------------------------------- */
function AddProviderDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (v: boolean) => void; onCreated: (p: AIProvider) => void | Promise<void> }) {
  const [form, setForm] = useState({ display_name: '', provider_type: 'openai', provider_name: '', api_key: '', base_url: '', model: '', models: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const placeholder = form.provider_type === 'anthropic' ? 'https://api.anthropic.com' : form.provider_type === 'gemini' ? 'https://generativelanguage.googleapis.com' : 'https://api.example.com/v1'
  const submit = async () => {
    if (!form.display_name.trim()) {
      setError('请输入供应商显示名称')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const p = await createProvider({
        display_name: form.display_name.trim(),
        provider_type: form.provider_type,
        provider_name: form.provider_name.trim() || undefined,
        api_key: form.api_key.trim() || undefined,
        base_url: form.base_url.trim() || undefined,
        model: form.model.trim() || undefined,
        available_models: splitModels(form.models),
      })
      toast.success(`已添加 ${p.display_name}`)
      onOpenChange(false)
      setForm({ display_name: '', provider_type: 'openai', provider_name: '', api_key: '', base_url: '', model: '', models: '' })
      await onCreated(p)
    } catch (e) {
      setError(getApiErrorMessage(e, '添加失败'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      width={34}
      title="添加自定义供应商"
      description="适用于 OpenAI 兼容的中转服务、自建网关，或其他 Anthropic / Gemini 协议的服务。"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            添加
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.grid2}>
          <Field label="显示名称" htmlFor="np-name" error={error && !form.display_name.trim() ? error : undefined}>
            <Input id="np-name" autoFocus value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} placeholder="例如：我的中转" />
          </Field>
          <Field label="协议">
            <Select
              ariaLabel="协议"
              value={form.provider_type}
              onValueChange={v => setForm({ ...form, provider_type: v })}
              options={[
                { value: 'openai', label: 'OpenAI 兼容' },
                { value: 'anthropic', label: 'Anthropic' },
                { value: 'gemini', label: 'Gemini' },
              ]}
            />
          </Field>
        </div>
        <Field label="API Key" htmlFor="np-key" optional>
          <Input id="np-key" type="password" autoComplete="off" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} />
        </Field>
        <Field label="Base URL" htmlFor="np-url" optional>
          <Input id="np-url" value={form.base_url} placeholder={placeholder} onChange={e => setForm({ ...form, base_url: e.target.value })} />
        </Field>
        <div className={s.grid2}>
          <Field label="默认模型" htmlFor="np-model" optional>
            <Input id="np-model" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} />
          </Field>
          <Field label="标识" htmlFor="np-id" optional hint="不填会自动生成">
            <Input id="np-id" value={form.provider_name} onChange={e => setForm({ ...form, provider_name: e.target.value })} />
          </Field>
        </div>
        <Field label="可选模型" htmlFor="np-models" optional hint="逗号分隔">
          <Input id="np-models" value={form.models} onChange={e => setForm({ ...form, models: e.target.value })} />
        </Field>
        {error && form.display_name.trim() && <Notice tone="danger">{error}</Notice>}
      </div>
    </Dialog>
  )
}

/* ---------------------------------------------------------------------------
   Web search
--------------------------------------------------------------------------- */
function WebSearchGroup() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['ai-settings', 'search'], queryFn: getSearchSettings })
  const [draft, setDraft] = useState<Partial<SearchSettings> & { tavily_api_key?: string }>({})
  const [busy, setBusy] = useState<'save' | 'test' | null>(null)
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const cur = useMemo(() => ({ ...(q.data ?? {}), ...draft }) as SearchSettings & { tavily_api_key?: string }, [q.data, draft])
  if (!q.data) return null
  const set = (p: Partial<SearchSettings> & { tavily_api_key?: string }) => setDraft(d => ({ ...d, ...p }))
  const save = async () => {
    setBusy('save')
    try {
      const { tavily_api_key, ...rest } = draft
      await updateSearchSettings({ ...rest, ...(tavily_api_key?.trim() ? { tavily_api_key: tavily_api_key.trim() } : {}) })
      if (draft.default_mode) setStoredWebSearchMode(draft.default_mode)
      setDraft({})
      await qc.invalidateQueries({ queryKey: ['ai-settings', 'search'] })
      toast.success('联网搜索设置已保存')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '保存失败'))
    } finally {
      setBusy(null)
    }
  }
  const test = async () => {
    setBusy('test')
    try {
      const r = await testSearchSettings({ tavily_api_key: draft.tavily_api_key?.trim() || undefined })
      setTestMsg({ ok: r.success, text: `${r.message}（${r.provider} · ${r.result_count} 条结果）` })
    } catch (e) {
      setTestMsg({ ok: false, text: getApiErrorMessage(e, '测试失败') })
    } finally {
      setBusy(null)
    }
  }
  return (
    <Group title="联网搜索" desc="需要最新信息时，教练会先检索网页再回答，并在回答下方列出来源。">
      <Rows>
        <div className={s.row}>
          <div className={s.rowText} style={{ flex: 1 }}>
            <SwitchField label="允许联网搜索" description="关闭后，对话中的「联网」开关不会生效。" checked={cur.enabled} onCheckedChange={v => set({ enabled: v })} />
          </div>
        </div>
        <Row label="默认方式">
          <div style={{ width: 280 }}>
            <Select ariaLabel="默认联网方式" value={cur.default_mode} onValueChange={v => set({ default_mode: v as WebSearchMode })} options={WEB_MODES} />
          </div>
        </Row>
        <div className={s.row}>
          <div className={s.stack} style={{ flex: 1 }}>
            <Field label="Tavily API Key" htmlFor="tavily-key" optional hint={cur.tavily_api_key_masked ? `已保存：${cur.tavily_api_key_masked}。留空表示不修改。` : '没有 Key 时会自动使用 DuckDuckGo / Bing。'}>
              <Input id="tavily-key" type="password" autoComplete="off" value={draft.tavily_api_key ?? ''} onChange={e => set({ tavily_api_key: e.target.value })} />
            </Field>
            <div className={s.grid2}>
              <Field label="搜索深度">
                <Select ariaLabel="搜索深度" value={cur.tavily_search_depth} onValueChange={v => set({ tavily_search_depth: v as 'basic' | 'advanced' })} options={[{ value: 'basic', label: '标准' }, { value: 'advanced', label: '深入' }]} />
              </Field>
              <Field label="结果数量" htmlFor="tavily-n">
                <Input id="tavily-n" type="number" min={1} max={10} value={cur.tavily_max_results} onChange={e => set({ tavily_max_results: Math.max(1, Math.min(10, Number(e.target.value) || 1)) })} />
              </Field>
            </div>
            <SwitchField label="失败时使用兜底搜索" checked={cur.fallback_enabled} onCheckedChange={v => set({ fallback_enabled: v })} />
          </div>
        </div>
      </Rows>
      {testMsg && (
        <Notice tone={testMsg.ok ? 'success' : 'danger'} className={s.testResult} role="status">
          {testMsg.text}
        </Notice>
      )}
      <div className={s.actions} style={{ marginTop: 12 }}>
        <Button variant="primary" loading={busy === 'save'} disabled={Object.keys(draft).length === 0} onClick={() => void save()}>
          保存联网设置
        </Button>
        <Button loading={busy === 'test'} onClick={() => void test()}>
          测试搜索
        </Button>
      </div>
    </Group>
  )
}

/* ---------------------------------------------------------------------------
   RAG embedding
--------------------------------------------------------------------------- */
function RagGroup() {
  const q = useQuery({ queryKey: ['rag', 'settings'], queryFn: getRagSettings, retry: false })
  const qc = useQueryClient()
  const [key, setKey] = useState('')
  const [url, setUrl] = useState('')
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState<'save' | 'test' | 'reindex' | null>(null)
  useEffect(() => {
    if (!q.data) return
    setUrl(q.data.base_url)
    setModel(q.data.model)
  }, [q.data])
  if (q.isError || !q.data) return null
  const d = q.data
  const summary = d.projection_summary
  const run = async (kind: 'save' | 'test' | 'reindex') => {
    setBusy(kind)
    try {
      if (kind === 'save') {
        const r = await updateRagSettings({ ...(key.trim() ? { api_key: key.trim() } : {}), base_url: url.trim(), model: model.trim() })
        setKey('')
        toast.success(r.message || '检索设置已保存', r.requires_reindex ? { description: '嵌入模型变了，建议重建索引。' } : undefined)
      } else if (kind === 'test') {
        const r = await testRagEmbedding()
        ;(r.success ? toast.success : toast.error)(r.message)
      } else {
        const r = await reindexAllRagMaterials()
        toast.success(r.message || `已重建 ${r.materials_indexed} 份资料的索引`)
      }
      await qc.invalidateQueries({ queryKey: ['rag', 'settings'] })
    } catch (e) {
      toast.error(getApiErrorMessage(e, '操作失败'))
    } finally {
      setBusy(null)
    }
  }
  return (
    <Group title="资料检索（Embedding）" desc="用于语义检索你上传的资料。没有配置或服务不可用时，会自动退回关键词检索，不影响使用。">
      <Rows>
        <Row
          label={d.fallback_active ? '当前使用关键词检索' : d.embedding_enabled ? '语义检索已启用' : '未启用语义检索'}
          hint={summary ? `已索引 ${summary.ready}/${summary.total} 份资料 · ${d.total_chunks} 个片段${summary.failed ? ` · ${summary.failed} 份失败` : ''}` : `${d.total_chunks} 个片段`}
        >
          <Badge tone={d.fallback_active ? 'warning' : d.embedding_enabled ? 'success' : 'neutral'}>{d.fallback_active ? '关键词回退' : d.embedding_enabled ? '正常' : '未配置'}</Badge>
        </Row>
        <div className={s.row}>
          <div className={s.stack} style={{ flex: 1 }}>
            <Field label="Embedding API Key" htmlFor="rag-key" optional hint={d.api_key_masked ? `已保存：${d.api_key_masked}` : undefined}>
              <Input id="rag-key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} />
            </Field>
            <div className={s.grid2}>
              <Field label="Base URL" htmlFor="rag-url">
                <Input id="rag-url" value={url} onChange={e => setUrl(e.target.value)} />
              </Field>
              <Field label="模型" htmlFor="rag-model">
                <Input id="rag-model" value={model} onChange={e => setModel(e.target.value)} />
              </Field>
            </div>
          </div>
        </div>
      </Rows>
      <div className={s.actions} style={{ marginTop: 12 }}>
        <Button variant="primary" loading={busy === 'save'} onClick={() => void run('save')}>
          保存
        </Button>
        <Button loading={busy === 'test'} onClick={() => void run('test')}>
          测试连接
        </Button>
        <Button variant="ghost" loading={busy === 'reindex'} onClick={() => void run('reindex')}>
          重建全部索引
        </Button>
      </div>
    </Group>
  )
}

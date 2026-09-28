import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUp, AtSign, Check, ChevronDown, Cpu, Globe, ImagePlus, Square, X } from 'lucide-react'
import { IconButton, Popover, PopoverClose, toast } from '../../ui'
import { getAllProviders, AI_PROVIDERS_UPDATED_EVENT } from '../../services/aiSettingsApi'
import { getProviderModels, getSelectableChatProviders } from '../../components/Layout/chatModelOptions'
import { qk } from '../../app/queryClient'
import { useShell } from '../../app/shell/shellStore'
import s from './coach.module.css'

const MODEL_KEY = 'chat_model_override'
const WEB_KEY = 'mx_chat_web_search'
const MAX_IMAGE_BYTES = 5 * 1024 * 1024

export interface ComposerSubmit {
  text: string
  images: string[]
  providerName?: string
  model?: string
  webSearch: boolean
}

export interface ComposerHandle {
  fill: (text: string) => void
  focus: () => void
}

export const Composer = forwardRef<
  ComposerHandle,
  {
    busy: boolean
    streaming: boolean
    onSubmit: (v: ComposerSubmit) => Promise<boolean> | boolean
    onStop: () => void
    context?: { label: string; onRemove: () => void } | null
    placeholder?: string
  }
>(function Composer({ busy, streaming, onSubmit, onStop, context, placeholder }, ref) {
  const [text, setText] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [model, setModel] = useState(() => localStorage.getItem(MODEL_KEY) || '__route__')
  const [web, setWeb] = useState(() => localStorage.getItem(WEB_KEY) !== 'false')
  const areaRef = useRef<HTMLTextAreaElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const openSettings = useShell(st => st.openSettings)
  const providers = useQuery({ queryKey: qk.providers, queryFn: getAllProviders, staleTime: 60_000 })

  useImperativeHandle(ref, () => ({
    fill: v => {
      setText(v)
      requestAnimationFrame(() => {
        areaRef.current?.focus()
        areaRef.current?.setSelectionRange(v.length, v.length)
      })
    },
    focus: () => areaRef.current?.focus(),
  }))

  // Keep in sync with the AI settings drawer.
  useEffect(() => {
    const onUpdate = () => void providers.refetch()
    window.addEventListener(AI_PROVIDERS_UPDATED_EVENT, onUpdate)
    return () => window.removeEventListener(AI_PROVIDERS_UPDATED_EVENT, onUpdate)
  }, [providers])

  const groups = useMemo(
    () =>
      getSelectableChatProviders(providers.data ?? [])
        .map(p => ({ name: p.provider_name, label: p.display_name, models: getProviderModels(p) }))
        .filter(g => g.models.length > 0),
    [providers.data],
  )
  const values = useMemo(() => new Set(['__route__', ...groups.flatMap(g => g.models.map(m => `${g.name}::${m}`))]), [groups])

  useEffect(() => {
    if (providers.data && !values.has(model)) setModel('__route__')
  }, [model, providers.data, values])
  useEffect(() => localStorage.setItem(MODEL_KEY, model), [model])
  useEffect(() => localStorage.setItem(WEB_KEY, String(web)), [web])

  // Auto-grow
  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`
  }, [text])

  const [providerName, modelName] = model === '__route__' ? [undefined, undefined] : model.split('::')
  const modelLabel = model === '__route__' ? '自动选择模型' : modelName

  const addFiles = (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      if (!file.type.startsWith('image/')) continue
      if (file.size > MAX_IMAGE_BYTES) {
        toast.warning('图片不能超过 5MB', { description: file.name })
        continue
      }
      const reader = new FileReader()
      reader.onload = () => {
        const base64 = String(reader.result).split(',')[1]
        if (base64) setImages(prev => [...prev, base64].slice(0, 6))
      }
      reader.readAsDataURL(file)
    }
  }

  const submit = async () => {
    const value = text.trim()
    if (!value || busy) return
    const ok = await onSubmit({ text: value, images, providerName, model: modelName, webSearch: web })
    if (ok) {
      setText('')
      setImages([])
    }
  }

  return (
    <div className={s.dock}>
      <div
        className={s.composer}
        data-dragging={dragging || undefined}
        onDragOver={e => {
          if (Array.from(e.dataTransfer.items).some(i => i.type.startsWith('image/'))) {
            e.preventDefault()
            setDragging(true)
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault()
          setDragging(false)
          addFiles(e.dataTransfer.files)
        }}
      >
        {(context || images.length > 0) && (
          <div className={s.ctxRow}>
            {context && (
              <span className={s.ctxChip}>
                <AtSign aria-hidden />
                <span>{context.label}</span>
                <button type="button" aria-label="移除上下文" onClick={context.onRemove}>
                  <X />
                </button>
              </span>
            )}
            {images.map((img, i) => (
              <span key={i} className={s.thumb}>
                <img src={`data:image/png;base64,${img}`} alt={`待发送图片 ${i + 1}`} />
                <button type="button" aria-label="移除图片" onClick={() => setImages(prev => prev.filter((_, j) => j !== i))}>
                  <X />
                </button>
              </span>
            ))}
          </div>
        )}
        <textarea
          ref={areaRef}
          id="mnemox-chat-input"
          className={s.textarea}
          rows={1}
          value={text}
          aria-label="问教练"
          placeholder={placeholder ?? '问教练，或让它帮你记笔记、排计划…'}
          onChange={e => setText(e.target.value)}
          onPaste={e => {
            const files = Array.from(e.clipboardData.files).filter(f => f.type.startsWith('image/'))
            if (files.length) {
              e.preventDefault()
              addFiles(files)
            }
          }}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void submit()
            }
          }}
        />
        <div className={s.bar}>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={e => {
              if (e.target.files) addFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <IconButton label="添加图片" size="sm" onClick={() => fileRef.current?.click()}>
            <ImagePlus />
          </IconButton>
          <button type="button" className={s.pill} aria-pressed={web} onClick={() => setWeb(v => !v)} title="需要最新信息时联网检索">
            <Globe aria-hidden />
            <span>{web ? '联网' : '不联网'}</span>
          </button>
          <span className={s.barSpacer} />
          <Popover
            align="end"
            side="top"
            width={260}
            trigger={
              <button type="button" className={s.pill} aria-label={`聊天模型：${modelLabel}`}>
                <Cpu aria-hidden />
                <span>{modelLabel}</span>
                <ChevronDown aria-hidden />
              </button>
            }
          >
            <div className={s.modelList} role="radiogroup" aria-label="聊天模型">
              <PopoverClose asChild>
                <button type="button" role="radio" aria-checked={model === '__route__'} className={s.modelItem} onClick={() => setModel('__route__')}>
                  自动选择（按场景路由）
                  {model === '__route__' && <Check aria-hidden />}
                </button>
              </PopoverClose>
              {groups.map(g => (
                <div key={g.name}>
                  <div className={s.modelGroup}>{g.label}</div>
                  {g.models.map(m => {
                    const v = `${g.name}::${m}`
                    return (
                      <PopoverClose asChild key={v}>
                        <button type="button" role="radio" aria-checked={model === v} className={s.modelItem} onClick={() => setModel(v)}>
                          {m}
                          {model === v && <Check aria-hidden />}
                        </button>
                      </PopoverClose>
                    )
                  })}
                </div>
              ))}
              {groups.length === 0 && (
                <p className={s.modelEmpty}>
                  还没有可用的模型。
                  <PopoverClose asChild>
                    <button type="button" className={s.modelItem} style={{ padding: 0, minHeight: 0, color: 'var(--mx-ink-text)' }} onClick={() => openSettings('ai')}>
                      去配置 AI 模型
                    </button>
                  </PopoverClose>
                </p>
              )}
            </div>
          </Popover>
          {streaming ? (
            <button type="button" className={s.send} data-stop onClick={onStop} aria-label="停止生成">
              <Square />
            </button>
          ) : (
            <button type="button" className={s.send} disabled={!text.trim() || busy} onClick={() => void submit()} aria-label="发送">
              <ArrowUp />
            </button>
          )}
        </div>
      </div>
      <div className={s.foot}>回答会标注参考来源；记笔记、排计划这类写入，都会先生成草案等你确认。</div>
    </div>
  )
})

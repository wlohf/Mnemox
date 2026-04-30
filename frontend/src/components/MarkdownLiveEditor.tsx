import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import ToastUIEditor from '@toast-ui/editor'
import '@toast-ui/editor/dist/toastui-editor.css'
import './MarkdownLiveEditor.css'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

type ImageHookCallback = (url: string, text?: string) => void

type ToastEditorInstance = {
  on: (type: string, handler: (...args: any[]) => void) => void
  exec: (name: string, payload?: Record<string, any>) => void
  destroy: () => void
  getMarkdown: () => string
  getSelection: () => [number, number]
  getSelectedText: (start?: number, end?: number) => string
  getRangeInfoOfNode: (pos?: number) => { range: [number, number] | any; type: string }
  setMarkdown: (markdown: string) => void
  setPlaceholder: (placeholder: string) => void
  setHeight: (height: string) => void
  setMinHeight: (height: string) => void
  focus: () => void
  insertText: (text: string) => void
  setSelection: (start: number, end?: number) => void
  replaceSelection: (text: string, start?: number, end?: number) => void
  addHook: (type: string, handler: (blob: Blob | File, callback: ImageHookCallback) => void) => void
  removeHook: (type: string) => void
}

export interface MarkdownLiveEditorImageResult {
  url?: string
  markdown?: string
  alt?: string
}

export interface MarkdownLiveEditorProps {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  height?: string
  className?: string
  onUploadImage?: (file: File) => Promise<MarkdownLiveEditorImageResult | null>
}

export interface MarkdownLiveEditorHandle {
  focus: () => void
  insertText: (text: string) => void
  setMarkdown: (text: string) => void
  getMarkdown: () => string
}

export const MarkdownLiveEditor = forwardRef<MarkdownLiveEditorHandle, MarkdownLiveEditorProps>(
  function MarkdownLiveEditor(
    {
      value,
      onChange,
      placeholder = '输入 Markdown 内容...',
      height = '420px',
      className,
      onUploadImage,
    },
    ref,
  ) {
    const mountRef = useRef<HTMLDivElement | null>(null)
    const editorRef = useRef<ToastEditorInstance | null>(null)
    const syncingRef = useRef(false)
    const onChangeRef = useRef(onChange)
    const onUploadImageRef = useRef(onUploadImage)

    useEffect(() => {
      onChangeRef.current = onChange
    }, [onChange])

    useEffect(() => {
      onUploadImageRef.current = onUploadImage
    }, [onUploadImage])

    useEffect(() => {
      if (!mountRef.current || editorRef.current) return

      const options = {
        el: mountRef.current,
        height,
        minHeight: height,
        initialValue: value || '',
        initialEditType: 'wysiwyg',
        hideModeSwitch: true,
        previewStyle: 'vertical',
        placeholder,
        usageStatistics: false,
        toolbarItems: [
          ['heading', 'bold', 'italic', 'strike'],
          ['hr', 'quote'],
          ['ul', 'ol', 'task'],
          ['table', 'image', 'link'],
          ['code', 'codeblock'],
        ],
      }

      const editor = new ToastUIEditor(options as any) as ToastEditorInstance
      const tryConvertTaskShortcut = () => {
        const [from, to] = editor.getSelection()
        if (from !== to) return false

        const nodeInfo = editor.getRangeInfoOfNode(from)
        const range = nodeInfo?.range
        if (!nodeInfo || !Array.isArray(range) || range.length !== 2) return false

        const [lineStart, lineEnd] = range as [number, number]
        const lineText = editor.getSelectedText(lineStart, lineEnd)
        const matched = lineText.match(/^\s*[-*+]\s\[[ xX]\]\s*(.*)$/)
        if (!matched) return false

        const taskText = matched[1] || ''
        editor.replaceSelection(taskText, lineStart, lineEnd)
        editor.setSelection(lineStart)
        editor.exec('taskList')
        return true
      }

      editor.on('change', () => {
        if (syncingRef.current) return
        if (tryConvertTaskShortcut()) return
        onChangeRef.current(editor.getMarkdown())
      })
      editor.on('keyup', (_editorType: string, ev: KeyboardEvent) => {
        if (![']', ' ', 'Enter'].includes(ev.key)) return
        window.setTimeout(() => {
          tryConvertTaskShortcut()
        }, 0)
      })

      editorRef.current = editor
      return () => {
        editor.destroy()
        editorRef.current = null
      }
    }, [])

    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return

      editor.removeHook('addImageBlobHook')
      editor.addHook('addImageBlobHook', (blob: Blob | File, callback: ImageHookCallback) => {
        const source = blob instanceof File
          ? blob
          : new File([blob], `image-${Date.now()}.png`, { type: blob.type || 'image/png' })

        if (!onUploadImageRef.current) {
          const reader = new FileReader()
          reader.onload = () => {
            if (typeof reader.result === 'string') {
              callback(reader.result, source.name || 'image')
            }
          }
          reader.readAsDataURL(source)
          return
        }

        void (async () => {
          try {
            const result = await onUploadImageRef.current?.(source)
            if (!result) return
            if (result.url) {
              callback(result.url, result.alt || source.name || 'image')
              return
            }
            if (result.markdown && editorRef.current) {
              const text = result.markdown.endsWith('\n') ? result.markdown : `${result.markdown}\n`
              editorRef.current.insertText(text)
            }
          } catch {
            // Parent is responsible for reporting upload errors.
          }
        })()
      })
    }, [onUploadImage])

    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return
      if (editor.getMarkdown() === value) return
      syncingRef.current = true
      editor.setMarkdown(value || '')
      syncingRef.current = false
    }, [value])

    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return
      editor.setPlaceholder(placeholder)
    }, [placeholder])

    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return
      editor.setHeight(height)
      editor.setMinHeight(height)
    }, [height])

    useImperativeHandle(
      ref,
      () => ({
        focus: () => {
          editorRef.current?.focus()
        },
        insertText: (text: string) => {
          editorRef.current?.insertText(text)
        },
        setMarkdown: (text: string) => {
          editorRef.current?.setMarkdown(text || '')
        },
        getMarkdown: () => editorRef.current?.getMarkdown() || '',
      }),
      [],
    )

    return <div className={`markdown-live-editor ${className || ''}`} ref={mountRef} />
  },
)

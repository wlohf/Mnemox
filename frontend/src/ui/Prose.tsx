import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { cx } from './controls'
import s from './prose.module.css'

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const text = extractText(children)
  return (
    <pre>
      <button
        type="button"
        className={s.codeCopy}
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1400)
          })
        }}
      >
        {copied ? '已复制' : '复制'}
      </button>
      {children}
    </pre>
  )
}

function extractText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    return extractText((node as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

/**
 * Safe markdown renderer (raw HTML skipped) with GFM, math and code
 * highlighting. Links always open outside the app.
 */
export const Prose = memo(function Prose({
  children,
  streaming,
  className,
}: {
  children: string
  streaming?: boolean
  className?: string
}) {
  return (
    <div className={cx(s.prose, className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        skipHtml
        components={{
          a: props => <a {...props} target="_blank" rel="noreferrer noopener" />,
          pre: props => <CodeBlock>{props.children}</CodeBlock>,
        }}
      >
        {children}
      </ReactMarkdown>
      {streaming && <span className={s.caret} aria-hidden />}
    </div>
  )
})

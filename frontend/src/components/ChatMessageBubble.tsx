import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'
import './ChatMessageBubble.css'

interface ChatMessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  imageData?: string[]
  isStreaming?: boolean
  onQuoteToNote?: (content: string) => void
}

export function ChatMessageBubble({ role, content, imageData, isStreaming, onQuoteToNote }: ChatMessageBubbleProps) {
  const isUser = role === 'user'
  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 20,
        alignItems: 'flex-start',
      }}
    >
      {/* Assistant avatar on the left */}
      {!isUser && (
        <div className="msg-avatar msg-avatar-assistant">
          AI
        </div>
      )}

      <div className={isUser ? 'msg-bubble-user' : 'msg-bubble-assistant'}>
        {/* User message images */}
        {isUser && imageData && imageData.length > 0 && (
          <div style={{ marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {imageData.map((img, i) => (
              <img
                key={i}
                src={img.startsWith('data:') ? img : `data:image/png;base64,${img}`}
                alt={`image-${i}`}
                style={{
                  maxWidth: 200,
                  maxHeight: 200,
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid rgba(255,255,255,0.2)',
                }}
              />
            ))}
          </div>
        )}

        {isUser ? (
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: 14.5 }}>{content}</div>
        ) : (
          <div className="chat-markdown">
            {!isStreaming && onQuoteToNote && (
              <div style={{ marginBottom: 10, textAlign: 'right' }}>
                <button
                  type="button"
                  className="quote-note-btn"
                  onClick={() => onQuoteToNote(content)}
                >
                  📝 引用到笔记
                </button>
              </div>
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeHighlight, rehypeKatex]}
              components={{
                code(props) {
                  const { children, className } = props
                  const text = String(children || '')
                  const isInline = !className
                  if (isInline) {
                    return <code className={className}>{children}</code>
                  }
                  return (
                    <div style={{ position: 'relative' }}>
                      <button
                        type="button"
                        className="code-copy-btn"
                        onClick={() => navigator.clipboard?.writeText(text)}
                      >
                        复制
                      </button>
                      <code className={className}>{children}</code>
                    </div>
                  )
                },
              }}
            >
              {content}
            </ReactMarkdown>
            {isStreaming && (
              <span className="streaming-cursor" />
            )}
          </div>
        )}
      </div>

      {/* User avatar on the right */}
      {isUser && (
        <div className="msg-avatar msg-avatar-user">
          我
        </div>
      )}
    </div>
  )
}

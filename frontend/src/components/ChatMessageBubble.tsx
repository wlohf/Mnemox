import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'
import { Tooltip } from 'antd'
import { CopyOutlined, FormOutlined, SyncOutlined, DislikeOutlined } from '@ant-design/icons'
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

  const handleCopy = () => {
    navigator.clipboard?.writeText(content)
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 24,
        alignItems: 'flex-start',
        width: '100%',
      }}
    >
      {/* Assistant avatar on the left */}
      {!isUser && (
        <div style={{ 
          width: 30, height: 30, borderRadius: '50%', flexShrink: 0,
          background: 'linear-gradient(135deg, var(--brand-500), var(--brand-400))',
          display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 16, fontWeight: 'bold'
        }}>
          S
        </div>
      )}

      <div className={isUser ? 'msg-bubble-user' : 'msg-bubble-assistant'} style={{ width: isUser ? 'auto' : '100%' }}>
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
                  borderRadius: '12px',
                  border: '1px solid var(--border-light)',
                }}
              />
            ))}
          </div>
        )}

        {isUser ? (
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: 15 }}>{content}</div>
        ) : (
          <>
            <div className="chat-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeHighlight, rehypeKatex]}
                skipHtml
                components={{
                  a(props) {
                    return <a {...props} target="_blank" rel="noreferrer noopener" />
                  },
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
            
            {/* Action Toolbar */}
            {!isStreaming && (
              <div className="chat-action-toolbar">
                <Tooltip title="复制内容" placement="bottom">
                  <button className="chat-action-btn" onClick={handleCopy}><CopyOutlined /></button>
                </Tooltip>
                {onQuoteToNote && (
                  <Tooltip title="引用到笔记" placement="bottom">
                    <button className="chat-action-btn" onClick={() => onQuoteToNote(content)}><FormOutlined /></button>
                  </Tooltip>
                )}
                <Tooltip title="重新生成" placement="bottom">
                  <button className="chat-action-btn"><SyncOutlined /></button>
                </Tooltip>
                <Tooltip title="踩" placement="bottom">
                  <button className="chat-action-btn"><DislikeOutlined /></button>
                </Tooltip>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

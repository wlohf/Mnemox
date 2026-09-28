import type { MaterialItem } from '../../services/materialApi'
import type { RetrievalProjectionStatus } from '../../services/aiSettingsApi'

/*
 * View model for the materials library: file kinds, retrieval readiness,
 * outline extraction from the stored text, and upload validation that
 * mirrors the backend's rules so the learner hears "why" before uploading.
 */

export const ACCEPTED_EXT = ['.pdf', '.docx', '.md', '.txt'] as const
export const ACCEPT_ATTR = ACCEPTED_EXT.join(',')
export const MAX_UPLOAD_MB = 200

export type FileKind = 'pdf' | 'docx' | 'md' | 'txt' | 'other'

export const KIND_META: Record<FileKind, { label: string; short: string }> = {
  pdf: { label: 'PDF 文档', short: 'PDF' },
  docx: { label: 'Word 文档', short: 'DOCX' },
  md: { label: 'Markdown', short: 'MD' },
  txt: { label: '纯文本', short: 'TXT' },
  other: { label: '其他', short: 'FILE' },
}

export function kindOf(m: Pick<MaterialItem, 'file_type' | 'title'>): FileKind {
  const raw = (m.file_type || m.title.split('.').pop() || '').toLowerCase().replace(/^\./, '')
  if (raw === 'pdf' || raw === 'docx' || raw === 'md' || raw === 'txt') return raw
  if (raw === 'markdown') return 'md'
  return 'other'
}

/** Title without the file extension the upload used as its name. */
export function displayTitle(title: string): string {
  return title.replace(/\.(pdf|docx|md|markdown|txt)$/i, '')
}

export interface Readiness {
  key: 'ready' | 'keyword' | 'indexing' | 'failed' | 'extract_failed' | 'none'
  label: string
  detail: string
  tone: 'success' | 'neutral' | 'ink' | 'warning' | 'danger'
  canRetry: boolean
}

/**
 * How well the coach can use this material. Extraction failure comes first:
 * without text nothing downstream can work, and retrying the index won't help.
 */
export function readinessOf(
  m: Pick<MaterialItem, 'content_status' | 'retrieval_projection'>,
  semanticAvailable = true,
): Readiness {
  if (m.content_status === 'failed') {
    return {
      key: 'extract_failed',
      label: '没能读出文字',
      detail: '这份文件里没有可提取的文字，可能是扫描件或图片。换一份可复制文字的版本再上传。',
      tone: 'danger',
      canRetry: false,
    }
  }
  const p: RetrievalProjectionStatus | null | undefined = m.retrieval_projection
  if (!p) {
    return { key: 'none', label: '可用于对话', detail: '教练会在对话里按标题和内容引用这份资料。', tone: 'neutral', canRetry: false }
  }
  switch (p.status) {
    case 'ready':
      return {
        key: 'ready',
        label: '已建立语义索引',
        detail: `${p.vector_chunk_count || p.chunk_count} 个片段可按意思检索，教练能引用到具体段落。`,
        tone: 'success',
        canRetry: false,
      }
    case 'indexing':
    case 'pending':
      return { key: 'indexing', label: '正在建立索引', detail: '稍等片刻。索引完成前，教练先用关键词检索这份资料。', tone: 'ink', canRetry: false }
    case 'failed':
      return {
        key: 'failed',
        label: '索引失败',
        detail: p.last_error ? `原因：${p.last_error}` : '语义索引没有建好，现在只能按关键词检索。可以重试。',
        tone: 'warning',
        canRetry: true,
      }
    case 'degraded':
      return {
        key: 'keyword',
        label: '关键词检索',
        detail: semanticAvailable
          ? `已保存 ${p.chunk_count} 个文本片段，暂时按关键词检索。可以重试建立语义索引。`
          : `已保存 ${p.chunk_count} 个文本片段，按关键词检索。在设置里配置向量模型后，可以按意思检索。`,
        tone: 'neutral',
        canRetry: semanticAvailable,
      }
    default:
      return { key: 'keyword', label: '关键词检索', detail: '这份资料按关键词检索。', tone: 'neutral', canRetry: false }
  }
}

/* ---------------- Outline ---------------- */

export interface OutlineEntry {
  level: number
  text: string
  line: number
}

/** Markdown-style headings (and "第X章" lines) as a reading outline. */
export function outlineOf(content: string | null | undefined, max = 60): OutlineEntry[] {
  if (!content) return []
  const out: OutlineEntry[] = []
  const lines = content.split(/\r?\n/)
  let inFence = false
  for (let i = 0; i < lines.length && out.length < max; i++) {
    const raw = lines[i]
    if (/^\s*```/.test(raw)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    const md = /^(#{1,4})\s+(.+?)\s*#*\s*$/.exec(raw)
    if (md) {
      out.push({ level: md[1].length, text: md[2].trim(), line: i })
      continue
    }
    const chapter = /^\s*(第[一二三四五六七八九十百零\d]+[章节篇部分])\s*[:：、.\s]?\s*(.{0,40})$/.exec(raw)
    if (chapter) out.push({ level: 2, text: `${chapter[1]}${chapter[2] ? ` ${chapter[2].trim()}` : ''}`, line: i })
  }
  return out
}

/** Stable id for a heading so the outline can scroll to it. */
export function headingId(text: string, index: number): string {
  return `h-${index}-${text.replace(/\s+/g, '-').replace(/[^\p{L}\p{N}-]/gu, '').slice(0, 32)}`
}

/* ---------------- Text stats ---------------- */

/** Characters of CJK + words of Latin text, a fair "length" for mixed notes. */
export function textLength(content: string | null | undefined): number {
  if (!content) return 0
  const cjk = content.match(/[㐀-鿿豈-﫿]/g)?.length ?? 0
  const latinWords = content.replace(/[㐀-鿿豈-﫿]/g, ' ').match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g)?.length ?? 0
  return cjk + latinWords
}

/** Reading minutes at ~400 CJK chars / 200 Latin words per minute. */
export function readingMinutes(content: string | null | undefined): number {
  if (!content) return 0
  const cjk = content.match(/[㐀-鿿豈-﫿]/g)?.length ?? 0
  const latin = content.replace(/[㐀-鿿豈-﫿]/g, ' ').match(/[A-Za-z0-9]+/g)?.length ?? 0
  return Math.max(1, Math.round(cjk / 400 + latin / 200))
}

export function formatCount(n: number): string {
  if (n >= 10_000) return `${(n / 10_000).toFixed(n >= 100_000 ? 0 : 1)} 万`
  return n.toLocaleString('zh-CN')
}

/* ---------------- Upload validation ---------------- */

export interface UploadCheck {
  ok: boolean
  reason?: string
}

export function checkUpload(file: Pick<File, 'name' | 'size'>): UploadCheck {
  const lower = file.name.toLowerCase()
  const ext = lower.includes('.') ? lower.slice(lower.lastIndexOf('.')) : ''
  if (!(ACCEPTED_EXT as readonly string[]).includes(ext)) {
    const hint = ext === '.doc' ? '旧版 .doc 请另存为 .docx 再上传。' : '支持 PDF、Word（.docx）、Markdown 和 TXT。'
    return { ok: false, reason: `「${file.name}」的格式不支持。${hint}` }
  }
  if (file.size === 0) return { ok: false, reason: `「${file.name}」是空文件。` }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return { ok: false, reason: `「${file.name}」超过 ${MAX_UPLOAD_MB} MB。` }
  return { ok: true }
}

/* ---------------- Filtering & ordering ---------------- */

export type SortKey = 'recent' | 'title'

export function filterMaterials(
  items: MaterialItem[],
  opts: { query: string; kind: FileKind | 'all'; projectId: number | 'all' | 'none' },
): MaterialItem[] {
  const q = opts.query.trim().toLowerCase()
  return items.filter(m => {
    if (opts.kind !== 'all' && kindOf(m) !== opts.kind) return false
    const projects = m.project_ids ?? []
    if (opts.projectId === 'none' && projects.length > 0) return false
    if (typeof opts.projectId === 'number' && !projects.includes(opts.projectId)) return false
    return !q || m.title.toLowerCase().includes(q)
  })
}

export function sortMaterials(items: MaterialItem[], sort: SortKey): MaterialItem[] {
  const list = items.slice()
  if (sort === 'title') list.sort((a, b) => displayTitle(a.title).localeCompare(displayTitle(b.title), 'zh-CN') || b.id - a.id)
  else list.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : b.id - a.id))
  return list
}

/** Highlight query terms inside a search snippet. */
export function splitHighlight(text: string, query: string): Array<{ text: string; hit: boolean }> {
  const terms = query
    .trim()
    .split(/\s+/)
    .filter(t => t.length > 0)
    .map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (terms.length === 0) return [{ text, hit: false }]
  // split() with one capture group puts the matches at odd indices.
  const re = new RegExp(`(${terms.join('|')})`, 'i')
  return text
    .split(new RegExp(re.source, 'gi'))
    .map((part, i) => ({ text: part, hit: i % 2 === 1 }))
    .filter(part => part.text.length > 0)
}

/* ---------------- Display helpers ---------------- */

function plainSnippet(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_`>]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** A snippet that opens just before the first query term, markdown noise removed. */
export function snippetAround(text: string, query: string, before = 24, after = 150): string {
  const flat = plainSnippet(text)
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const lower = flat.toLowerCase()
  const hits = terms.map(t => lower.indexOf(t)).filter(i => i >= 0)
  const at = hits.length ? Math.min(...hits) : 0
  const start = Math.max(0, at - before)
  const end = Math.min(flat.length, at + after)
  return `${start > 0 ? '…' : ''}${flat.slice(start, end)}${end < flat.length ? '…' : ''}`
}

const norm = (s: string) => s.replace(/[\s:：·\-—_.,，。《》「」"'“”]/g, '').toLowerCase()

/** Drop a leading "# Title" that only repeats the material's own title. */
export function stripLeadingTitle(content: string, title: string): string {
  const m = /^\s*#\s+(.+?)\s*\r?\n/.exec(content)
  if (!m) return content
  const heading = norm(m[1])
  const own = norm(displayTitle(title))
  if (!heading || !own) return content
  const same = heading === own || (own.includes(heading) && heading.length / own.length > 0.5)
  return same ? content.slice(m[0].length).replace(/^\s*\n/, '') : content
}

import { describe, expect, it } from 'vitest'
import type { MaterialItem } from '../../services/materialApi'
import {
  checkUpload,
  displayTitle,
  filterMaterials,
  kindOf,
  outlineOf,
  readinessOf,
  readingMinutes,
  sortMaterials,
  snippetAround,
  splitHighlight,
  stripLeadingTitle,
  textLength,
} from './materialModel'

function mat(p: Partial<MaterialItem> & { id: number }): MaterialItem {
  return {
    title: `资料 ${p.id}.md`,
    created_at: `2026-09-0${Math.min(p.id, 9)}T00:00:00`,
    updated_at: `2026-09-0${Math.min(p.id, 9)}T00:00:00`,
    ...p,
  }
}

describe('file kinds and titles', () => {
  it('reads the kind from file_type, then from the title', () => {
    expect(kindOf({ file_type: 'PDF', title: 'x' })).toBe('pdf')
    expect(kindOf({ file_type: null, title: '笔记.markdown' })).toBe('md')
    expect(kindOf({ file_type: 'epub', title: 'x' })).toBe('other')
  })
  it('drops the upload extension from titles', () => {
    expect(displayTitle('线性代数讲义.pdf')).toBe('线性代数讲义')
    expect(displayTitle('v1.2 notes')).toBe('v1.2 notes')
  })
})

describe('readinessOf', () => {
  it('puts extraction failure first and forbids retry', () => {
    const r = readinessOf({ content_status: 'failed', retrieval_projection: null })
    expect(r.key).toBe('extract_failed')
    expect(r.canRetry).toBe(false)
  })
  it('maps projection states', () => {
    const base = { source_type: 'material', source_id: 1, backend: 'chroma', operation: 'upsert', source_version: 1, attempt_count: 1 }
    expect(readinessOf({ retrieval_projection: { ...base, status: 'ready', chunk_count: 4, vector_chunk_count: 4 } }).key).toBe('ready')
    expect(readinessOf({ retrieval_projection: { ...base, status: 'failed', chunk_count: 0, vector_chunk_count: 0, last_error: 'timeout' } }).detail).toContain('timeout')
    expect(readinessOf({ retrieval_projection: { ...base, status: 'degraded', chunk_count: 3, vector_chunk_count: 0 } }).canRetry).toBe(true)
    expect(readinessOf({ retrieval_projection: { ...base, status: 'degraded', chunk_count: 3, vector_chunk_count: 0 } }, false).canRetry).toBe(false)
    expect(readinessOf({ retrieval_projection: null }).key).toBe('none')
  })
})

describe('outlineOf', () => {
  it('collects markdown headings and ignores code fences', () => {
    const text = '# 标题\n正文\n```\n# 不是标题\n```\n## 小节 ##\n第三章 导数'
    expect(outlineOf(text).map(o => [o.level, o.text])).toEqual([
      [1, '标题'],
      [2, '小节'],
      [2, '第三章 导数'],
    ])
  })
  it('is empty for missing content', () => {
    expect(outlineOf(null)).toEqual([])
  })
})

describe('length helpers', () => {
  it('counts CJK characters and Latin words', () => {
    expect(textLength('费曼复盘 is useful')).toBe(4 + 2)
    expect(readingMinutes('字'.repeat(1200))).toBe(3)
    expect(readingMinutes('')).toBe(0)
  })
})

describe('checkUpload', () => {
  it('accepts supported files and explains rejections', () => {
    expect(checkUpload({ name: 'a.PDF', size: 10 }).ok).toBe(true)
    expect(checkUpload({ name: 'old.doc', size: 10 }).reason).toContain('.docx')
    expect(checkUpload({ name: 'x.png', size: 10 }).ok).toBe(false)
    expect(checkUpload({ name: 'e.md', size: 0 }).reason).toContain('空文件')
    expect(checkUpload({ name: 'big.pdf', size: 201 * 1024 * 1024 }).reason).toContain('200 MB')
  })
})

describe('filter and sort', () => {
  const items = [
    mat({ id: 1, title: '线性代数.pdf', file_type: 'pdf', project_ids: [7] }),
    mat({ id: 2, title: '费曼笔记.md', file_type: 'md', project_ids: [] }),
    mat({ id: 3, title: '概率论.pdf', file_type: 'pdf' }),
  ]
  it('filters by kind, project and title', () => {
    expect(filterMaterials(items, { query: '', kind: 'pdf', projectId: 'all' }).map(m => m.id)).toEqual([1, 3])
    expect(filterMaterials(items, { query: '', kind: 'all', projectId: 7 }).map(m => m.id)).toEqual([1])
    expect(filterMaterials(items, { query: '', kind: 'all', projectId: 'none' }).map(m => m.id)).toEqual([2, 3])
    expect(filterMaterials(items, { query: '费曼', kind: 'all', projectId: 'all' }).map(m => m.id)).toEqual([2])
  })
  it('sorts newest first by default and by title on request', () => {
    expect(sortMaterials(items, 'recent').map(m => m.id)).toEqual([3, 2, 1])
    expect(sortMaterials(items, 'title').map(m => m.id)).toHaveLength(3)
  })
})

describe('splitHighlight', () => {
  it('marks every occurrence of every term', () => {
    expect(splitHighlight('费曼复盘和费曼技巧', '费曼')).toEqual([
      { text: '费曼', hit: true },
      { text: '复盘和', hit: false },
      { text: '费曼', hit: true },
      { text: '技巧', hit: false },
    ])
  })
  it('escapes regex characters and handles an empty query', () => {
    expect(splitHighlight('a+b', 'a+')).toEqual([
      { text: 'a+', hit: true },
      { text: 'b', hit: false },
    ])
    expect(splitHighlight('text', '  ')).toEqual([{ text: 'text', hit: false }])
  })
})

describe('snippetAround', () => {
  it('centres on the first match and strips markdown', () => {
    const text = '# 标题\n' + '甲'.repeat(300) + '费曼复盘的关键' + '乙'.repeat(300)
    const snip = snippetAround(text, '费曼', 20, 40)
    expect(snip.startsWith('…')).toBe(true)
    expect(snip).toContain('费曼复盘')
    expect(snip).not.toContain('#')
  })
  it('falls back to the start when nothing matches', () => {
    expect(snippetAround('## 小节\n正文内容', '不存在', 50)).toBe('小节 正文内容')
  })
})

describe('stripLeadingTitle', () => {
  it('removes a first heading that repeats the title', () => {
    expect(stripLeadingTitle('# 间隔复习讲义\n\n## 1. 为什么', '间隔复习讲义.md')).toBe('## 1. 为什么')
    expect(stripLeadingTitle('# 主动学习与记忆方法速览\n正文', 'Demo：主动学习与记忆方法速览')).toBe('正文')
  })
  it('keeps unrelated headings', () => {
    expect(stripLeadingTitle('# 第一章\n正文', '线性代数讲义')).toBe('# 第一章\n正文')
  })
})

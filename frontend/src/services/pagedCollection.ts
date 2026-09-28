import { scopedApiFetch } from './apiClient'

/** Stable ID cursor: deletions between pages must not skip the next row. */
export async function fetchAllPages<T extends { id: number }>(
  url: string, fetch = scopedApiFetch(),
): Promise<T[]> {
  const result: T[] = []
  let afterId = 0
  while (true) {
    const page = await fetch<T[]>(`${url}${url.includes('?') ? '&' : '?'}limit=200&after_id=${afterId}`)
    if (!page.length) return result
    if (page.some(item => item.id <= afterId)) throw new Error('服务器分页协议不兼容，请升级服务器')
    result.push(...page)
    afterId = Math.max(...page.map(item => item.id))
    if (page.length < 200) return result
  }
}

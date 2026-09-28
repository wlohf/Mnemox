import { useCallback, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteMaterial,
  getMaterial,
  listMaterialChapters,
  listMaterials,
  searchMaterials,
  uploadMaterial,
  type MaterialItem,
} from '../../services/materialApi'
import { batchUpdateProjectMaterials, listProjects } from '../../services/conversationApi'
import { retryRetrievalProjection } from '../../services/aiSettingsApi'
import { startLearningPipeline } from '../../services/learningApi'
import { getRagHealth } from '../../services/ragApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { toast } from '../../ui'
import { qk } from '../../app/queryClient'
import { checkUpload, displayTitle } from './materialModel'

/*
 * Server state for the materials library. The list is the whole shelf
 * (up to 500 items), fetched once; individual texts load on demand.
 */

export const MATERIAL_LIMIT = 500

export interface UploadJob {
  id: string
  name: string
  state: 'uploading' | 'failed'
  error?: string
}

const detailKey = (id: number) => ['materials', 'detail', id] as const
const chaptersKey = (id: number) => ['materials', id, 'chapters'] as const

export function useMaterialDetail(id: number | null) {
  const detail = useQuery({
    queryKey: detailKey(id ?? 0),
    queryFn: () => getMaterial(id!),
    enabled: id != null,
    staleTime: 5 * 60_000,
  })
  const chapters = useQuery({
    queryKey: chaptersKey(id ?? 0),
    queryFn: () => listMaterialChapters(id!),
    enabled: id != null,
    staleTime: 5 * 60_000,
  })
  return { detail, chapters }
}

export function useContentSearch(query: string, enabled: boolean) {
  const q = query.trim()
  return useQuery({
    queryKey: ['materials', 'search', q],
    queryFn: () => searchMaterials(q, { topK: 12 }),
    enabled: enabled && q.length >= 2,
    staleTime: 60_000,
    retry: false,
  })
}

export function useMaterialsLibrary() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: qk.materials, queryFn: () => listMaterials(MATERIAL_LIMIT), staleTime: 30_000 })
  const projects = useQuery({ queryKey: qk.projects, queryFn: listProjects, staleTime: 60_000 })
  const rag = useQuery({ queryKey: ['rag', 'health'], queryFn: getRagHealth, staleTime: 60_000, retry: false })
  const [uploads, setUploads] = useState<UploadJob[]>([])
  const seq = useRef(0)

  const patch = useCallback(
    (next: MaterialItem) => {
      qc.setQueryData<MaterialItem[]>(qk.materials, prev => (prev ?? []).map(m => (m.id === next.id ? { ...m, ...next, content: m.content } : m)))
    },
    [qc],
  )

  /** Upload several files; returns the ids of the materials that landed. */
  const upload = useCallback(
    async (files: File[], syncToRag = true): Promise<number[]> => {
      const accepted: File[] = []
      for (const f of files) {
        const check = checkUpload(f)
        if (check.ok) accepted.push(f)
        else toast.warning('这份文件没有上传', { description: check.reason })
      }
      if (accepted.length === 0) return []

      const jobs = accepted.map(f => ({ id: `u${++seq.current}`, name: f.name, state: 'uploading' as const }))
      setUploads(prev => [...jobs, ...prev])

      const landed: number[] = []
      await Promise.all(
        accepted.map(async (file, i) => {
          const job = jobs[i]
          try {
            const r = await uploadMaterial(file, { syncToRag })
            landed.push(r.id)
            setUploads(prev => prev.filter(u => u.id !== job.id))
            if (r.duplicate) {
              toast.info('这份资料已经在资料库里', { description: `沿用已有的「${displayTitle(r.title)}」。` })
            } else if (r.content_status === 'failed') {
              toast.warning('已上传，但没能读出文字', { description: `「${displayTitle(r.title)}」可能是扫描件。` })
            } else {
              toast.success('已加入资料库', { description: displayTitle(r.title) })
            }
          } catch (error) {
            const message = getApiErrorMessage(error, '上传失败，请稍后重试')
            setUploads(prev => prev.map(u => (u.id === job.id ? { ...u, state: 'failed', error: message } : u)))
          }
        }),
      )
      await qc.invalidateQueries({ queryKey: qk.materials })
      void qc.invalidateQueries({ queryKey: ['rag', 'health'] })
      return landed
    },
    [qc],
  )

  const dismissUpload = useCallback((id: string) => setUploads(prev => prev.filter(u => u.id !== id)), [])

  const remove = useCallback(
    async (m: MaterialItem) => {
      await deleteMaterial(m.id)
      qc.setQueryData<MaterialItem[]>(qk.materials, prev => (prev ?? []).filter(x => x.id !== m.id))
      qc.removeQueries({ queryKey: detailKey(m.id) })
      // Deleting a material also removes its goals, chapters and tasks.
      void qc.invalidateQueries({ queryKey: ['goals'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: ['rag', 'health'] })
    },
    [qc],
  )

  const retryIndex = useCallback(
    async (m: MaterialItem) => {
      try {
        const projection = await retryRetrievalProjection(m.id)
        patch({ ...m, retrieval_projection: projection })
        if (projection.status === 'ready') toast.success('语义索引已建好')
        else toast.warning('还是只能按关键词检索', { description: projection.last_error || '向量模型可能还没配置。' })
      } catch (error) {
        toast.error(getApiErrorMessage(error, '重建索引失败'))
      }
    },
    [patch],
  )

  const setProjects = useCallback(
    async (m: MaterialItem, next: number[]) => {
      const current = new Set(m.project_ids ?? [])
      const wanted = new Set(next)
      const add = [...wanted].filter(id => !current.has(id))
      const drop = [...current].filter(id => !wanted.has(id))
      await Promise.all([
        ...add.map(pid => batchUpdateProjectMaterials(pid, [m.id], [])),
        ...drop.map(pid => batchUpdateProjectMaterials(pid, [], [m.id])),
      ])
      patch({ ...m, project_ids: [...wanted].sort((a, b) => a - b) })
      void qc.invalidateQueries({ queryKey: qk.projects })
    },
    [patch, qc],
  )

  const startLearning = useCallback(
    async (m: MaterialItem) => {
      const r = await startLearningPipeline(m.id)
      void qc.invalidateQueries({ queryKey: ['goals'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: chaptersKey(m.id) })
      void qc.invalidateQueries({ queryKey: ['review'] })
      return r
    },
    [qc],
  )

  return { list, projects, rag, uploads, upload, dismissUpload, remove, retryIndex, setProjects, startLearning }
}

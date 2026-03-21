import { useState, useEffect } from 'react'
import { Modal, Input, message, List, Checkbox, Spin } from 'antd'
import { useChatStore } from '../stores/chatStore'
import { getProject, batchUpdateProjectMaterials } from '../services/conversationApi'
import { apiFetch } from '../services/apiClient'

const { TextArea } = Input

const COLOR_OPTIONS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1',
  '#13c2c2', '#eb2f96', '#fa8c16', '#2f54eb', '#a0d911',
]

interface ProjectSettingsModalProps {
  open: boolean
  projectId?: number
  onClose: () => void
}

interface MaterialItem {
  id: number
  title: string
  file_type?: string
}

export function ProjectSettingsModal({ open, projectId, onClose }: ProjectSettingsModalProps) {
  const { projects, createProject, updateProject, deleteProject } = useChatStore()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [defaultInstructions, setDefaultInstructions] = useState('')
  const [color, setColor] = useState('#1890ff')
  const [loading, setLoading] = useState(false)
  const [materialsLoading, setMaterialsLoading] = useState(false)
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<Set<number>>(new Set())
  const [initialMaterialIds, setInitialMaterialIds] = useState<Set<number>>(new Set())

  const isEdit = projectId !== undefined
  const project = isEdit ? projects.find((p) => p.id === projectId) : null

  const loadMaterials = async () => {
    setMaterialsLoading(true)
    try {
      const res = await apiFetch('/api/materials/?skip=0&limit=200')
      if (!res.ok) {
        setMaterials([])
        return
      }
      const arr = await res.json()
      const list: MaterialItem[] = (arr || []).map((m: any) => ({
        id: m.id,
        title: m.title,
        file_type: m.file_type,
      }))
      setMaterials(list)
    } catch {
      setMaterials([])
    } finally {
      setMaterialsLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return

    void loadMaterials()

    if (project) {
      setName(project.name)
      setDescription(project.description || '')
      setDefaultInstructions(project.default_instructions || '')
      setColor(project.color || '#1890ff')
    } else if (!isEdit) {
      setName('')
      setDescription('')
      setDefaultInstructions('')
      setColor('#1890ff')
    }

    if (isEdit && projectId) {
      void (async () => {
        const detail = await getProject(projectId)
        const ids = new Set<number>(detail?.material_ids || [])
        setSelectedMaterialIds(ids)
        setInitialMaterialIds(new Set(ids))
      })()
    } else {
      setSelectedMaterialIds(new Set())
      setInitialMaterialIds(new Set())
    }
  }, [open, project, isEdit])

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning('请输入项目名称')
      return
    }
    setLoading(true)
    try {
      if (isEdit && projectId) {
        await updateProject(projectId, {
          name: name.trim(),
          description: description.trim() || undefined,
          default_instructions: defaultInstructions.trim() || undefined,
          color,
        })

        const toAdd = Array.from(selectedMaterialIds).filter((id) => !initialMaterialIds.has(id))
        const toRemove = Array.from(initialMaterialIds).filter((id) => !selectedMaterialIds.has(id))

        if (toAdd.length > 0 || toRemove.length > 0) {
          await batchUpdateProjectMaterials(projectId, toAdd, toRemove)
        }

        message.success('项目已更新')
      } else {
        const created = await createProject(name.trim(), description.trim(), defaultInstructions.trim(), color)
        if (!created) {
          throw new Error('创建项目失败')
        }

        if (selectedMaterialIds.size > 0) {
          await batchUpdateProjectMaterials(created.id, Array.from(selectedMaterialIds), [])
        }

        message.success('项目已创建')
      }
      onClose()
    } catch {
      message.error('操作失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = () => {
    if (!projectId) return
    Modal.confirm({
      title: '删除项目',
      content: '删除项目后，其下的对话将变为无项目对话。确定删除？',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await deleteProject(projectId)
        message.success('项目已删除')
        onClose()
      },
    })
  }

  return (
    <Modal
      title={isEdit ? '编辑项目' : '新建项目'}
      open={open}
      onOk={handleSave}
      onCancel={onClose}
      confirmLoading={loading}
      okText={isEdit ? '保存' : '创建'}
      cancelText="取消"
      width={500}
      footer={(_, { OkBtn, CancelBtn }) => (
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            {isEdit && (
              <a style={{ color: '#ff4d4f', fontSize: 13 }} onClick={handleDelete}>
                删除项目
              </a>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
    >
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 500 }}>
          项目名称 *
        </label>
        <Input
          placeholder="例如：高等数学、英语四级"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 500 }}>
          描述
        </label>
        <Input
          placeholder="项目描述（可选）"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 500 }}>
          默认 AI 指令
        </label>
        <TextArea
          placeholder="在此项目下的对话中，AI 会额外遵循这些指令（可选）&#10;例如：请用英文回答所有问题"
          value={defaultInstructions}
          onChange={(e) => setDefaultInstructions(e.target.value)}
          autoSize={{ minRows: 3, maxRows: 6 }}
          maxLength={2000}
          showCount
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={{ display: 'block', marginBottom: 8, fontSize: 13, fontWeight: 500 }}>
          颜色
        </label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {COLOR_OPTIONS.map((c) => (
            <div
              key={c}
              onClick={() => setColor(c)}
              style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                background: c,
                cursor: 'pointer',
                border: color === c ? '3px solid #333' : '3px solid transparent',
                transition: 'border 0.2s',
              }}
            />
          ))}
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <label style={{ display: 'block', marginBottom: 8, fontSize: 13, fontWeight: 500 }}>
          项目资料
        </label>
        {materialsLoading ? (
          <div style={{ textAlign: 'center', padding: '16px 0' }}><Spin size="small" /></div>
        ) : (
          <List
            size="small"
            bordered
            dataSource={materials}
            locale={{ emptyText: '暂无可绑定资料' }}
            style={{ maxHeight: 180, overflow: 'auto' }}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => {
                  setSelectedMaterialIds((prev) => {
                    const next = new Set(prev)
                    if (next.has(item.id)) {
                      next.delete(item.id)
                    } else {
                      next.add(item.id)
                    }
                    return next
                  })
                }}
              >
                <div style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 8 }}>
                  <Checkbox checked={selectedMaterialIds.has(item.id)} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.title}
                    </div>
                    <div style={{ fontSize: 11, color: '#999' }}>{item.file_type?.toUpperCase() || 'FILE'}</div>
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </div>
    </Modal>
  )
}

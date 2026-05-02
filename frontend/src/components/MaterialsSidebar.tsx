import {
  List,
  Button,
  Upload,
  Switch,
  Tag,
  Checkbox,
} from 'antd'
import {
  UploadOutlined,
  FileOutlined,
  DeleteOutlined,
  ExceptionOutlined,
  CalendarOutlined,
} from '@ant-design/icons'

interface Material {
  id: number
  name: string
  uploadTime: string
  file_type?: string
  file_path?: string
}

interface DailyPlan {
  date: string
  content: string
}

interface WrongQuestionPreview {
  id: number
  content: string
  mastery_status: string
}

interface MaterialsSidebarProps {
  materials: Material[]
  materialsLoading: boolean
  selectedMaterialIds: Set<number>
  onToggleMaterial: (id: number) => void
  onPreview: (material: Material) => void
  onDelete: (id: number) => void
  onUpload: (file: File) => boolean | Promise<boolean>
  syncToRAG: boolean
  onSyncChange: (val: boolean) => void
  ragStatus: {
    enabled: boolean
    rag_online: boolean
    total_chunks: number
    embedding_enabled?: boolean
    fallback_active?: boolean
    last_retrieval_status?: { message?: string; mode?: string; ok?: boolean }
  } | null
  weeklyPlans: DailyPlan[]
  wrongQuestions?: WrongQuestionPreview[]
}

export function MaterialsSidebar({
  materials,
  materialsLoading,
  selectedMaterialIds,
  onToggleMaterial,
  onPreview,
  onDelete,
  onUpload,
  syncToRAG,
  onSyncChange,
  ragStatus,
  weeklyPlans,
  wrongQuestions = [],
}: MaterialsSidebarProps) {

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
      {/* 资料库 */}
      <div style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>
            <FileOutlined /> 资料库
          </h3>
        </div>
        <List
          size="small"
          dataSource={materials}
          loading={materialsLoading}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  type="text"
                  size="small"
                  icon={<FileOutlined />}
                  onClick={(e) => { e.stopPropagation(); onPreview(item) }}
                  title="预览"
                  style={{ color: '#1890ff' }}
                />,
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => { e.stopPropagation(); onDelete(item.id) }}
                  title="删除"
                />,
              ]}
              style={{
                cursor: 'pointer',
                padding: '8px 12px',
                background: selectedMaterialIds.has(item.id) ? '#e6f7ff' : 'transparent',
                borderLeft: selectedMaterialIds.has(item.id) ? '3px solid #1890ff' : '3px solid transparent',
              }}
              onClick={() => onToggleMaterial(item.id)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                <Checkbox
                  checked={selectedMaterialIds.has(item.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleMaterial(item.id)}
                />
                <List.Item.Meta
                  avatar={<FileOutlined style={{ color: item.file_type === 'pdf' ? '#ff4d4f' : '#1890ff' }} />}
                  title={<span style={{ fontSize: 13 }}>{item.name}</span>}
                  description={
                    <span style={{ fontSize: 11, color: '#999' }}>
                      {item.uploadTime} · {item.file_type?.toUpperCase() || 'FILE'}
                    </span>
                  }
                />
              </div>
            </List.Item>
          )}
        />
      </div>

      {/* 导入资料 */}
      <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 12, color: '#666' }}>同步到 RAG 知识库</span>
          <Switch size="small" checked={syncToRAG} onChange={onSyncChange} />
        </div>
        {ragStatus && (
          <div style={{ marginBottom: 8 }}>
            <Tag color={ragStatus.enabled && ragStatus.rag_online ? 'green' : ragStatus.fallback_active || !ragStatus.embedding_enabled ? 'orange' : 'default'}>
              RAG 知识库: {ragStatus.rag_online ? '在线' : 'Fallback'}
            </Tag>
            {ragStatus.rag_online && (
              <Tag color="blue">
                {ragStatus.total_chunks} chunks
              </Tag>
            )}
            {ragStatus.last_retrieval_status?.message && (
              <div style={{ marginTop: 4, fontSize: 12, color: ragStatus.fallback_active ? '#fa8c16' : '#666' }}>
                {ragStatus.last_retrieval_status.message}
              </div>
            )}
          </div>
        )}
        <Upload.Dragger
          multiple
          beforeUpload={(file) => onUpload(file as unknown as File)}
          showUploadList={false}
          accept=".pdf,.docx,.txt,.md"
        >
          <p><UploadOutlined style={{ fontSize: 24 }} /></p>
          <p style={{ fontSize: 13, margin: '8px 0 4px' }}>点击或拖拽文件到此处上传</p>
          <p style={{ fontSize: 11, color: '#999' }}>支持 PDF、Word、TXT、Markdown、EPUB</p>
        </Upload.Dragger>
      </div>

      {/* 错题本 */}
      <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
        <h3 style={{ marginBottom: 16 }}>
          <ExceptionOutlined /> 错题本
        </h3>
        <List
          size="small"
          dataSource={wrongQuestions}
          locale={{ emptyText: '暂无错题' }}
          renderItem={(item) => (
            <List.Item style={{ cursor: 'pointer' }}>
              <List.Item.Meta
                title={<span style={{ fontSize: 13 }}>{item.content?.slice(0, 40) || `错题 #${item.id}`}</span>}
                description={
                  <span style={{ fontSize: 11, color: '#999' }}>
                    {item.mastery_status === 'mastered' ? '已掌握' : item.mastery_status === 'partial' ? '部分掌握' : '未掌握'}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </div>

      {/* 本周计划 */}
      <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
        <h3 style={{ marginBottom: 12 }}>
          <CalendarOutlined /> 本周计划
        </h3>
        <List
          size="small"
          dataSource={weeklyPlans}
          locale={{ emptyText: '本周暂无计划（在右侧日历中添加）' }}
          renderItem={(p) => (
            <List.Item style={{ padding: '6px 0' }}>
              <div style={{ width: '100%' }}>
                <div style={{ fontSize: 12, color: '#666' }}>{p.date}</div>
                <div
                  style={{
                    fontSize: 12,
                    color: '#999',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {(p.content || '').split('\n')[0] || '（空）'}
                </div>
              </div>
            </List.Item>
          )}
        />
      </div>
    </div>
  )
}

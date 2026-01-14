import { Card, Button, Upload, Table, Space } from 'antd'
import { UploadOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'

export function Materials() {
  const columns = [
    {
      title: '资料标题',
      dataIndex: 'title',
      key: 'title',
    },
    {
      title: '文件类型',
      dataIndex: 'file_type',
      key: 'file_type',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
    },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space size="middle">
          <Button type="link" icon={<EditOutlined />}>编辑</Button>
          <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1>资料管理</h1>
        <Upload>
          <Button type="primary" icon={<UploadOutlined />}>
            上传资料
          </Button>
        </Upload>
      </div>
      
      <Card>
        <Table
          columns={columns}
          dataSource={[]}
          locale={{ emptyText: '暂无资料，请点击上传' }}
        />
      </Card>
    </div>
  )
}

import { Card, List, Button, Space } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'

export function Notes() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1>笔记</h1>
        <Button type="primary" icon={<PlusOutlined />}>
          新建笔记
        </Button>
      </div>
      
      <Card>
        <List
          itemLayout="horizontal"
          dataSource={[]}
          locale={{ emptyText: '暂无笔记，点击新建笔记开始记录' }}
          renderItem={(item: any) => (
            <List.Item
              actions={[
                <Button type="link" icon={<EditOutlined />}>编辑</Button>,
                <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>,
              ]}
            >
              <List.Item.Meta
                title={item.title}
                description={`创建于 ${item.created_at}`}
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}

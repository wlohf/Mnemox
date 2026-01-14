import { Card, List, Button, Tag, Empty } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'

export function Review() {
  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>复习中心</h1>
      
      <Card title="今日待复习">
        <Empty description="暂无待复习内容">
          <Button type="primary">开始学习新内容</Button>
        </Empty>
      </Card>
      
      <Card title="复习历史" style={{ marginTop: 16 }}>
        <List
          itemLayout="horizontal"
          dataSource={[]}
          locale={{ emptyText: '还没有复习记录' }}
          renderItem={(item: any) => (
            <List.Item
              actions={[
                <Tag icon={<ClockCircleOutlined />} color="default">
                  {item.date}
                </Tag>,
                <Tag icon={<CheckCircleOutlined />} color="success">
                  已完成
                </Tag>,
              ]}
            >
              <List.Item.Meta
                title={item.title}
                description={item.description}
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}

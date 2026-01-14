import { Card, Row, Col, Input, Button, List, Avatar } from 'antd'
import { SendOutlined, UserOutlined, RobotOutlined } from '@ant-design/icons'

const { TextArea } = Input

export function Study() {
  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>学习空间</h1>
      
      <Row gutter={[16, 16]}>
        {/* AI 对话区 */}
        <Col span={16}>
          <Card title="AI 学习助手" style={{ height: 600 }}>
            {/* 对话列表 */}
            <div style={{ height: 450, overflowY: 'auto', marginBottom: 16 }}>
              <List
                itemLayout="horizontal"
                dataSource={[]}
                locale={{ emptyText: '开始你的学习之旅吧！' }}
                renderItem={(item: any) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={
                        <Avatar
                          icon={item.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                        />
                      }
                      description={item.content}
                    />
                  </List.Item>
                )}
              />
            </div>
            
            {/* 输入框 */}
            <div style={{ display: 'flex', gap: 8 }}>
              <TextArea
                placeholder="输入你的回答或问题..."
                autoSize={{ minRows: 2, maxRows: 4 }}
              />
              <Button type="primary" icon={<SendOutlined />}>
                发送
              </Button>
            </div>
          </Card>
        </Col>
        
        {/* 侧边栏 */}
        <Col span={8}>
          <Card title="当前章节" style={{ marginBottom: 16 }}>
            <p style={{ color: '#999' }}>请先选择要学习的资料</p>
          </Card>
          
          <Card title="番茄钟">
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 48, fontWeight: 'bold', margin: '24px 0' }}>
                25:00
              </div>
              <Button type="primary" size="large">
                开始学习
              </Button>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

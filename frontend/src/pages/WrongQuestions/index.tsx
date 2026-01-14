import { Card, Tabs, Table, Tag, Button } from 'antd'

export function WrongQuestions() {
  const columns = [
    {
      title: '题目',
      dataIndex: 'question',
      key: 'question',
    },
    {
      title: '题型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => <Tag>{type}</Tag>,
    },
    {
      title: '错误次数',
      dataIndex: 'wrong_count',
      key: 'wrong_count',
    },
    {
      title: '掌握状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const color = status === '已掌握' ? 'success' : status === '部分掌握' ? 'warning' : 'error'
        return <Tag color={color}>{status}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Button type="link">查看详情</Button>
      ),
    },
  ]

  const items = [
    {
      key: 'all',
      label: '全部错题',
      children: (
        <Table
          columns={columns}
          dataSource={[]}
          locale={{ emptyText: '暂无错题记录' }}
        />
      ),
    },
    {
      key: 'by-chapter',
      label: '按章节',
      children: (
        <Table
          columns={columns}
          dataSource={[]}
          locale={{ emptyText: '暂无错题记录' }}
        />
      ),
    },
    {
      key: 'by-type',
      label: '按题型',
      children: (
        <Table
          columns={columns}
          dataSource={[]}
          locale={{ emptyText: '暂无错题记录' }}
        />
      ),
    },
  ]

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>错题本</h1>
      
      <Card>
        <Tabs items={items} />
      </Card>
    </div>
  )
}

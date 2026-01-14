# 学习助手前端

基于 React + TypeScript + Ant Design 的前端应用。

## 快速开始

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

前端将在 http://localhost:5173 启动。

### 3. 构建生产版本

```bash
npm run build
```

构建产物将生成在 `dist` 目录。

## 项目结构

```
frontend/
├── src/
│   ├── components/          # 通用组件
│   │   └── Layout/          # 布局组件
│   ├── pages/               # 页面组件
│   │   ├── Dashboard/       # 仪表盘
│   │   ├── Materials/       # 资料管理
│   │   ├── Study/           # 学习空间
│   │   ├── Review/          # 复习中心
│   │   ├── WrongQuestions/  # 错题本
│   │   ├── Statistics/      # 统计分析
│   │   ├── Notes/           # 笔记
│   │   └── Settings/        # 设置
│   ├── services/            # API 调用（待实现）
│   ├── stores/              # 状态管理（待实现）
│   ├── hooks/               # 自定义 Hooks（待实现）
│   ├── types/               # TypeScript 类型定义（待实现）
│   ├── utils/               # 工具函数（待实现）
│   ├── App.tsx              # 应用入口
│   ├── main.tsx             # React 入口
│   └── index.css            # 全局样式
├── public/                  # 静态资源
├── index.html               # HTML 模板
├── vite.config.ts           # Vite 配置
├── tsconfig.json            # TypeScript 配置
└── package.json             # 项目依赖
```

## 功能页面

- **仪表盘** - 展示今日学习概览、学习日历、待办任务
- **资料管理** - 上传和管理学习资料
- **学习空间** - AI 对话学习、番茄钟计时
- **复习中心** - 间隔复习任务列表和复习历史
- **错题本** - 按章节、题型分类的错题管理
- **统计分析** - 学习时间、掌握程度、薄弱点分析
- **笔记** - Markdown 笔记管理
- **设置** - AI 配置、番茄钟设置、复习提醒

## 技术栈

- **React 18** - 前端框架
- **TypeScript** - 类型安全
- **Ant Design** - UI 组件库
- **React Router** - 路由管理
- **Zustand** - 状态管理（待集成）
- **ECharts** - 数据可视化（待集成）
- **Axios** - HTTP 请求（待集成）

## 开发规范

### 组件命名

- 使用 PascalCase 命名组件文件夹和文件
- 组件导出使用具名导出

### 样式

- 优先使用 Ant Design 的主题和组件样式
- 避免内联样式，使用 CSS Modules 或 styled-components

### 类型定义

- 为所有组件 props 定义类型
- 为 API 响应定义接口类型
- 使用 TypeScript 严格模式

## 下一步

- [ ] 实现 API 服务层
- [ ] 实现状态管理
- [ ] 集成数据可视化图表
- [ ] 实现 Markdown 编辑器
- [ ] 完善各页面功能
- [ ] 添加加载状态和错误处理
- [ ] 优化响应式布局
- [ ] 添加单元测试

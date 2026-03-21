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

## 项目结构（当前）

```
frontend/
├── src/
│   ├── components/          # 通用组件
│   │   └── Layout/          # 布局组件
│   ├── pages/               # 页面组件（当前包含 PomodoroPage）
│   ├── services/            # API 调用（chat/conversation/ai/pomodoro）
│   ├── stores/              # 状态管理（chat/pomodoro）
│   ├── hooks/               # 自定义 Hooks（按需扩展）
│   ├── types/               # TypeScript 类型定义（按需扩展）
│   ├── utils/               # 工具函数
│   ├── App.tsx              # 应用入口
│   ├── main.tsx             # React 入口
│   └── index.css            # 全局样式
├── public/                  # 静态资源
├── index.html               # HTML 模板
├── vite.config.ts           # Vite 配置
├── tsconfig.json            # TypeScript 配置
└── package.json             # 项目依赖
```

## 当前页面

- `/`：主学习页（对话 + 资料 + 日历 + 番茄）
- `/pomodoro`：番茄统计独立页（趋势 + 任务分布）

## 技术栈

- **React 18** - 前端框架
- **TypeScript** - 类型安全
- **Ant Design** - UI 组件库
- **React Router** - 路由管理
- **Zustand** - 状态管理
- **ECharts** - 数据可视化
- **Fetch API** - HTTP 请求

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

## 主要待办

- 将主页面进一步拆分为多页面（如错题本、复习中心、笔记）
- 项目-资料绑定管理入口（当前后端已支持，前端待补）
- 错题本与复习模块接入真实后端数据
- 增加测试与构建流程守护

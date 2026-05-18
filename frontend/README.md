# Mnemox Frontend

Mnemox 前端是一个基于 React + TypeScript + Vite 的 AI 学习教练界面。它连接 FastAPI 后端，提供 AI 对话、资料管理、番茄钟、错题复习、目标计划、笔记、学习画像、EDA 报告、主动干预、Agent 建议和 Anki 风格记忆卡等功能。

## 技术栈

- React 18
- TypeScript 5
- Vite 5
- Ant Design 5
- React Router 6
- Zustand
- Dexie / IndexedDB
- ECharts
- Toast UI Editor / React Markdown / KaTeX

## 快速开始

安装依赖：

```bash
cd frontend
npm install
```

启动开发服务器：

```bash
npm run dev
```

默认访问地址：

```text
http://localhost:5173
```

生产构建：

```bash
npm run build
```

本地预览构建产物：

```bash
npm run preview
```

代码检查：

```bash
npm run lint
```

## 后端依赖

前端默认通过相对路径访问后端 API，例如 `/api/chat/send`、`/api/materials`、`/api/goals`。开发时需要同时启动后端：

```bash
cd ../backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

如果使用 Docker 或反向代理，需要保证 `/api/*` 能转发到 FastAPI 后端。

## 当前页面

主要路由定义在 `src/App.tsx`：

- `/login`：登录与注册
- `/`：主学习工作台，包含对话、资料、侧栏和今日聚焦入口
- `/dashboard`：学习驾驶舱
- `/pomodoro`：番茄钟与统计
- `/wrong-questions`：错题本
- `/review`：间隔复习任务
- `/goals`：学习目标与任务
- `/plans`：每日计划
- `/notes`：笔记系统
- `/memory`：AI 记忆
- `/mastery`：掌握度地图
- `/progress`：进度引擎
- `/profile`：用户画像
- `/prompts`：Prompt 模板管理
- `/eda`：学习行为 EDA 报告
- `/intervention`：主动干预与每日报告
- `/agent`：自主学习 Agent
- `/anki`：Anki 风格记忆卡

除 `/login` 外，页面都通过 `ProtectedRoute` 保护，需要登录后访问。

## 项目结构

```text
frontend/
├── src/
│   ├── App.tsx                 # 路由、主题、同步引擎启动和系统更新检查
│   ├── main.tsx                # React 入口
│   ├── index.css               # 全局样式和主题变量
│   ├── components/             # 通用组件、聊天组件、设置弹窗、侧栏和布局
│   ├── components/Layout/      # 主布局、统计弹窗、今日聚焦动作
│   ├── pages/                  # 业务页面
│   ├── services/               # API 客户端和各业务接口封装
│   ├── stores/                 # Zustand 状态管理
│   ├── db/                     # Dexie 本地数据库定义
│   ├── sync/                   # 离线同步引擎、同步状态和模块适配器
│   ├── hooks/                  # 离线优先业务 hooks
│   └── types/                  # 第三方或本地类型声明
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── nginx.conf
```

## 数据与同步

前端使用 `localStorage` 保存登录 token、主题和系统设置。可离线编辑的数据使用 IndexedDB：

- `notes`
- `goals`
- `goalTasks`
- `ankiCards`
- `wrongQuestions`

同步逻辑由 `src/sync/SyncEngine.ts` 统一调度。它会在登录后启动，每 30 秒同步一次，也会在网络恢复时立即同步。各模块通过 `src/sync/adapters/*SyncAdapter.ts` 接入服务端 API。

同步状态通过 `SyncStatusIndicator` 展示，永久失败的本地操作会保留错误信息，方便用户重试或后续做冲突处理。

## API 约定

统一请求封装在 `src/services/apiClient.ts`：

- 自动附加 `Authorization: Bearer <token>`
- 非 `FormData` 请求自动设置 `Content-Type: application/json`
- 401 时清理 token 并跳转登录页
- 网络异常和 5xx 错误会展示 Ant Design message

新增接口时优先在 `src/services/` 下创建对应业务文件，不要在页面里直接散落 `fetch` 调用。

## UI 方向

当前 UI 以 Ant Design 为基础，并通过全局 CSS、主题 token、布局组件和局部自定义样式增强视觉表现。

外层目录 `../aether-ref` 是 Android Compose 项目 Aether 的参考代码，主要用于观察它的视觉风格、信息层级、动效节奏和组件细节；它不是 Mnemox 前端源码的一部分。后续如果继续模仿 Aether，建议先提炼设计原则，再映射到 Web 组件：

- 更清晰的主工作区与辅助侧栏层级
- 更轻的边框和阴影，减少默认后台管理感
- 更强的消息气泡、工具调用、上下文卡片和输入栏视觉重点
- 保持学习工具的高密度信息展示，不把应用改成营销落地页

## 开发约定

- 组件文件使用 PascalCase。
- 页面组件放在 `src/pages`，可复用组件放在 `src/components`。
- API 响应和请求类型尽量在对应 `services` 文件中定义。
- 新增离线模块时，需要同时扩展 Dexie 表、同步适配器、队列入队逻辑和 UI 同步状态。
- 样式优先复用现有主题变量和布局模式，避免引入新的全局视觉语言。
- 不要在前端持久化明文敏感信息，AI Provider Key 等敏感配置应走后端接口。

## 近期改进重点

- 继续收敛主界面视觉风格，明确从 Aether 借鉴哪些 Web 可落地的 UI 模式。
- 给 RAG 检索状态增加更清晰的前端提示，例如语义检索、关键词 fallback、embedding 错误。
- 完善离线同步冲突 UI，让用户能处理服务端和本地同时修改的记录。
- 为关键页面补充轻量组件测试或端到端冒烟测试。
- 清理过时样式和重复组件，减少页面之间的视觉割裂。

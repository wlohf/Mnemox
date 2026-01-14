# 学习助手 (Study Assistant)

一个基于认知科学学习方法的智能学习助手系统。

## 项目概述

通过 AI 辅导帮助用户高效学习和备考，整合多种科学学习方法：
- 费曼学习法（用自己的话解释）
- 间隔复习（艾宾浩斯遗忘曲线）
- 主动回忆（苏格拉底式提问）
- OKR 目标拆解
- 番茄工作法时间管理
- 学习进度可视化

## 技术栈

### 后端
- Python 3.10+
- FastAPI - 现代高性能 Web 框架
- SQLite - 轻量级数据库
- SQLAlchemy - ORM
- 多 AI 提供商支持（OpenAI, Claude, Gemini, Qwen）

### 前端
- React 18 + TypeScript
- Vite - 快速构建工具
- Ant Design - UI 组件库
- ECharts - 数据可视化

## 项目结构

```
StudyAssistant/
├── docs/                    # 设计文档
├── backend/                 # Python 后端
├── frontend/                # React 前端
├── data/                    # 数据存储
│   ├── study.db            # SQLite 数据库
│   └── uploads/            # 学习资料
└── README.md
```

## 快速开始

### ⚡ 一键启动（推荐）

**Windows 用户**：双击项目根目录的 `start.bat` 即可！

- 自动启动前后端服务
- 自动打开浏览器
- 无需手动操作

详细说明请查看 [启动指南.md](启动指南.md)

---

### 🔧 手动启动

**第一步：启动后端**

```bash
cd backend
pip install -r requirements.txt
python -m app.main
```

**第二步：启动前端**（另开一个终端）

```bash
cd frontend
npm install
npm run dev
```

**第三步：打开浏览器**

访问：http://localhost:5173

---

### 🛑 停止服务

双击 `stop.bat` 或直接关闭终端窗口

## 开发计划

- [x] 项目初始化
- [ ] 数据库设计和建表
- [ ] AI 服务适配层
- [ ] 资料上传和解析
- [ ] 学习流程引擎
- [ ] 间隔复习调度
- [ ] 前端界面开发

## 文档

详细的系统设计文档请查看 [docs/system-design.md](docs/system-design.md)

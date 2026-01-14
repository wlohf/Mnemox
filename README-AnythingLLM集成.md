# StudyAssistant × AnythingLLM 集成

<div align="center">

**智能学习助手 + 强大的 RAG 系统**

让您的学习资料变得"会说话"！

[快速开始](#快速开始) · [功能特性](#功能特性) · [架构说明](#架构说明) · [API 文档](#api-文档)

</div>

---

## 🎯 项目简介

本项目实现了 **StudyAssistant**（智能学习助手）与 **AnythingLLM**（开源 RAG 系统）的深度集成，让学习资料不再是静态的文档，而是可以与您智能对话的学习伙伴。

### 核心功能

- 📚 **智能资料管理**: 上传学习资料自动同步到 AnythingLLM
- 🤖 **RAG 问答**: 基于您的资料内容进行智能问答
- 📊 **资料分析**: AI 自动分析资料，提取重点和摘要
- 📝 **大纲生成**: 为任何资料自动生成学习大纲
- 🔍 **语义搜索**: 在海量资料中精准找到相关内容
- 💾 **本地部署**: 完全私有化，数据安全可控

## 🚀 快速开始

### 一键启动

```bash
# 1. 进入项目目录
cd StudyAssitant

# 2. 运行一键启动脚本
.\start_with_anythingllm.bat  # Windows

# 3. 等待所有服务启动完成
```

### 测试集成

```bash
cd backend
python test_integration.py
```

看到 "✅ 所有测试通过！" 即可开始使用！

### 详细安装步骤

请参考: [快速开始-AnythingLLM集成.md](./快速开始-AnythingLLM集成.md)

## ✨ 功能特性

### 1. 文档智能上传

```python
# 上传资料时自动同步到 RAG 系统
POST /api/materials/upload
{
  "title": "Python 编程基础",
  "file": <binary>,
  "sync_to_anythingllm": true
}
```

### 2. 智能问答

```python
# 向 AI 提问关于资料的任何问题
POST /api/materials/1/ask
{
  "question": "Python 中的装饰器是什么？"
}

# 响应
{
  "question": "Python 中的装饰器是什么？",
  "answer": "装饰器是 Python 中的一种设计模式，它允许在不修改原函数代码的情况下..."
}
```

### 3. 自动分析资料

```python
# AI 自动分析资料内容
POST /api/materials/1/analyze

# 自动回答以下问题：
# - 请总结这份资料的主要内容
# - 这份资料有哪些重点知识点？
# - 请为这份资料生成学习大纲
```

### 4. 生成学习大纲

```python
# 为资料生成详细的学习大纲
POST /api/materials/1/generate-outline

# 响应
{
  "outline": "第一章：Python 基础\n  1.1 变量与数据类型\n  1.2 运算符..."
}
```

## 🏗️ 架构说明

```
┌─────────────────────────────────────────────────────────┐
│                    用户界面层                             │
│  ┌──────────────┐              ┌──────────────┐         │
│  │ Web Frontend │              │  AnythingLLM │         │
│  │   (React)    │              │  Web UI      │         │
│  └──────┬───────┘              └──────────────┘         │
└─────────┼──────────────────────────────────────────────┘
          │
┌─────────┼──────────────────────────────────────────────┐
│         │              API 层                            │
│  ┌──────▼───────┐                                       │
│  │   FastAPI    │◄──────┐                               │
│  │   Routers    │       │                               │
│  └──────┬───────┘       │                               │
└─────────┼───────────────┼───────────────────────────────┘
          │               │
┌─────────┼───────────────┼───────────────────────────────┐
│         │    业务逻辑层    │                               │
│  ┌──────▼───────┐  ┌───▼──────────────┐                │
│  │   Material   │  │   AnythingLLM    │                │
│  │   Service    │──►    Provider      │                │
│  └──────┬───────┘  └───┬──────────────┘                │
└─────────┼───────────────┼───────────────────────────────┘
          │               │
┌─────────┼───────────────┼───────────────────────────────┐
│         │    存储层      │                               │
│  ┌──────▼───────┐  ┌───▼──────────────┐                │
│  │   SQLite     │  │  AnythingLLM     │                │
│  │   Database   │  │  API Server      │                │
│  └──────────────┘  │  + Collector     │                │
│                    └───┬──────────────┘                │
│                        │                                │
│                    ┌───▼──────────────┐                │
│                    │  Vector Database │                │
│                    │   (LanceDB)      │                │
│                    └──────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

### 技术栈

**后端 (StudyAssistant)**
- Python 3.10+
- FastAPI
- SQLAlchemy (异步)
- httpx (异步 HTTP 客户端)

**RAG 系统 (AnythingLLM)**
- Node.js
- Express
- LanceDB (向量数据库)
- 支持多种 LLM (OpenAI, Ollama, Claude 等)

**前端**
- React + TypeScript
- Vite
- TailwindCSS

## 📚 API 文档

启动服务后访问:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/materials/upload` | POST | 上传资料文件 |
| `/api/materials/` | GET | 获取资料列表 |
| `/api/materials/{id}` | GET | 获取资料详情 |
| `/api/materials/{id}/ask` | POST | 向 AI 提问 |
| `/api/materials/{id}/analyze` | POST | 分析资料 |
| `/api/materials/{id}/generate-outline` | POST | 生成大纲 |

详细 API 文档: [ANYTHINGLLM_INTEGRATION.md](./ANYTHINGLLM_INTEGRATION.md)

## 🔧 配置说明

### 环境变量

复制 `backend/env.example.anythingllm` 为 `backend/.env` 并配置：

```env
# 启用 AnythingLLM
ANYTHINGLLM_ENABLED=true
ANYTHINGLLM_BASE_URL=http://localhost:3001
ANYTHINGLLM_WORKSPACE=study-materials

# LLM 配置 (任选其一)
OPENAI_API_KEY=sk-...           # 使用 OpenAI
# 或使用本地 Ollama（无需 API Key）
```

### 使用本地 LLM (推荐)

完全免费，无需 API Key！

1. 安装 Ollama: https://ollama.ai
2. 下载模型: `ollama pull llama2`
3. 在 AnythingLLM Web 界面配置使用 Ollama

## 🎬 使用示例

### Python 脚本示例

```python
import requests

# 1. 上传资料
with open('python_tutorial.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/materials/upload',
        files={'file': f},
        data={
            'title': 'Python 教程',
            'sync_to_anythingllm': 'true'
        }
    )
material = response.json()
material_id = material['id']

# 2. 等待处理（通常几秒）
import time
time.sleep(10)

# 3. 提问
response = requests.post(
    f'http://localhost:8000/api/materials/{material_id}/ask',
    json={'question': '如何定义 Python 函数？'}
)
print(response.json()['answer'])
```

### cURL 示例

```bash
# 上传资料
curl -X POST "http://localhost:8000/api/materials/upload" \
  -F "title=学习资料" \
  -F "file=@document.pdf" \
  -F "sync_to_anythingllm=true"

# 提问
curl -X POST "http://localhost:8000/api/materials/1/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "这份资料的主要内容是什么？"}'
```

## 🐛 故障排除

### 常见问题

**Q: 提示 "AnythingLLM 服务未启动"**
```bash
# 检查服务状态
python backend/test_integration.py

# 手动启动 AnythingLLM
cd tools/anything-llm/server
yarn dev

# 新终端
cd tools/anything-llm/collector
yarn dev
```

**Q: 文件上传成功但无法问答**
- 等待文档处理完成（查看 AnythingLLM 日志）
- 访问 http://localhost:3001 检查文档是否在工作空间中
- 确保已配置 LLM 提供商

**Q: RAG 回答不准确**
- 尝试更详细的问题
- 检查文档是否完整上传
- 考虑使用更强大的 LLM 模型

更多问题请查看: [快速开始-AnythingLLM集成.md](./快速开始-AnythingLLM集成.md#常见问题)

## 📖 文档索引

- 📘 [快速开始指南](./快速开始-AnythingLLM集成.md) - 从零开始的完整教程
- 📗 [详细集成文档](./ANYTHINGLLM_INTEGRATION.md) - 深入的技术文档
- 📙 [API 参考](http://localhost:8000/docs) - 完整 API 文档（需启动服务）

## 🌟 核心优势

### 1. **完全私有化**
- 所有数据存储在本地
- 可使用本地 LLM (Ollama)
- 无需担心隐私泄露

### 2. **真正的 RAG**
- 基于向量搜索的语义理解
- 回答基于您的资料内容
- 支持引用和溯源

### 3. **易于扩展**
- 模块化设计
- 清晰的服务层
- 支持自定义 AI 功能

### 4. **开箱即用**
- 一键启动脚本
- 自动化测试
- 详细文档

## 🛣️ Roadmap

- [ ] 前端界面集成 RAG 功能
- [ ] 支持更多文档格式 (PPT, Excel, 视频字幕)
- [ ] 章节自动识别和切分
- [ ] 基于 RAG 的智能题目生成
- [ ] 学习笔记与原文关联
- [ ] 知识图谱可视化
- [ ] 多人协作学习

## 💡 使用场景

### 📖 考试备考
- 上传教材和讲义
- 快速查找知识点
- 生成复习大纲
- 模拟练习题

### 🎓 论文研究
- 管理大量文献
- 快速检索相关内容
- 总结论文要点
- 生成文献综述

### 💻 技术学习
- 整理技术文档
- 快速查询 API
- 代码示例搜索
- 技术概念解释

### 🏢 企业培训
- 管理培训资料
- 员工自助学习
- 知识库建设
- 快速答疑

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目采用 MIT 许可证。

---

<div align="center">

**如果觉得有帮助，请给个 ⭐ Star！**

Made with ❤️ for better learning

</div>

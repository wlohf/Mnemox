# AnythingLLM 集成指南

本文档介绍如何在 StudyAssistant 项目中集成和使用 AnythingLLM 的 RAG 功能。

## 功能概述

通过集成 AnythingLLM，StudyAssistant 获得以下能力：

1. **智能文档管理**：上传的学习资料自动同步到 AnythingLLM
2. **RAG 问答**：基于上传的资料进行智能问答
3. **资料分析**：自动分析资料内容，生成摘要和重点
4. **学习大纲生成**：为资料自动生成学习大纲

## 安装和配置

### 1. 启动 AnythingLLM 服务

首先需要启动 AnythingLLM 的服务器和文档处理器：

```bash
# 进入 AnythingLLM 目录
cd tools/anything-llm

# 安装依赖（首次运行）
cd server && yarn install
cd ../collector && yarn install

# 启动服务器（端口 3001）
cd server
yarn dev

# 启动文档处理器（端口 8888）- 新开一个终端
cd collector
yarn dev
```

### 2. 配置 StudyAssistant

编辑 `StudyAssistant/backend/.env` 文件（如果不存在，从 `.env.example` 复制）：

```env
# 启用 AnythingLLM 集成
ANYTHINGLLM_ENABLED=true

# AnythingLLM 服务地址
ANYTHINGLLM_BASE_URL=http://localhost:3001

# API 密钥（如果 AnythingLLM 开启了认证）
ANYTHINGLLM_API_KEY=

# 默认工作空间名称
ANYTHINGLLM_WORKSPACE=study-materials
```

### 3. 安装 Python 依赖

```bash
cd StudyAssistant/backend
pip install -r requirements.txt
```

### 4. 启动 StudyAssistant

```bash
# 在 StudyAssistant 根目录
python backend/app/main.py

# 或使用启动脚本
.\start.bat  # Windows
./start.sh   # Linux/Mac
```

## API 使用示例

### 1. 上传资料并自动同步到 AnythingLLM

```bash
curl -X POST "http://localhost:8000/api/materials/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "title=Python编程基础" \
  -F "file=@python_tutorial.pdf" \
  -F "sync_to_anythingllm=true"
```

响应：
```json
{
  "id": 1,
  "title": "Python编程基础",
  "file_path": "data/uploads/abc123.pdf",
  "file_type": "pdf",
  "created_at": "2026-01-11T10:00:00",
  "updated_at": "2026-01-11T10:00:00"
}
```

### 2. 获取资料列表

```bash
curl -X GET "http://localhost:8000/api/materials/"
```

### 3. 使用 RAG 分析资料

```bash
curl -X POST "http://localhost:8000/api/materials/1/analyze"
```

响应：
```json
{
  "title": "Python编程基础",
  "analysis": [
    {
      "question": "请总结这份资料的主要内容",
      "answer": "这份资料介绍了Python的基础知识..."
    },
    {
      "question": "这份资料有哪些重点知识点？",
      "answer": "主要包括：1. 变量和数据类型 2. 控制流..."
    },
    {
      "question": "请为这份资料生成学习大纲",
      "answer": "第一章：Python入门\n  1.1 环境搭建..."
    }
  ]
}
```

### 4. 向 AI 提问

```bash
curl -X POST "http://localhost:8000/api/materials/1/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Python中的列表和元组有什么区别？"
  }'
```

响应：
```json
{
  "question": "Python中的列表和元组有什么区别？",
  "answer": "列表(list)和元组(tuple)的主要区别在于：1. 可变性：列表是可变的，可以修改；元组是不可变的..."
}
```

### 5. 生成学习大纲

```bash
curl -X POST "http://localhost:8000/api/materials/1/generate-outline"
```

## 工作流程

```
用户上传文件
    ↓
StudyAssistant 保存文件
    ↓
创建数据库记录
    ↓
同步到 AnythingLLM
    ↓
AnythingLLM 处理文档
    ↓
文档被向量化并索引
    ↓
用户可以进行 RAG 问答
```

## 架构说明

### 核心组件

1. **AnythingLLMProvider** (`app/ai/anythingllm_provider.py`)
   - 与 AnythingLLM API 通信的客户端
   - 处理文档上传、RAG 查询等

2. **MaterialService** (`app/services/material_service.py`)
   - 资料管理的业务逻辑
   - 协调数据库操作和 AnythingLLM 同步

3. **Materials Router** (`app/routers/materials.py`)
   - RESTful API 端点
   - 处理 HTTP 请求和响应

### 数据流

```
Frontend → API Router → Service Layer → AnythingLLM Provider → AnythingLLM API
                ↓
           Database
```

## 故障排除

### 1. AnythingLLM 服务未启动

错误信息：`AnythingLLM 服务未启动`

解决方法：
- 确保在 `tools/anything-llm/server` 目录运行 `yarn dev`
- 检查 3001 端口是否被占用

### 2. 文档处理失败

错误信息：`文档处理服务未启动，请先启动 collector 服务`

解决方法：
- 确保在 `tools/anything-llm/collector` 目录运行 `yarn dev`
- 检查 8888 端口是否被占用

### 3. 上传文件但未同步

可能原因：
- `ANYTHINGLLM_ENABLED` 未设置为 `true`
- `sync_to_anythingllm` 参数设置为 `false`
- AnythingLLM 服务不可用（会记录错误但不影响主流程）

### 4. RAG 查询返回不相关的内容

可能原因：
- 文档尚未完全处理完成
- 工作空间中包含了其他不相关的文档
- 可以在 AnythingLLM Web 界面中查看工作空间内容

## 进阶使用

### 自定义工作空间

可以为不同类型的资料创建不同的工作空间：

```python
# 在代码中指定工作空间
material_service = MaterialService(db)
material_service.anythingllm.default_workspace = "math-materials"
```

### 批量上传

```python
for file_path in file_list:
    await material_service.create_material(
        title=file_path.name,
        file_path=str(file_path),
        sync_to_anythingllm=True
    )
```

### 自定义分析问题

修改 `analyze_document` 方法中的 `questions` 参数来自定义分析维度。

## Web 界面访问

AnythingLLM 提供了完整的 Web 管理界面：

1. 访问 http://localhost:3001
2. 可以查看所有工作空间和文档
3. 可以直接在界面中与文档对话
4. 查看文档处理状态和向量数据库

## 下一步

- [ ] 实现自动章节识别和切分
- [ ] 支持更多文档格式（DOCX、PPTX）
- [ ] 实现学习笔记自动关联到原文档位置
- [ ] 基于 RAG 的智能题目生成
- [ ] 学习进度跟踪和知识图谱

## 参考资源

- [AnythingLLM 官方文档](https://docs.anythingllm.com)
- [AnythingLLM API 文档](http://localhost:3001/api/docs) (服务启动后)
- [FastAPI 文档](https://fastapi.tiangolo.com)

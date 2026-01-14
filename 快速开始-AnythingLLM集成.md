# 快速开始 - AnythingLLM 集成

本指南将帮助您快速设置并使用 StudyAssistant 与 AnythingLLM 的集成功能。

## 前提条件

- ✅ Node.js (v18 或更高版本)
- ✅ Python 3.10+
- ✅ 已下载 AnythingLLM (位于 `tools/anything-llm` 目录)

## 快速启动（5 步完成）

### 步骤 1: 安装依赖

```bash
# 安装 AnythingLLM 依赖
cd tools/anything-llm/server
yarn install

cd ../collector
yarn install

# 安装 StudyAssistant 依赖
cd ../../StudyAssitant/backend
pip install -r requirements.txt

cd ../frontend
npm install
```

### 步骤 2: 配置环境变量

在 `StudyAssitant/backend` 目录创建 `.env` 文件：

```env
# 启用 AnythingLLM
ANYTHINGLLM_ENABLED=true
ANYTHINGLLM_BASE_URL=http://localhost:3001
ANYTHINGLLM_WORKSPACE=study-materials

# 其他必要配置
DATABASE_URL=sqlite+aiosqlite:///./data/study.db
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your-api-key-here  # 如果需要使用 OpenAI
```

### 步骤 3: 初始化数据库

```bash
cd StudyAssitant/backend
python init_db.py
```

### 步骤 4: 启动所有服务

**方式 A - 使用一键启动脚本（推荐）：**

```bash
cd StudyAssitant
.\start_with_anythingllm.bat  # Windows
```

**方式 B - 手动启动（需要 4 个终端窗口）：**

```bash
# 终端 1: AnythingLLM Server
cd tools/anything-llm/server
yarn dev

# 终端 2: AnythingLLM Collector
cd tools/anything-llm/collector
yarn dev

# 终端 3: StudyAssistant Backend
cd StudyAssitant/backend
python -m uvicorn app.main:app --reload

# 终端 4: StudyAssistant Frontend
cd StudyAssitant/frontend
npm run dev
```

### 步骤 5: 测试集成

运行测试脚本验证所有服务正常：

```bash
cd StudyAssitant/backend
python test_integration.py
```

如果看到 "✅ 所有测试通过！"，说明集成成功！

## 开始使用

### 访问界面

- 🌐 **StudyAssistant 前端**: http://localhost:5173
- 📚 **StudyAssistant API 文档**: http://localhost:8000/docs
- 🤖 **AnythingLLM Web 界面**: http://localhost:3001

### API 快速测试

#### 1. 上传资料

```bash
curl -X POST "http://localhost:8000/api/materials/upload" \
  -F "title=测试资料" \
  -F "file=@test.pdf" \
  -F "sync_to_anythingllm=true"
```

#### 2. 查看资料列表

```bash
curl "http://localhost:8000/api/materials/"
```

#### 3. 向 AI 提问

```bash
curl -X POST "http://localhost:8000/api/materials/1/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "这份资料讲了什么？"}'
```

#### 4. 生成学习大纲

```bash
curl -X POST "http://localhost:8000/api/materials/1/generate-outline"
```

## 功能演示

### 场景 1: 上传学习资料并智能问答

```python
import requests

# 1. 上传资料
files = {'file': open('python_tutorial.pdf', 'rb')}
data = {
    'title': 'Python 编程教程',
    'sync_to_anythingllm': True
}
response = requests.post('http://localhost:8000/api/materials/upload', 
                        files=files, data=data)
material = response.json()
material_id = material['id']

# 2. 等待处理完成（通常几秒到几分钟）
import time
time.sleep(10)

# 3. 向 AI 提问
question_data = {
    'question': 'Python 中如何定义函数？'
}
response = requests.post(
    f'http://localhost:8000/api/materials/{material_id}/ask',
    json=question_data
)
answer = response.json()
print(f"问题: {answer['question']}")
print(f"答案: {answer['answer']}")
```

### 场景 2: 自动生成学习大纲

```python
import requests

material_id = 1

response = requests.post(
    f'http://localhost:8000/api/materials/{material_id}/generate-outline'
)
outline = response.json()
print(outline['outline'])
```

### 场景 3: 资料深度分析

```python
import requests

material_id = 1

response = requests.post(
    f'http://localhost:8000/api/materials/{material_id}/analyze'
)
analysis = response.json()

for item in analysis['analysis']:
    print(f"\n问题: {item['question']}")
    print(f"答案: {item['answer']}")
    print("-" * 50)
```

## 使用 AnythingLLM Web 界面

1. 访问 http://localhost:3001
2. 首次访问会要求设置 LLM 提供商（可选择 OpenAI、Ollama 等）
3. 进入 `study-materials` 工作空间
4. 可以看到通过 StudyAssistant 上传的所有文档
5. 直接在界面中与文档对话

## 常见问题

### Q: 上传文件后提示 "AnythingLLM 服务未启动"

A: 确保以下服务都在运行：
- AnythingLLM Server (端口 3001)
- AnythingLLM Collector (端口 8888)

运行 `python test_integration.py` 检查服务状态。

### Q: RAG 查询没有返回相关内容

A: 
- 文档可能还在处理中，等待几分钟后重试
- 检查文档是否成功上传到 AnythingLLM (访问 http://localhost:3001)
- 确认问题表述清晰，与文档内容相关

### Q: 文件上传失败

A: 
- 检查文件格式是否支持（PDF、TXT、MD、DOCX 等）
- 确保文件大小不超过限制
- 检查 `data/uploads` 目录是否存在且有写入权限

### Q: 如何停止所有服务？

A: 
```bash
# Windows
.\stop_all.bat

# 或手动关闭所有终端窗口
```

### Q: 端口被占用怎么办？

A: 修改对应服务的端口配置：
- AnythingLLM Server: 修改 `tools/anything-llm/server/.env` 中的 `SERVER_PORT`
- StudyAssistant Backend: 修改启动命令中的 `--port` 参数
- 记得同步修改 `ANYTHINGLLM_BASE_URL` 配置

## 进阶配置

### 使用本地 LLM (Ollama)

1. 安装 Ollama: https://ollama.ai
2. 下载模型: `ollama pull llama2`
3. 在 AnythingLLM Web 界面中选择 Ollama 作为 LLM 提供商
4. 无需 API Key，完全本地运行！

### 多工作空间管理

```python
from app.ai.anythingllm_provider import AnythingLLMProvider

provider = AnythingLLMProvider()

# 为不同科目创建不同工作空间
await provider.ensure_workspace("math-materials")
await provider.ensure_workspace("english-materials")
await provider.ensure_workspace("programming-materials")
```

### 自定义文档元数据

```python
metadata = {
    "title": "高等数学第一章",
    "docAuthor": "张三",
    "description": "微积分基础",
    "docSource": "教材扫描件"
}

await provider.upload_document(
    file_path="math_ch1.pdf",
    metadata=metadata
)
```

## 下一步

- 📖 查看完整文档: [ANYTHINGLLM_INTEGRATION.md](./ANYTHINGLLM_INTEGRATION.md)
- 🎨 自定义前端界面以显示 RAG 功能
- 🔧 集成其他 AI 功能（题目生成、学习计划等）
- 📊 添加学习分析和统计功能

## 技术支持

遇到问题？
1. 查看 [ANYTHINGLLM_INTEGRATION.md](./ANYTHINGLLM_INTEGRATION.md) 的故障排除章节
2. 检查各服务的日志输出
3. 运行 `python test_integration.py` 诊断问题

祝学习愉快！🎓

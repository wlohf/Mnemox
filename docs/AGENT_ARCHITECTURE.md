# Agent Architecture

本版本加入轻量级 Agent 架构，用于把“对话、复习、计划”等学习能力封装成可扩展模块。

## 后端结构

- `backend/app/agents/base.py`：`AgentContext` 与 `BaseAgent`，统一持有数据库会话和当前用户。
- `backend/app/agents/chat_agent.py`：通用学习对话 Agent，可调用用户配置的 AI provider；AI 未配置时返回可读 fallback。
- `backend/app/agents/review_agent.py`：读取当前用户到期错题，生成复习摘要和行动建议。
- `backend/app/agents/study_plan_agent.py`：汇总当前用户逾期/今日任务和到期复习，生成今日安排。
- `backend/app/agents/manager.py`：Agent 注册表和实例化入口。
- `backend/app/services/agent_service.py`：服务层封装。
- `backend/app/routers/agent.py`：REST API。

## API

所有 Agent API 均需要登录态 Bearer Token。

```http
GET /api/agent
```

返回可用 Agent 列表。

```http
POST /api/agent/{agent_name}/run
Content-Type: application/json

{"payload": {}}
```

当前内置：

- `chat`：`payload.message` 为用户问题。
- `review`：可选 `payload.limit` 控制到期错题数量。
- `study_plan`：生成今日学习安排。

## 前端

- `frontend/src/services/agentApi.ts`：Agent API client。
- `frontend/src/pages/AgentPage.tsx`：Agent 工作台。
- 侧边栏新增 `/agent` 入口。

## 设计原则

1. 所有查询必须按 `current_user.id` 过滤，避免跨用户数据泄露。
2. Agent 可独立 fallback，AI 未配置不能导致整体 API 崩溃。
3. 新 Agent 只需继承 `BaseAgent` 并注册到 `AgentManager._registry`。

# Mnemox API Contract

> 更新日期：2026-09-04

本目录是给项目开发者和 AI Coding Agent 阅读的 API 说明。**OpenAPI 是机器事实源，本文档是领域导航和调用约束，不重复手抄全部 endpoint。**

## 事实源优先级

1. FastAPI `/openapi.json`：字段、参数、响应 schema 的机器事实源。
2. FastAPI `/docs` / `/redoc`：交互式查询入口。
3. `frontend/src/services/*Api.ts`：前端可调用的稳定业务函数边界。
4. `docs/api/*.md`：领域职责、关键流程、权限、错误和稳定性说明。

若人工文档与 OpenAPI 冲突，以当前代码生成的 OpenAPI 为准，并修正文档。

## 前端调用边界

```text
UI Component / Page
        ↓
Feature Hook / Store
        ↓
frontend/src/services/*Api.ts
        ↓
apiClient.ts
        ↓
FastAPI /api/...
```

UI 层禁止：

- 直接调用 `apiFetch()`；
- 直接拼 `/api/...`；
- 处理 cookie / Authorization 等传输细节；
- 根据 HTTP 状态码实现领域逻辑。

同步适配器和离线同步 hook 属于基础设施层，可以直接依赖 `apiClient`，但仍应集中管理 endpoint。

该边界由 `backend/tests/test_api_contract_boundary.py` 自动守卫。

## 领域索引

| 领域 | 文档 | 主要前端 Service |
| --- | --- | --- |
| 认证与会话 | [auth.md](auth.md) | `authApi.ts` |
| 资料 | [materials.md](materials.md) | `materialApi.ts` |
| 知识图谱 / Association | [knowledge.md](knowledge.md) | `knowledgeApi.ts`, `knowledgeLabApi.ts`, `associationApi.ts` |
| 学习 / 目标 / 计划 / 复习 | [learning.md](learning.md) | `learningApi.ts`, `goalApi.ts`, `planApi.ts`, `reviewApi.ts` |
| 记忆 | [memory.md](memory.md) | `memoryApi.ts` |
| Agent / Coach | [agent.md](agent.md) | `agentApi.ts`, `coachApi.ts` |
| 错误契约 | [error-contract.md](error-contract.md) | `apiClient.ts` |

## 稳定性标记

- **Stable**：当前前端生产路径依赖，修改 request/response 必须同步 service 和测试。
- **Internal**：内部运维或诊断接口，不作为 UI 公共能力承诺。
- **Experimental**：Stage/Spike 能力，可变更，但必须在文档或 endpoint 描述中明确。

当前目标不是一次性给 262 个 endpoint 全部补人工说明，而是保证：**核心 UI 路径有稳定 service、关键 response 有机器 schema、边界有自动测试、领域文档可导航。**

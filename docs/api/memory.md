# Memory API

## 职责

Memory 领域保存可持续使用的用户记忆、声明和时态事实，并与笔记/学习证据保持边界。

## 前端边界

- Stable Service：`frontend/src/services/memoryApi.ts`
- UI 只调用语义化函数，不直接访问 `/api/memory/...`。
- 时态冲突、纠正、失效和来源追溯由后端处理；前端不自行推断“当前事实”。

## Contract 原则

- 所有用户数据必须按 `current_user` 隔离。
- 错误和诊断信息不得泄漏 provider secret、数据库细节或其他用户内容。
- 记忆与笔记不是同一对象：笔记是用户可编辑内容，Memory 是 Agent 可消费的长期状态/事实层。

具体字段与实验性时态接口以 OpenAPI 为准。
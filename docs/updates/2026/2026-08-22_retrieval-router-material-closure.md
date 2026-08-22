# 2026-08-22 RetrievalRouter 与大资料混合检索闭环

## 本轮完成

- 新增统一 `RetrievalRouter`，覆盖 material、note、confirmed memory、concept、learner_state。
- 主聊天大资料从直接 `rag.retrieve(...)` 迁移到 Router material adapter。
- material adapter 接入 Chroma + keyword 的可替换 Hybrid backend，并保留 material ID、区间与 project scope。
- 标准化 chunk 来源、backend provenance、跨来源 RRF diagnostics。
- material 原始 Chroma/BM25/RRF 分数在 Router 边界归一化为 `[0,1]` 相对分数，避免主聊天把 RRF 小数误判为低相关度；原始分数继续保留用于调试。
- 保留 Agent 检索工具的空查询兼容行为：note、memory、concept、learner state 返回默认近期/高风险项，material 经 ContextStore 返回最近资料摘要且不触发语义 backend。
- 保留 `search_memories` 原有 `key`、`value_preview`、`locked` 响应字段，同时补充统一 Router 的来源信息和新字段，避免已有前端、评测与调用方发生破坏性变化。
- 新增 L0/L1/L2 加载。
- `ChatAgent`、`AgentKernel` 和 Agent 工具 API 新增 `search_concepts`、`search_learner_state`。
- `context_retrieve` 改走统一 Router。
- 笔记上下文服务改为通过 Router 的 note source 读取。
- 保留大资料全文截断作为最后降级路径。

## 风险处理

- staged、ignored 或过期记忆不会进入统一检索。
- 概念边与两端概念都做当前用户隔离。
- Router 跨来源 RRF 不重复计算 material 内部的 Chroma/keyword RRF。
- 共享 SQLAlchemy `AsyncSession` 的来源检索顺序执行，避免并发 session 操作。
- 关键词 BM25 当前是 reference/fallback，不作为最终大规模稀疏索引承诺。

## 测试

- 新增 `test_retrieval_router.py`：material scope、chunk provenance、分数归一化、空查询兼容、两层 RRF 边界、局部降级、L0 加载。
- 新增 `test_chat_retrieval_router_integration.py`：验证主聊天大资料实际调用 Router。
- 完整 CI 结果记录在对应 PR 中。

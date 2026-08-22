# RetrievalRouter × Material Hybrid 检索闭环

日期：2026-08-22

## 目标

把主聊天的大资料语义检索正式迁入统一 `RetrievalRouter`，同时恢复并固化第一阶段定义的统一检索边界：资料、笔记、已确认记忆、概念图和学习状态都通过同一个路由层进入 Agent、AgentKernel 与 Coach。

## 最终结构

```text
Chat / Coach / Agent / AgentKernel
              ↓
       RetrievalRouter
       ├── material（一个顶层来源）
       │      └── Chroma + keyword → 内部 RRF
       ├── note
       ├── confirmed memory
       ├── concept graph
       └── learner state
              ↓
      跨来源 RRF + L0/L1/L2
```

## 关键决策

1. **两层 RRF 不重复计权。** Chroma 与 keyword 是 material 来源内部的候选生成器；Router 只把融合后的 material 列表作为一个顶层来源，与 note、memory、concept、learner_state 融合。
2. **范围过滤先落 SQL。** `material_ids`、ID 区间和 `project_id` 由 `MaterialSearchScope` 解析，Chroma 只接收已经确认属于当前用户的真实资料 ID。
3. **已确认记忆才可召回。** Router 同时要求 `status=active`、`review_status=confirmed`、未过期，避免 staged/ignored 记忆进入上下文。
4. **概念边双重用户隔离。** 边必须属于当前用户，边两端概念也必须属于当前用户；异常跨用户端点不会进入结果。
5. **局部失败局部降级。** 任一来源失败只记录到 diagnostics，其余来源继续返回；单来源检索不做无意义的第二层 RRF。
6. **分层加载。** L0 返回标题，L1 返回片段或状态摘要，L2 才加载完整内容。
7. **关键词 backend 的定位。** 当前 BM25 风格实现是无额外依赖的 reference/fallback；大规模资料库稳定后可原位替换为 Qdrant sparse 或 PostgreSQL FTS，不改 Router 调用方。

## 主聊天行为

- 小资料仍全文注入。
- 大资料不再直接调用 `rag.retrieve(...)`，而是调用：

```python
RetrievalRouter(db).search(
    query=message,
    user_id=user_id,
    source_types=("material",),
    material_ids=large_ids,
    load_level=L1,
)
```

- 无命中或来源异常时，继续保留原有全文截断作为最终降级路径。

## 工具接线

`ChatAgent` 与 `AgentKernel` 统一支持：

- `search_notes`
- `search_materials`
- `search_memories`
- `search_concepts`
- `search_learner_state`
- `context_retrieve`

错题、画像、任务和反馈仍由各自领域服务负责，不强行塞入 RetrievalRouter。

## 验收标准

- material scope、chunk 来源和 backend provenance 可追踪；
- 跨来源 RRF 不把 Chroma/keyword 重复当成两个顶层来源；
- 单来源异常时其余来源仍可用；
- 主聊天的大资料路径实际经过 RetrievalRouter；
- Agent API 类型包含概念和学习状态检索；
- 完整后端、PostgreSQL、前端、桌面和浏览器 CI 全部通过；
- 更新记录与架构文档同步后再合并。

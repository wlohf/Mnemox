# 2026-08-22：检索生命周期、离线质量集与 Qdrant Spike

## 基线校准

- PR #8 已 squash 合并至 `main@5da524c`，统一 `RetrievalRouter` 覆盖资料、笔记、确认记忆、概念和学习者状态。
- GitHub Actions [run 32559668354](https://github.com/wlohf/Mnemox/actions/runs/32559668354) 的 Backend、Frontend、PostgreSQL 16 多 worker、Chromium、Windows smoke 与 Repository integrity 全部通过；它不替代真实 Electron 启动和正式生产发布。

## 功能变化

1. 新增版本化 `retrieval_projections` 与 `retrieval_projection_chunks`；Alembic / PostgreSQL head 升级为 `20260822_10`，SQLite lightweight migration 同步覆盖。
2. 统一资料 `ingest / refresh / forget / rebuild / retry`；旧分块替换、用户范围重建、无 embedding 降级、配置失效、失败删除墓碑和跨重启恢复均有持久化状态。
3. 新增 `PATCH /api/materials/{material_id}`、`GET /api/rag/projections` 和 `POST /api/rag/projections/{material_id}/retry`；资料列表、详情、设置和侧栏显示投影状态、错误与重试入口。
4. `/api/materials/search` 改为只经过 `RetrievalRouter`；SQL keyword backend 优先读取用户隔离且版本匹配的 chunk 清单。
5. 修复资料上传开关原先提交 `sync_to_anythingllm` 而不是后端实际识别的 `sync_to_rag`。
6. 新增 13 份资料 / 16 个查询的固定检索评测集及 CI Recall@5 门禁。
7. 用真实 Qdrant Local 对比 dense + sparse + 原生 RRF、轻量词项重排与 sparse 降级；当前语料未证明足够的生产切换收益，因此继续使用 Chroma。

架构边界、完整指标、可复现命令和 go/no-go 原因见 [检索生命周期与 Qdrant Spike 决策](../../superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md)。

## 验证结果

- 后端全量：`386 passed, 8 skipped, 53 subtests passed`；其中 4 个 PostgreSQL 服务验收和 4 个可选 Qdrant 用例在默认本地环境跳过。
- 安装 Qdrant 可选依赖后的生命周期、质量、Qdrant、schema、API 冒烟与多用户隔离聚焦回归：`54 passed`。
- 新增真实 API 更新/删除/投影状态冒烟及多用户隔离专项：`12 passed`。
- 前端：`24 files / 74 tests passed`；生产构建与 lint 均通过。
- 桌面端：`21 passed`。
- Alembic：12 个修订、单一 head `20260822_10`；9 份变更 Markdown 本地链接检查与 `git diff --check` 通过。
- 离线质量门禁：hybrid Recall@5 `0.9833`，跨用户泄漏与删除后残留均为 0。

## 下一模块

概念图谱自动抽取、人工编辑与先修缺口闭环。真实用户数据校准、正式 PostgreSQL 升级、真实 Electron 安装 / 启动 / 升级仍属于独立后续验收，不冒充本模块交付。

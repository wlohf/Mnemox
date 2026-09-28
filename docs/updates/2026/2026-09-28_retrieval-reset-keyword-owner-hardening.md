# 向量重置、关键词检索与数据归属修复

承接 [聊天流、资料上传与检索投影稳定性修复](2026-09-28_chat-upload-retrieval-hardening.md)，处理后端评审的第二批问题：维度不匹配时单个请求清空所有用户向量；关键词检索每次查询加载全部资料正文；多处 `user_id` 缺省回落到 1 号用户或跳过归属过滤。

## 修改

### 1. 向量维度不匹配不再由请求直接清空全局集合

- `RAGService` 在检索、写入或语义检索校验中发现维度不匹配时，只标记 `vector_incompatible`：暂停语义检索与新的 embedding 调用，状态提示回退关键词检索，并对同一次不匹配只请求一次重置。
- 新增 `reset_incompatible_vector_collection`：在排他配置锁下（等待进行中的 ingest 完成）重置共享集合，并把所有 `ready` 资料投影改为 `degraded`（清零向量数、写明需重建），前端据此显示重试入口；`failed`、`pending` 等状态保持不变。重置失败时清除标记，下次查询重新检测并重试。
- 应用启动时向 `RAGService` 注册该处理器，经后台运行器按固定键串行执行；`GET /api/rag/health` 增加 `vector_incompatible` 字段，`message` 同步显示暂停原因。
- 与 RAG 设置页修改配置的路径保持一致：不自动重新嵌入（避免费用），由用户重建。

### 2. 关键词检索不再每次加载全部正文

- `Material.content` 的 ORM 写入会自动刷新 `content_hash`（`material_content_digest`，与投影使用同一公式）。检索时用该列与投影摘要比较，一致即信任已持久化的分块清单，不读取正文；不一致（历史行、缺少投影）才读取正文核对，仍不一致的按原逻辑现场分块。应用内没有绕过 ORM 修改资料正文的写法，今后也不应引入。
- 新增按分块文本摘要（`chunk_hash`）寻址的分词缓存（LRU，上限约 200 万个词频项）。缓存命中时只读取分块元数据；未命中的分块和最终返回的前 k 个片段才读取文本。BM25 公式与原实现逐项一致，由对照测试固定。
- 语义检索结果校验同样改为优先比较摘要，不再为每个命中资料加载全文。
- 未引入 FTS5 / PostgreSQL 全文索引：数据库方向未定，先做与数据库无关的优化。语料超过缓存上限时仍正确，但被淘汰的分块会重新分词。

### 3. 数据归属不再回落到 1 号用户

- 移除 17 个模型 `user_id` 列的 `default=1`；新增 `before_flush` 检查，新建这些行时缺少 `user_id` 直接报错，覆盖仍带 `DEFAULT 1` 的旧 SQLite 库。未改变数据库结构，不需要迁移。
- 记忆服务、事件追踪、资料服务中 `user_id: int = 1` 的参数改为必填；扫描确认所有调用方都已显式传入。
- 修复反思流程新建对话摘要时未写 `user_id`（落到 1 号用户）的问题。
- 聊天错题检测、自动建目标、资料名检测、最近资料查询中“`user_id` 为空就跳过归属过滤”的写法改为必填并无条件过滤；`_auto_create_goal_and_tasks` 查询资料时原本完全不按用户过滤，现已限定为本人资料。`MaterialService.get_material` / `list_materials` / `delete_material` 同样改为必须按用户查询。

## 涉及文件

- 后端：`app/ai/rag_service.py`、`app/routers/rag.py`、`app/services/retrieval_projection_service.py`、`app/services/material_retrieval_backend.py`、`app/main.py`、`app/utils/transaction_policy.py`、`app/models/material.py`、`app/models/__init__.py`、17 个模型文件的 `user_id` 列、`app/services/memory_service.py`、`app/services/event_tracker.py`、`app/services/material_service.py`、`app/routers/chat.py`、`app/routers/learning.py`
- 测试：`tests/test_rag_service_status.py`、`tests/test_material_retrieval_backend.py`、`tests/test_retrieval_projection_lifecycle.py`、`tests/test_owner_scoping.py`（新增）

## 验证

- 新增用例覆盖：维度不匹配时不清空集合、只请求一次重置、暂停期间不调用 embedding；统一重置只执行一次、覆盖所有用户、只把 `ready` 改为 `degraded`；热缓存查询不读取正文且不重复分词；关键词得分与原 BM25 实现逐项一致；缺少 `user_id` 时写入前报错；反思摘要归属对话所有者；自动建目标不作用于他人资料；资料服务按用户读取和删除。
- `test_rag_service_status.py` 中“检索遇到维度不匹配立即清空集合”的旧断言改为验证新行为。
- 后端完整回归：**770 passed、50 skipped、70 subtests passed**，约 268 秒，pytest 退出码 0；较上一批（762 passed）新增的 8 项全部通过，跳过与警告数量不变。环境同上一批（`/tmp` 下的 Python 3.12 临时虚拟环境，临时数据目录，未连接 PostgreSQL）。本批无前端改动。

## 已知限制

- 维度不匹配后需用户重建索引，才会恢复语义检索；不会自动重新嵌入。
- `content_hash` 依赖 ORM 写入；绕过 ORM 直接改 `materials.content` 会使关键词检索沿用旧分块。
- 分词缓存为进程内缓存，按单实例部署设计。

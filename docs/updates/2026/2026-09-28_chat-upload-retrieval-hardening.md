# 聊天流、资料上传与检索投影稳定性修复

后端评审发现的 4 个问题：聊天回复结束前串行等待额外模型调用；流式保存写库过密；大文件上传阻塞事件循环；项目归属变化触发整份资料付费重嵌入。本次一并修复，并补齐前端索引状态显示。

## 修改

### 1. 聊天后处理不再阻塞 `[DONE]`

- `_persist_streamed_chat_turn` 只负责主消息落库（保留 SQLite 写锁重试），随后把摘要、长期记忆抽取、反思、错题检测和学习事件交给 `_enrich_streamed_chat_turn` 在后台执行，并返回该任务。
- 新增 `app/services/background_runner.py`：进程内有界运行器，保留强引用，全局并发上限 4，同一对话按提交顺序串行，避免连续两轮同时写同一摘要；应用关闭时最多等待 10 秒后取消剩余任务。
- 用户在 `[DONE]` 后断开连接不再取消记忆抽取。后处理仍是尽力而为：进程在后处理完成前重启时，本轮后处理会丢失（与原先失败时仅记日志的语义一致）；需要跨重启补跑时再引入持久任务表。

### 2. 流式保存降频

- 请求摘要 `chat_request_hash` 每轮只计算一次，不再在每次保存时对整个请求体（含 base64 图片）重新序列化和哈希。
- 保留“先提交再推送”的约定；首段立即提交，之后按 0.5 秒或 2048 字符批量提交（原为 150 毫秒 / 1024 字符）。新增截止时间：模型输出停顿时，已暂存的文本到期即提交并推送，不再等下一段输出。
- 中途保存只更新回复内容；对话标题和 `updated_at` 仅在开始和终态（完成/中断）时更新。

### 3. 上传不再阻塞服务

- 上传文件的边写边哈希与格式签名校验放入线程执行。
- PDF / DOCX 文本抽取改在 `spawn` 子进程中执行，超时后强制结束子进程（原先线程超时后仍在后台解析并争用 GIL）；TXT / MD 为有界读取，仍在进程内完成。桌面入口 `desktop_main.py` 增加 `multiprocessing.freeze_support()`，避免打包后的 exe 在启动子进程时重复拉起后端。
- 新建资料时，若配置了 embedding，向量化改为后台执行，接口立即返回 `pending` 投影；未配置 embedding 或关闭向量同步时，仍在请求内完成 SQL 分块并返回 `degraded`。后台任务在重启前未完成的，会由启动恢复流程重新索引（`pending` / `indexing` 属于恢复状态）。
- 前端资料列表把 `pending` 显示为“索引处理中”，存在排队/索引中的资料时每 4 秒静默刷新索引状态，完成后停止。

### 4. 项目归属不再触发重嵌入

- 每个资料 chunk 只写一份向量（ID `mat{material_id}_chunk{i}`），不再按项目复制，也不再写 `project_id` 元数据；项目范围统一在 SQL 中解析为资料 ID 后过滤。
- 投影签名不再包含项目归属；删除 `_reindex_material_for_projects`，加入/移出项目只修改 SQL 关联。
- 兼容旧索引：签名仍为旧格式（含 `project_ids`）且内容、配置未变的 `ready` 投影会直接改用新签名，不会在升级后整体重新嵌入。旧的按项目重复向量在检索时去重（语义检索 4 倍过采样），下次重建该资料时被清理。

## 涉及文件

- 后端：`app/routers/chat.py`、`app/services/chat_progress.py`、`app/services/background_runner.py`（新增）、`app/main.py`、`app/routers/materials.py`、`app/utils/file_extract.py`、`app/services/material_service.py`、`desktop_main.py`、`app/ai/rag_service.py`、`app/services/material_retrieval_backend.py`、`app/services/retrieval_projection_service.py`、`app/routers/chat_projects.py`、`app/routers/system.py`
- 前端：`src/components/Layout/ObsidianLayout.tsx`
- 测试：`tests/test_chat_stream_persistence.py`、`tests/test_background_runner.py`（新增）、`tests/test_file_extract_isolation.py`（新增）、`tests/test_retrieval_projection_lifecycle.py`、`tests/test_multi_user_isolation.py`

## 验证

- 新增用例覆盖：后处理阻塞时 `[DONE]` 仍立即到达且断开后后处理继续完成；40 段输出批量提交且复用同一请求摘要；模型停顿时暂存文本按截止时间释放；中途保存不改对话行；运行器同键顺序、并发上限、失败隔离与关闭取消；子进程超时被结束、子进程异常上报、DOCX 子进程抽取、纯文本不起子进程；项目归属变化不重嵌入；旧签名沿用不重嵌入；有 embedding 时上传后后台完成向量化；无 embedding 时请求内降级完成。
- `test_multi_user_isolation.py` 中“批量调整项目资料会重新索引 2 次”的旧断言改为“不调用任何索引”。
- 前端：`tsc --noEmit`、改动文件 ESLint、`vitest run`（37 个文件 / 165 项）通过。
- 后端完整回归：**762 passed、50 skipped、70 subtests passed**，约 268 秒；改动前同一环境基线为 747 passed、50 skipped，新增 15 项全部通过，无新增失败或警告。跳过项保留其外部平台/集成条件，不当作通过。
- 测试环境：仓库内 `backend/venv` 基于已不存在的 Python 3.10，无法运行；本次在 `/tmp` 的独立 Python 3.12 虚拟环境按 `requirements-dev.txt` 安装依赖执行，数据目录指向临时目录，未连接 PostgreSQL，也未做真实浏览器或 Windows 打包验证。

## 已知限制

- 聊天后处理与新资料向量化依赖进程内运行器，均按单实例部署设计；多实例部署需要改为持久队列。
- 每轮记忆抽取仍会调用一次模型，本次只消除了等待和断开丢失，没有降低调用次数。
- `desktop_main.py` 的 `freeze_support()` 未在真实 Windows 打包产物上验证。

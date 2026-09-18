# P0/P1 稳定化第二阶段：离线同步协议

日期：2026-09-12。状态：**工作区实现和本地验收完成，未提交、合入或部署**。延续[第一阶段](2026-09-12_p0-p1-hardening-phase1.md)，没有修改真实数据库、真实附件或密钥，没有自动认领旧离线数据。本次“第二阶段”指工程审查后的稳定化批次，不是产品路线图中的 V2 Stage 2。

## 1. 实现范围

### 本地事务与不可变请求

- `saveLocalOperation` 在一个 IndexedDB 事务中修改本地记录与队列；失败整体回滚。笔记、目标、目标任务 hooks 统一使用该入口，不再先写记录再入队，也不再绕过队列直接删除。
- Dexie v5 为操作分配独立 UUID。领取后冻结操作正文、服务端 ID、父目标 ID、预期版本和幂等键；重试/刷新沿用原请求。只有未领取的连续 update 可以合并，领取后的再编辑另建操作。
- `acknowledgeOperation` 只确认相同 UUID 的队列行。仍有后续编辑/删除时不覆盖本地内容；返回的服务端身份和版本用于下一次领取，不会把推送中的新编辑误标为已同步。
- 未发送的 create + delete 可以原子取消；已经领取、结果不确定的 create 必须先重放确认，再补偿 delete。目标删除包含子任务；未确认远端删除前保留本地子任务，删除中的目标不能再添加任务。

### 服务端幂等与版本控制

适用模块：`notes`、`goals`、`goalTasks`、`ankiCards`、`wrongQuestions` 的同步 CRUD。

- 新增 `GET /api/sync/capabilities`，返回 `protocol_version: 1`；新客户端在写入前探测，旧服务端/不支持协议时保留本地操作并报错，不冒险发送可能被忽略的保护头。
- 每个 POST/PUT/DELETE 可以携带 `Idempotency-Key`。`sync_receipts` 以用户和 key 唯一；指纹包含方法、路径、正文以及预期版本头。相同请求返回原成功结果，不重复执行；同 key 不同请求返回 `409 IDEMPOTENCY_KEY_REUSED`。
- SQLite/PostgreSQL 使用 `INSERT ... ON CONFLICT DO NOTHING RETURNING` 预留回执。领域写入和成功回执在同一事务提交/回滚。SQLite 笔记更新/删除继续在已有写锁内部提交；新增全局 ORM 版本冲突到 HTTP 409 的映射。
- 五类实体增加整数 `sync_version`，通过 SQLAlchemy `version_id_col` 约束 ORM 更新/删除。PUT/DELETE 接受 `If-Match: "<version>"`；过期版本返回 `409 SYNC_CONFLICT`。响应通过 JSON 提供版本，并非新增 HTTP 缓存 ETag 功能。旧客户端不带头仍兼容，但不享有客户端预期版本检查，其 ORM 写入仍推进版本。
- 笔记只改 links 也推进版本，并重新加载响应关系，避免返回旧链接。目标和任务可空字段的显式 null 不再被静默忽略。Anki 增加卡片编辑/删除入口，编辑限正文/说明/标签，不通过此入口改写复习调度状态。
- 新增 `GET /api/sync/{module}/{id}` 供冲突处理读取自有规范快照；不存在/不归属均为 404。归属检查先于版本比较。

### 冲突、拉取与时间

- 冲突保留队列和本地正文，不做时钟猜测或自动覆盖。采用云端时重新取规范快照；保留本机时使用新 UUID 和确认过的服务端版本，发生第二次并发修改则再次冲突。
- 本地删除、远端已删除、预览不可用分别提示；重新创建/继续删除是明确选择，而非静默复活记录。
- 拉取后只有仍为 synced、没有队列操作、且本地修订/服务端版本/时间未变化的行才能被覆盖。存在已领取或历史不确定 create 时，暂缓导入该模块的陌生服务端行，防止响应丢失期间重复展示。
- Anki 的 `limit=200` 和错题分页都不是完整删除快照，不能据此删掉未出现的本地行。目标任务任一分组拉取失败，不执行部分列表的删除对账。
- 同步响应使用共享 UTC `Z` 序列化；客户端兼容把旧 naive datetime 解释为 UTC，日期型业务字段不加时区。新增/修正的部分写入采用 `utc_now_db()`。这不是对全库历史墙上时间或所有旧路由的迁移。

## 2. 升级与运维边界

1. 新增迁移 `20260912_23`，上游为 `20260903_22`：五张领域表的 `sync_version` 与 `sync_receipts`。SQLite lightweight upgrade 同步补列；无版本数据库指纹识别也加入新结构，避免误当旧基线接管。
2. **先备份，再升级服务端和数据库，最后升级客户端。** PostgreSQL 必须先应用迁移；新客户端遇到旧服务端会停止排队写入，而不是降级到不安全协议。没有执行正式库迁移。
3. Dexie v4 及更早的无幂等键 create 可能已在云端成功：升级后标记 `legacyUncertain/failed`，保留内容和操作，普通重试不会解除隔离。需人工核对云端并备份本地内容，不能通过删库、清队列或回退旧客户端“修复”。专门的历史队列恢复 UI 尚未实现。
4. 回执在领域记录删除后仍存在，以防旧请求再次创建记录。目前回执保存成功响应，可能含业务正文；**删除领域对象不等于擦除其历史同步回执**。上线前需确定容量、保留期限和隐私擦除策略；不能直接清空回执而重新开放重放窗口，应设计保留去重墓碑的压缩/擦除方案。备份也需按同一策略处理。
5. 旧的不带版本头的在线调用仍兼容；当前协议不能承诺任意旧客户端、原始 SQL/bulk 写入、绕过统一入口的扩展也享有版本保护。新写入路径必须遵守版本与事务契约。
6. Anki/错题目前优先保证“不误删”，尚未完成所有分页的增量同步及远端删除收敛；同账号多标签页 leader/锁、队列恢复交互和终态 4xx 的人工处理仍需完善。

## 3. 验证证据

所有后端验证在 `/tmp` 源码副本和合成 SQLite 中执行，排除 `.env`、真实数据、上传和依赖目录；使用现有 Python 3.10.12 环境。前端为 Node 24.16.0。CI 的 Python 3.11 / Node 20、真实 PostgreSQL 多进程和 Windows 验收不能由这些结果替代。

| 验证 | 结果与边界 |
| --- | --- |
| 前端全量 Vitest | **32 files / 141 tests passed**；使用 fake-indexeddb 和模拟网络，覆盖原子回滚、领取期间编辑/删除、刷新后重放、旧服务器拒绝、拉取竞争、目标级删除、UTC 与升级隔离 |
| 后端协议/迁移/事务专项 | **31 passed, 10 subtests passed**；含五模块 HTTP CRUD、重复键/版本变化、所有权、并发创建/更新、回滚、显式 null、links-only 响应与版本。HTTP 专项使用 ASGI + 合成鉴权，不是真实多进程 |
| 后端安全/兼容宽回归 | **98 passed, 2 subtests passed**；含第一阶段授权、出站、上传、AI、聊天、笔记关联、UTC/API 边界。不是全量后端测试 |
| 实际 SQLite Alembic | 从空库升至 head、降至 `20260903_22`、再升级均通过；唯一 head 为 `20260912_23`，`alembic check` 无新增操作 |
| 真实 Chromium + HTTP + IndexedDB | **5 项通过**：真实注册登录/HttpOnly Cookie、实际已提交的 POST 响应丢失后浏览器刷新去重、真实版本冲突保留本地内容、UI 采用云端、UI 明确确认删除冲突。时区 Asia/Shanghai；仅合成账号/独立后端 |
| 静态与构建 | `tsc --noEmit`、lint、Vite production build、`git diff --check` 通过；冲突组件静态 UI 检查无命中 |

浏览器验收不是全 mock：仅在一次真实 POST 返回并已提交后由故障注入丢弃响应，重放仍由真实数据库回执处理。其余 API 直达独立 FastAPI。它不代表真实双设备、跨账号多标签页、生产代理或 Electron 验收。

后端测试仍有 Pydantic 等弃用警告，未将其说成零告警。浏览器测试最初有合成账号格式和异步完成等待的测试脚本问题，修正后五项通过；先前失败不作为产品缺陷结论。

主要测试/入口：

- `frontend/src/sync/{SyncEngine,syncSafety,syncProtocol}.test.ts`
- `frontend/scripts/selftest-sync.mjs`（要求 Vite、独立后端和显式合成写入授权）
- `backend/tests/test_{sync_protocol_api,offline_sync_protocol,schema_migration,transaction_ownership_architecture}.py`

在已启动且确认使用**一次性数据库**的本地 Vite/后端上执行真实浏览器验收：

```sh
cd frontend
MNEMOX_SYNC_E2E_ALLOW_SYNTHETIC_WRITES=1 \
MNEMOX_E2E_BASE_URL=http://127.0.0.1:5187 \
MNEMOX_E2E_ARTIFACT_DIR=/tmp/mnemox-sync-e2e \
node scripts/selftest-sync.mjs
```

脚本拒绝非 loopback URL，但 loopback 代理仍可能指向真实后端，必须由运行者确认数据库隔离；脚本会创建合成账号，不要在常用工作库上运行。

本机日志：`/tmp/mnemox-phase2-frontend-final.log`、`/tmp/mnemox-phase2-protocol-schema-final.log`、`/tmp/mnemox-phase2-wide-backend.log`、`/tmp/mnemox-phase2-migration-final.log`、`/tmp/mnemox-phase2-real-e2e.log`、`/tmp/mnemox-phase2-build.log`。冲突对话框桌面/390px 截图：`/tmp/mnemox-phase2-sync-browser/`。这些是本机临时证据，不是仓库或 CI 永久制品。

## 4. 下一阶段

知识抽取外部调用移出长事务、Unit 检查点、来源版本和租约 fencing、有界取消/停机、按执行日原子预算预留及调用账本尚未实现；文件解析进程资源隔离另行实施。同步回执治理、分页/多标签页、真实 PostgreSQL/部署/Electron 的验收继续单列。本批完成不表示全部 P0/P1 已关闭。

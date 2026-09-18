# P0/P1 稳定化第三阶段：知识抽取事务与预算

日期：2026-09-12。状态：**工作区实现和本地验收完成；未提交、合入或部署**。这是工程审查后的第三批稳定化，不是产品路线图的 V2 Stage 3。延续[第二阶段](2026-09-12_p0-p1-hardening-phase2.md)，没有访问真实业务库、真实附件或供应商密钥；原有前端工作区修改保留。

## 1. 事务与恢复

- `process_claimed_extraction_run` 改为接收独立 session factory 和领取时的 `lease_token`，拒绝借用调用方 `AsyncSession`。`ExtractionRuntime._transaction` 是明确登记的独立检查点提交入口；预算服务仍只 flush。
- 准备/加载、调用预留、调用结算、每个 Unit 的 Claim/Evidence/解析候选/outbox/进度、run 终态分别使用短事务。模型等待和 grounding 均在脱离事务的 Unit 快照上执行，模型等待期间没有借出的 SQL 连接，也不持有来源或 run 行锁。
- 可选语义解析先在事务外预取向量候选，检查点内只访问只读缓存；仍回 SQL 检查候选归属和状态。保留 exact/alias/既有人工映射的 SQL 短路和 mention 数量上限，避免预取增加不必要的模型调用。该功能的 embedding 预算不属于本批 LLM 账本，不能据此开放其生产门禁。
- 每个成功 Unit 的内容和 `processed_unit_ids` 同事务持久化。后续失败/停机不撤销先前 Unit；重试跳过已完成 Unit，只有明确 force 才重置处理进度，**不重置已消费预算**。
- 自动抽取仍需 Evidence grounding，自动 Claim 保持待审核，不改变人工确认和规范 SQL 权威边界。

## 2. 租约、来源与取消

- 每次领取产生新 UUID `lease_token`，并设置独立 `lease_expires_at`；不再把可重置的 `attempt_count` 当 fencing token。
- 检查点先锁 Source，再以运行状态、worker、token、未过期租约做条件更新，并复核当前、自有、有效的 SourceRevision。Unit 正文和 hash 也必须与加载快照一致。失效结果不能落库，旧 worker 不能覆盖新 owner 的失败/终态。
- 模型等待期间按不超过一秒及租约三分之一的间隔续租/观察取消。来源替换/删除会清空所有租约字段；旧结果不能复活已删除内容。
- 停机先停止领取并发出取消，再在配置宽限内等待。对拒绝协作取消的 awaitable 不无限等待，保留后台任务引用，阻止该 worker 继续发起调用/重复启动消费循环。已完成 Unit 保留，未完成运行可安全重新排队。
- 这是**应用层有界等待和拒绝迟到写入**，不是远端请求撤销保证，也不是杀死任意线程/第三方 SDK 的承诺。事件循环被同步代码阻塞、进程硬退出、底层线程仍运行等情况仍需进程级监督。

## 3. 持久调用与执行日预算

新增 `knowledge_extraction_daily_budgets` 和 `knowledge_extraction_calls`：

- 日桶以 `(user_id, execution_day)` 唯一；执行日是调用预留时的 UTC 日，不是 run 创建日或响应到达日。
- 每次 provider 尝试先提交独立 UUID 预留。Run 行锁串行化累计调用数/Token 限额，用户日桶 upsert 和条件加算仲裁跨 run/跨进程配额。只支持 SQLite/PostgreSQL，其他方言拒绝执行。
- 结构化调用失败后的普通 chat 降级必须再次预留。OpenAI extraction 实例禁用 SDK 重试；Gemini 非流式 extraction 每次请求设置 `attempts=1`，不支持该控制的 SDK 拒绝抽取。Claude 使用无自动重试的现有 HTTP 路径。普通聊天的重试策略不变，已有 OpenAI/Claude 出站防护保留。
- 预留采用消息/系统/schema 的 UTF-8 字节量、固定开销和输出上限，不再使用单独 `len(Unit)/4`。这仍是保守 Token 限额，不是供应商发票或美元硬上限。
- 失败、超时、取消、响应不确定都不退预留。取得 usage 后按 `max(预留, 已记账, 实报)` 向原日桶补差，已发生的超额如实保留并阻止后续超额预留。
- `unknown` 可被仍存活的迟到 provider 结果最终化一次；重复结算不能重复加算，最终化也不能退款、挪日或修改取消/失效的 run 结果。进程已经退出时无法自动取得迟到 usage，保留不确定收费，后续需供应商对账。
- `call_count` 是持久预留尝试数：进程可能在提交预留后、真正发送 HTTP 前退出。因此一笔预留最多覆盖一次受控 provider 尝试，不承诺每笔都有可证明的已发送 HTTP。`reserved/unknown` 明确反映该不确定性。
- 账本仅含关联 ID、租约、时间、状态、provider/model 名和白名单数值用量（input/output/total/configured cost），不保存 prompt、来源正文或模型输出。Unit 错误只保留异常类型或受控预算原因，避免 SDK/校验/SQL 异常把正文写进错误元数据。领域 Claim/Evidence 仍按现有规则保存。

## 4. 升级与运维门禁

迁移：`20260912_24`，上游 `20260912_23`。新增两个账本表及 run 的 `lease_token`、`lease_expires_at`、`budget_review_required`。SQLite lightweight 路径同步补齐结构和历史保护；历史审核回填不是吞掉错误的 best-effort 分支。

**部署顺序：备份 → 停止所有旧版抽取消费者并核对未确认调用 → 升级数据库和全部后端实例 → 核对历史账本 → 恢复允许的抽取。不得混跑新旧抽取 worker。**

- 升级前已有的所有 LLM run（包括 usage 为空的 queued/running 记录）标记 `budget_review_required`。空 usage 不能证明没有已发送但未记录的调用。
- 只要一个用户有未核对的历史记录，其所有新 LLM 预留都会暂停，不能用另建 run 绕过旧消耗。规则 extractor 不使用 LLM 额度，也不因此停用；可选 embedding 并非免费且有独立治理边界。
- 历史 usage、Unit 和正文原样保留，不猜测旧执行日，不自动补零、不自动发起付费调用。retry/force 不清审核标志或预算账本。
- 解除隔离必须先用真实调用/账单证据核对历史执行日、调用数及消耗，完成保守结转和审计。**不要直接清 usage、删账本、删 run 或修改审核标志来“恢复额度”**。专用历史补录/审核工具尚未实现，作为上线前独立任务保留。
- 生产使用账本后，不能照搬测试中的 downgrade 来回滚：降级会删除账本表。应停止消费者，按经过验证的备份/恢复方案处理，并重新核对未确认调用。
- `KNOWLEDGE_LLM_MAX_OUTPUT_TOKENS` 默认 `2048`，允许 `128..8192`；`KNOWLEDGE_EXTRACTION_SHUTDOWN_GRACE_SECONDS` 默认 `5`，允许 `>0..30` 秒。既有总开关、LLM opt-in、64 次/run、64,000 Token/run 和 256,000 Token/用户 UTC 日默认值未扩大。

## 5. 验证与尚未覆盖的范围

后端测试在排除 `.env`、真实数据和上传的 `/tmp` 源码副本中运行，使用 Python 3.10.12。模型和语义查询均为合成替身，不使用真实 API Key。

| 验证 | 结果与边界 |
| --- | --- |
| SQLite 故障注入与预算 | 包含在最终宽回归中：逐 Unit 提交/恢复、无借出连接、独立写入不被模型等待阻塞、同名 worker 新 token、续租、来源删除、拒绝取消、有限停机、降级独立计费、额度拒绝、失败不退款及迟到用量结算 |
| 真实 PostgreSQL 16 | **26 passed**；运行同一套 runtime/预算故障注入，另含两个独立 Python 进程竞争同一用户日桶。使用 loopback 一次性容器、独立 schema，无生产数据；模型仍为替身 |
| 合成旧 SQLite 升级 | Alembic 和 lightweight 两条路径都验证保留历史 usage/正文、标记未知 LLM、重复执行不清标志；包含在宽回归中 |
| 双数据库实际迁移 | SQLite 和真实 PostgreSQL 均从空库全链升级，再用合成旧 LLM 行验证 `23→24→23→24` 数据保护与 drift；最终复核唯一 head 为 `20260912_24`，两库均 `No new upgrade operations detected` |
| 兼容宽回归 | **24 模块，179 passed、12 subtests passed、97 warnings**；包含知识生命周期/解析/投影、预算/provider、schema/事务、前两批安全/同步、AI 和聊天。不是完整后端套件 |
| 静态与保留检查 | `git diff --check` 通过；与第三阶段初始副本比较的 170 个前端文件无变化。本阶段未改前端，未重跑前端构建或 Electron |

组合验证曾暴露两个 chat 日志断言失败。实际探针确认原因是嵌入式 Alembic 默认禁用已有应用 logger，而非 RAG 开关；现使用 `disable_existing_loggers=False` 并加入回归，最新 179 项组合已包含该修复。另补齐了语义预取的 SQL 短路，避免已知身份增加模型调用。97 个告警主要为既有弃用警告，未宣称零告警或全量后端通过。

主要测试：

- `backend/tests/test_knowledge_extraction_runtime.py`
- `backend/tests/test_knowledge_extraction_budget.py`
- `backend/tests/test_extraction_provider_limits.py`
- `backend/tests/test_extraction_migration.py`
- `backend/tests/test_extraction_postgres.py`
- `backend/tests/test_schema_migration.py`、`test_transaction_ownership_architecture.py`

运行 PostgreSQL 专项必须先确认是一次性数据库，再显式提供 `MNEMOX_EXTRACTION_TEST_POSTGRES_URL`（loopback、数据库名前缀 `mnemox_phase3_`）和 `MNEMOX_EXTRACTION_TEST_ALLOW_SYNTHETIC_WRITES=1`。测试会创建/删除自己的独立 schema。URL 限制无法证明本地代理的数据库隔离，不要在工作库或生产库上运行。

独立待办仍包括：可选 embedding 查询/投影 SDK 的隐藏重试、独立预算和底层线程资源治理；历史账本补录；真实供应商 usage/账单、进程硬退出后的对账；正式生产升级；恶意文件解析进程隔离。此次未更改前端，也未重跑 Windows/Electron、真人数据或完整后端套件。第二阶段同步的回执/隐私/恢复/分页/多标签门禁继续单列。

本机临时证据：`/tmp/mnemox-phase3-final-wide.log`、`/tmp/mnemox-phase3-final-postgres.log`、`/tmp/mnemox-phase3-roundtrip.log`、`/tmp/mnemox-phase3-final-drift.log`、`/tmp/mnemox-phase3-resolution-final.log`、`/tmp/mnemox-phase3-logging-probe.log`、`/tmp/mnemox-phase3-logging-regression.log`。这些不是持久 CI 制品。

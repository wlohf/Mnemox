# 更新记录：画像投影与 Agent 工具事务边界

## 本周期目标

- 消除派生画像服务内部提交调用方事务的隐式副作用。
- 让快照查询保持纯读，为后续把更多投影接入统一 unit of work 建立可测试契约。

## 已完成

### 1. 服务层改为 flush-only

- `compute_and_save_profile` 仍负责聚合、upsert 和返回最新画像，但内部只执行 `flush`，不再 `commit`。
- 数据提交或回滚由请求、后台 worker或批处理入口决定；画像可与同事务领域变更一起原子提交或一起回滚。
- `get_or_compute_profile` 的过期刷新运行在 savepoint 中；刷新失败只回滚该派生步骤，不污染调用方外层事务。

### 2. 显式后台事务

- 番茄钟完成后的画像刷新继续使用独立 session，并显式 `commit`；异常时显式 `rollback` 后记录不影响主流程的告警。
- Profile API 和 Demo 导入原本已有调用方提交，继续保持入口拥有事务的语义。

### 3. 纯读学习快照

- 学习快照改为只调用 `get_profile`；没有画像时返回空对象，不会因 Agent、Coach 或周报读取上下文而创建 `user_profiles`。
- 明确画像刷新入口为 Profile API、显式刷新和番茄钟提交后的投影 worker。

### 4. Agent 只读工具不再提前提交

- `AgentManager.call_chat_tool` 查询后只 flush 审计日志，不再直接 commit 调用方会话。
- 独立 HTTP 工具调用仍由请求 unit of work 在成功返回时提交；AgentKernel 内的工具日志随 checkpoint 一起提交。
- 这避免多步 Kernel 的一次只读检索提前提交尚未形成完整 checkpoint 的其他状态。

## 数据与回滚

- 本模块不新增 schema 或迁移，不改画像计算公式。
- 新事务契约会让未显式提交的独立调用自然回滚；这是预期保护。所有已知独立 worker 调用点已补显式提交。
- 若回滚代码，只会恢复服务内部提交；无需数据回填。

## 验证结果

- 画像事务契约专项当前为 `5 passed`；本轮最终后端全量为 `491 passed, 10 skipped, 58 subtests passed`。
- 新增验证覆盖：服务零 commit、调用方回滚同时撤销笔记与画像、显式 commit 后可见、学习快照不创建缺失画像，以及只读 Agent 工具不提交待处理业务状态/审计日志。

## 已知限制 / 后续事项

- 资料和检索投影等历史服务仍有内部 commit；必须按调用链逐项迁移并验证独立 worker 语义，不能全局搜索替换。
- 下一模块统一 Phase 2 的 naive UTC 数据库存储与带 `Z` API 序列化，减少调度、租约和归因边界漂移。

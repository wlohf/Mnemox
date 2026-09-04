# 更新记录：检索长操作并发 Fencing

## 本周期目标

- 防止较早开始、较晚完成的向量索引覆盖较新的规范资料版本。
- 让整用户重建、清除与单资料 ingest/forget 共享同一可证明的顺序边界。

## 已完成

### 1. 同用户长操作串行化

- 新增可复用的长操作锁：所有运行时先取得进程内用户锁；PostgreSQL 再通过独立连接持有 session advisory lock，SQLite/桌面端使用进程内路径。
- 锁使用 namespace 与用户 ID 生成稳定 signed BIGINT key；不同用户和不同 namespace 不冲突，因此跨用户操作仍可并行。
- PostgreSQL 锁连接与业务 session 分离，业务流程可以在向量调用前后提交 durable saga checkpoint，而锁不会随事务提交释放。

### 2. 取消与连接池安全

- 正常退出显式执行 `pg_advisory_unlock`。
- 请求取消时屏蔽 unlock 任务的取消并等待释放完成；若解锁失败则使物理连接失效，禁止仍持有 session lock 的连接返回连接池。

### 3. 规范来源重载

- `ingest` 取得锁后按用户和资料 ID 使用 `populate_existing` 重读 `materials`；等待期间变旧的 ORM 对象不会继续建立索引。
- 若规范资料已删除，则返回已有 tombstone/生命周期状态或明确失败，不会把已删除资料重新写回向量库。
- `rebuild_user` 在一个用户锁内完成预清理和全部索引，并调用内部已锁定实现，避免嵌套锁；`forget` 和 `forget_user` 使用同一边界。

## 数据与兼容

- 不新增 schema 或迁移。
- 锁粒度当前为“同一用户的检索变更”，选择安全优先：同用户多资料不会并行索引，不同用户仍可并行。真实吞吐证明需要更细粒度时，才评估共享用户锁 + 独占资料锁。

## 验证结果

- 操作锁、检索生命周期、资料后端、概念图谱删除及事务架构组合为 `27 passed, 6 skipped`；跳过项需要真实 PostgreSQL 16 环境。
- 并发回归会暂停旧内容索引、提交新规范内容并启动第二次索引，验证第二次向量调用在锁释放前不会开始，最终 SQL 与向量均为新版本。
- PostgreSQL 候选门禁新增真实 `pg_try_advisory_lock` 验证：持有期间其他连接不可取得，退出后可取得并显式释放；本地 SQLite 不冒充该项已执行。

### 4. 全局配置切换收口

- 所有 ingest、retry、forget、rebuild 和用户清除操作先取得共享的全局 retrieval 配置锁，再取得既有用户锁；不同用户仍可并行。
- 保存全局 RAG 配置、热重载 RAG 服务和将不兼容 projection 标记为 stale 在同一个排他区间执行，因此配置指纹不会在长索引中途切换。
- PostgreSQL 使用同一个稳定 key 的 shared/exclusive session advisory lock；SQLite/桌面端使用写者优先的进程内异步读写锁。两种路径都沿用独立连接、显式 unlock、取消等待和 unlock 失败即失效连接的池安全规则。
- `mark_configuration_stale` 的直接调用也会取得排他锁，路由内已持锁时仅走显式内部路径，避免重入死锁。

## 后续事项

- PostgreSQL 候选 workflow 和生产池容量仍需实际执行新门禁。

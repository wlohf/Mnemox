# P0/P1 稳定化：第一阶段止损修复

日期：2026-09-12。状态：**工作区实现及本地回归完成，未提交、未部署，不代表全部 P0/P1 已完成。**

## 本次范围

按工程审查的推进顺序，先修复身份、安全边界和失败时的数据保留；不在同一批次引入同步服务端新协议或重写知识抽取事务。

### 1. 离线账号与请求隔离

- IndexedDB 在浏览器 origin 的基础上，按服务端用户 ID + 账号创建时间分库，覆盖 notes/goals/goalTasks/ankiCards/wrongQuestions/opQueue。创建时间区分数据库重建后复用的数字 ID。
- 登录确认且目标库打开后才发布已认证状态；退出立即停止同步、关闭旧库。关闭后的 Dexie 实例禁止自动重开。各异步适配器/本地操作捕获自己的数据库句柄，不能在 await 后转入新账号的库。
- 请求捕获会话代次和 AbortSignal；账号切换取消旧请求，即使传输忽略取消，也拒绝迟到响应。同步队列在重试、确认及拉取间核对运行代次；停止会唤醒退避等待。
- `X-Mnemox-User-Id` 表达请求启动时的预期账号，服务端核对认证用户，不匹配返回 `409 / SESSION_USER_MISMATCH`。该字段不是授权凭据；没有它的现有 API/CLI 客户端保持兼容。
- 同 origin 标签页通过不含凭据的 storage 通知停用旧会话；共享 Cookie 已变化但通知未到达时，后端预期账号校验兜底。
- Cookie 修改请求串行化，避免旧 logout 响应清掉新 login；并发 checkAuth 合并，迟到登录结果不能复活已退出会话。路由子树按账号重新挂载，避免复用旧账号的组件局部状态。

关键实现：`frontend/src/db/studyDb.ts`、`services/sessionScope.ts`、`services/apiClient.ts`、`stores/authStore.ts`、`sync/SyncEngine.ts` 及适配器。

### 2. AI 出站连接防护

- OpenAI-compatible、Claude 和模型目录查询统一受保护传输；禁止自动重定向和环境代理。
- 公网部署且 `ALLOW_PRIVATE_AI_ENDPOINTS=false` 时，只允许 HTTPS、公网解析结果；保存时校验之外，每次建立 TCP 连接重新解析全部地址，拒绝混合公网/私网结果，只连接已验证 IP。
- 固定的是 TCP 地址，原始 Host、TLS SNI、证书主机名验证保留。连接预算覆盖 DNS；验证也有超时；不会为了安全把 OpenAI 模型响应超时意外缩短到 HTTP 客户端默认的 5 秒。
- 兼容安装的 OpenAI SDK 使用 httpx 或 httpx2 的版本。私有连接池适配集中在 `outbound_transport.py`，不识别的 HTTP 栈默认拒绝，而不是回落到不受保护客户端。
- 本地开发/显式私网开关仍可使用本地模型。Gemini Provider 没有暴露自定义 base URL，本批未改动其官方 SDK 路径。

关键实现：`backend/app/utils/outbound_{url,transport}.py`、两个 Provider、`routers/ai_settings.py`。

### 3. 删除与故障恢复

- notes/ankiCards/wrongQuestions 删除只把明确的 404 当作远端已不存在；网络错误、403、5xx 保留本地记录/删除墓碑和待确认队列。goals/goalTasks 原有正确删除语义保持。
- 目标任务拉取失败不再使用不完整快照推断删除。
- 后端暂时不可用与设备断网分开处理；设备仍联网时允许下一轮同步探测后端恢复。拉取失败显式发布失败状态，不伪装成同步成功。

### 4. 密码与附件边界

- 注册校验 bcrypt 的 72 UTF-8 字节上限，超限返回明确的 400；验证超长输入和损坏哈希返回认证失败，不产生 500，也不截断密码。
- async 登录/注册中的 bcrypt 工作移到线程池。
- 历史 `images/{filename}` 无归属附件默认拒绝；`images/{user_id}/...` 保持用户隔离。
- 资料附件从文件名后缀匹配改为上传根目录内的规范路径精确匹配，阻止同名/后缀碰撞授权。

## 升级注意事项

1. **旧的 `StudyAssistantDB` 不删除、不自动归入当前账号。**它没有可信归属字段，必须保留备份，确认所有者后再设计显式恢复/导入流程。上线后已同步数据可从服务器重新拉取，旧库中仅本地保存的内容不会自动出现。
2. **旧平铺图片不自动迁移或删除。**需要先建立可验证的用户归属，再迁移目录和引用；禁止根据“当前登录的人”猜测归属。
3. AI 请求不再使用 `HTTP_PROXY` / `HTTPS_PROXY` 等环境代理。需直连或另行设计受控出站代理；公网发布保持私网端点开关关闭，并配置网络层 egress 防护。
4. 浏览器 IndexedDB 自身受 origin 约束；Electron 动态端口跨启动的存储稳定性不在本次修复范围内。其他持久化 store、跨标签页同账号并发同步和离线冷启动仍需独立验收，不能把本批称为完整离线协议。
5. 后端无新增 schema 迁移，未触碰真实数据库、上传文件或密钥；前端增加仅测试使用的 `fake-indexeddb@6.2.4`。

## 验证证据

在排除 `.env`、真实数据和依赖目录的独立源码快照运行后端测试；使用项目现有 Python 3.10 虚拟环境、`env -i`、合成 SECRET_KEY、独立 `MNEMOX_DATA_DIR`，没有真实模型或内网请求。

- 后端定向回归：**83 passed, 2 subtests passed**。覆盖新 auth/upload、连接固定、出站策略，以及既有授权、上传、Provider usage、模型发现、关键路径、聊天持久化和多用户隔离。
- 前端完整单元回归：**31 files / 122 tests passed**。
- `tsc --noEmit`、`npm run lint`、Vite production build、`git diff --check`：通过。
- Chromium UI 验收：番茄钟、计划、笔记、侧栏任务关联、Agent 草案确认，**5 项通过**。这是 mock API 驱动的现有验收，不是生产 Cookie/代理的真实全栈 E2E。
- 新测试真实执行 Dexie + fake IndexedDB 的分库/关闭/恢复、真实 SyncEngine 的旧会话晚到/删除故障/恢复；并使用真实 HTTP 连接池配合内存 TCP/TLS 流验证 IP 固定、Host/SNI/证书校验和 DNS 重绑定阻断。

新增测试：

- `frontend/src/db/studyDb.test.ts`
- `frontend/src/services/sessionScope.test.ts`
- `frontend/src/sync/syncSafety.test.ts`
- `frontend/src/stores/authStore.test.ts` 增量
- `backend/tests/test_auth_upload_regressions.py`
- `backend/tests/test_ai_outbound_transport_security.py`
- `backend/tests/test_ai_connection_pinning.py`

未在本批重跑全量后端、真实 PostgreSQL/Windows Electron、真实供应商服务和生产发布验收。

## 后续顺序与完成标准

1. **同步协议（下一批）**：已领取操作不可变、本地写入与入队原子化、创建请求端到端幂等、服务端版本/ETag 原子比较、RFC 3339 时间边界。必须覆盖同步中继续编辑/删除、响应丢失重试、双设备并发和不同时区。当前这些 P1 问题仍未修复；不能据此宣称同步“不丢、不重”。随后增加分页/增量游标与多标签页单消费者。
2. **后台任务治理**：模型调用移出长事务，按 Unit 提交且验证来源版本/租约，取消和停机有界；按实际执行日原子预留预算并记录调用账本。为崩溃、过期租约、取消与成本恢复补故障注入。文件解析的独立进程资源隔离另行实施。
3. **发布验收**：历史离线内容/附件的明确归属恢复、真实前后端 Cookie/代理/双账号 E2E、Windows 安装更新、生产安全配置和受控上线。

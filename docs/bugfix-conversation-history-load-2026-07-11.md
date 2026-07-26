# 历史对话加载失败：根因分析与修复

日期：2026-07-11  
范围：`frontend/src/stores/chatStore.ts`、`frontend/src/components/ConversationSidebar.tsx`、`frontend/src/components/Layout/ObsidianLayout.tsx`、`backend/app/routers/conversations.py`

## 1. 现象

用户点击历史对话，或打开 `/conversations/:id` 路由时，前端提示：

> 加载历史对话失败，请稍后重试

对话详情无法进入，当前会话可能被错误清空或切回错误状态。

## 2. 调用链

```
ConversationSidebar.handleOpenConversation
  → chatStore.setActiveConversation(id)
    → conversationApi.getConversation(id)
      → GET /api/conversations/{id}
        → conversations.get_conversation
```

路由直达：

```
ObsidianLayout route effect
  → setActiveConversation(routedConversationId)
```

启动恢复：

```
backendReady effect
  → restoreActiveConversation
    → reconcilePersistedSelections
    → setActiveConversation(persistedId)
```

## 3. 根因

### 3.1 并发竞态（主因）

`setActiveConversation` 会：

1. 立即把 `activeConversationId` 写成目标 ID
2. 异步请求详情
3. 成功后写入 messages；失败后回滚到 previousId

当以下请求并发时：

- 启动恢复：`restoreActiveConversation()`
- 路由加载：`setActiveConversation(routedConversationId)`
- 用户快速连点两个历史对话

较慢的旧请求后返回，会覆盖较新选择的 messages，或把 activeId 回滚错位。  
失败时前端只返回 `false`，错误详情被 `catch {}` 吞掉，UI 只能显示笼统文案。

### 3.2 分页列表误判“对话不存在”

`reconcilePersistedSelections` 原先用 `listConversations()` 的第一页结果（默认 limit=50）判断 localStorage 中的 `chat_activeConversationId` 是否有效。

若真实对话存在但不在第一页，会被误清：

```
activeConversationId = null
messages = []
```

随后恢复失败，用户看到“加载失败 / 空会话”。

### 3.3 后端 image_data 解析脆弱

`get_conversation` 原先：

```python
json.loads(m.image_data) if m.image_data else None
```

任一历史消息的 `image_data` 不是合法 JSON，整个详情接口 500，前端表现为“加载历史对话失败”。

### 3.4 次要环境因素

本地存在两套 SQLite 文件：

- `Mnemox/data/study.db`
- `Mnemox/backend/data/study.db`

`start.bat` 从 `backend/` 启动时使用 `DATABASE_URL=sqlite+aiosqlite:///./data/study.db` → `backend/data/study.db`。  
若某次从项目根目录启动，会落到另一库，localStorage 中的对话 ID 在当前库中 404。  
本次修复不改路径策略，但文档记录该坑。

## 4. 修复方案（最小改动）

### 4.1 前端：请求代次 token

`chatStore` 增加单调递增 `_activeConversationRequestId`：

- 每次 `setActiveConversation` 自增
- 异步返回后若 requestId 不是最新，丢弃结果并返回 `false`
- 避免旧请求覆盖新选择

### 4.2 前端：错误可观测

- 新增 `lastConversationError`
- 失败时写入可读错误（`getApiErrorMessage`）
- Sidebar / 路由 effect 优先展示该文案，而不是固定兜底句

### 4.3 前端：reconcile 改为详情校验

不再用“是否出现在列表第一页”判定失效：

- 对 persisted conversation 调用 `getConversation(id)`
- 仅当 **404** 时清空
- 网络错误 / 5xx 不误清，避免把临时故障当成删除

### 4.4 前端：消除启动双请求竞态

`ObsidianLayout` 中：

- 若 URL 已有 `routedConversationId`，启动 effect **只 reconcile，不 restore**
- 由 route effect 负责加载目标对话
- route effect 增加 cancelled 标志，避免卸载后误导航

### 4.5 后端：安全解析 image_data

新增 `_parse_message_image_data`：

- 非法 JSON → `null` + warning 日志
- 合法 list/string → 规范化返回
- **单条坏数据不拖垮整次历史加载**

## 5. 验证

### 前端

```bash
cd frontend
npm test -- --run src/stores/chatStore.test.ts
```

覆盖：

1. 404 清理 stale persisted conversation
2. 并发旧响应不覆盖新选择
3. 不在第一页的有效对话不会被误清
4. 失败时保留当前会话并记录 `lastConversationError`

### 后端

```bash
cd backend
pytest tests/test_conversation_detail.py -q
```

覆盖：非法 `image_data` 时详情仍 200，坏字段降级为 `null`。

### 手工

1. 启动后端 + 前端
2. 登录后点开历史对话
3. 快速连点两个不同历史会话
4. 刷新 `/conversations/{id}`
5. 确认无误报、内容与选中项一致

## 6. 影响面与兼容性

| 区域 | 影响 |
|------|------|
| 对话发送 / 流式 | 无改动 |
| 对话列表 / 新建 / 删除 | 无破坏 |
| Agent 写入消息 | 无改动 |
| 详情响应字段 | 仍含 `messages`；坏 image_data 由 crash 变为 `null` |

## 7. 后续建议（未做）

1. `DATABASE_URL` 改为基于 `resolve_runtime_path` 的绝对路径，消除双库
2. 列表 API 支持 cursor/分页完整加载，减少“第一页假象”
3. 登出时清理 `chat_activeConversationId`，避免跨账号串 ID
4. 后端对 404/500 返回统一 `detail.code`，前端可做更细粒度文案

## 8. 结论

根因不是单一“接口挂了”，而是：

1. 并发详情加载无代次保护  
2. 分页列表误判会话失效  
3. 错误被吞导致只能显示笼统文案  
4. 坏 `image_data` 可让详情接口整体失败  

本次修复针对上述点做了最小、可回归验证的改动，不影响其他主流程。

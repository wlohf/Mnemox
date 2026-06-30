# Mnemox 中期产品力提升实施方案

日期：2026-06-22  
状态：实施前规划文档  
适用范围：自学习 Coach、搜索结果质量优化、Token 预算精细化

## 1. 目标

这份文档用于后续按阶段推进 Mnemox 的中期产品力提升。目标不是简单增加功能，而是把现有 AI 学习助手从“能回答、能提醒、能检索”推进到“会根据用户反馈持续调整策略、能稳定使用外部信息、能在长对话和复杂上下文下保持质量”。

本阶段聚焦三件事：

1. **自学习 Coach**：记录用户对提醒和建议的反馈，统计哪些策略有效，并逐步调整干预频率、语气、时机和技能选择。
2. **搜索结果质量优化**：在现有 Tavily 与 DuckDuckGo / Bing fallback 基础上，加入去重、可信度排序、摘要缓存和 UI 引用展示优化。
3. **Token 预算精细化**：把当前偏粗的聊天历史裁剪，升级为对聊天历史、RAG 资料、记忆、网页搜索结果、Coach / Agent 摘要分别分配预算。

最终效果：

- Coach 越用越懂当前用户，但所有学习结果可查看、可纠正、可重置。
- 联网搜索结果更少重复、更可信、引用更清晰。
- 长对话、RAG、记忆和搜索同时开启时，模型上下文更稳定，不会被某一类资料挤爆。

## 2. 当前状态判断

### 2.1 Coach

当前项目已经具备 Coach 内核的第一层能力：

- `backend/app/models/coach.py` 已有 `CoachEvent`、`CoachNudge`、`CoachPreference`、`CoachWorkflow`。
- `backend/app/services/coach_policy_engine.py` 已能根据事件、学习快照、偏好和近期反馈决定是否提醒。
- `backend/app/services/coach_feedback_service.py` 已能把 nudge 反馈记录为 `UserMemory` 中的 `coach_feedback`。
- `backend/app/services/coach_skills/` 已有多个技能，例如低动力支持、最小下一步、复盘提醒、复习债务救援等。
- `frontend/src/services/coachApi.ts` 已有事件、评估、nudge、反馈、技能、偏好接口。

当前短板：

- 反馈仍偏“近期抑制”，没有独立的长期统计表。
- 没有按 skill、channel、event_type 统计接受率、完成率、打扰率。
- 没有稳定的 `coach_learning_profile`，用户无法看到 Coach 学到了什么。
- Policy 仍主要是规则匹配，缺少基于历史成效的权重调整。

结论：下一步应优先做 **Coach Skill Statistics + Coach Learning Profile**，而不是马上引入更重的 Agent 框架。

### 2.2 搜索

当前项目已经有较好的基础：

- `backend/app/services/web_search.py` 已支持 Tavily、DuckDuckGo HTML、Bing RSS、Bing HTML。
- `backend/app/models/search_settings.py` 已有 `ai_search_settings`。
- `backend/app/services/search_settings_service.py` 已支持用户级搜索设置、Tavily key 加密存储和默认值归一化。
- `backend/app/routers/ai_settings.py` 已有 `/api/ai-settings/search`、`/api/ai-settings/search/test`。
- `backend/app/routers/chat.py` 已支持多种搜索模式，并通过 SSE 返回 `web_search_results`。
- `frontend/src/components/AISettingsDrawer.tsx` 已有联网搜索设置、Tavily key、质量参数和测试按钮。

当前短板：

- 去重只按 URL 简单处理，没有 canonical URL、标题相似度、跨 provider 合并。
- 搜索结果没有明确的可信度分层。
- 搜索结果摘要没有缓存，重复问题会反复请求外部搜索。
- UI 侧引用展示还可以更清楚，例如来源标签、可信度、更新时间、引用编号和回答正文对应关系。
- 搜索结果注入上下文目前是固定数量和固定字符上限，尚未纳入统一 Token 预算。

结论：搜索下一步不是“再接一个搜索源”，而是做 **结果质量层**。

### 2.3 Token 预算

当前项目已有初步实现：

- `backend/app/models/ai_settings.py` 已有 `max_context_tokens`、`max_output_tokens`。
- 各 AI provider 基类和 OpenAI / Claude / Gemini provider 已支持输出 token 参数。
- `backend/app/routers/chat.py` 有 `_trim_messages_for_context_budget`，会按上下文上限裁剪消息历史。
- 前端 provider 配置卡片已有上下文和输出 Token 上限输入。

当前短板：

- 预算主要用于裁剪 `messages`，还没有把 system prompt、RAG、记忆、搜索结果、Coach brief 纳入同一个预算器。
- RAG 和搜索仍容易抢占上下文，导致聊天历史或长期记忆被挤掉。
- 缺少每次请求的预算使用日志，难以排查“为什么这次没引用某段资料”。
- 缺少按内容来源的截断策略，例如搜索结果应该按可信度和相关度保留，而不是简单前 N 条。

结论：下一步应新增 `context_budget_service`，让不同上下文来源进入同一套预算分配和裁剪流程。

## 3. 产品原则

1. **显性学习，不偷偷改变**  
   Coach 可以学习用户偏好，但学习结果必须能在 UI 中查看、编辑、忽略、锁定、重置。

2. **确定性策略优先，LLM 只做辅助**  
   是否打扰用户、是否越过确认边界、是否写入数据，必须由确定性规则控制。LLM 可用于生成措辞、总结趋势、提出候选策略，但不能直接绕过用户设置。

3. **搜索来源可追溯**  
   回答中使用网页信息时，必须能追溯到 URL、标题、来源 provider、检索时间。搜索失败时不能假装已联网。

4. **预算可解释**  
   当内容被裁剪时，系统应该能在 debug 日志或开发接口里说明：聊天历史用了多少、RAG 用了多少、记忆用了多少、搜索用了多少。

5. **先做小闭环，再做复杂 Agent**  
   先完成反馈统计、策略调整、UI 可控，再考虑 LangGraph / Agents SDK 一类框架。

## 4. 总体架构

```text
用户行为 / 学习数据 / 聊天信号 / 番茄钟 / 复习债务
        |
        v
Coach Event / Learning Snapshot / Memory / RAG / Search
        |
        +------------------+
        | Context Budget   |
        | 统一上下文预算    |
        +------------------+
        |
        +------------------+        +---------------------+
        | Coach Policy     | <----> | Coach Learning      |
        | 确定性策略边界    |        | stats + profile     |
        +------------------+        +---------------------+
        |
        v
Nudge / Chat Inline / Agent Panel / Desktop Notification
        |
        v
用户反馈：helpful / accepted / completed / snoozed / dismissed / too_disruptive ...
        |
        v
统计更新 -> 学习画像更新 -> 下次策略调整
```

## 5. 自学习 Coach 实施方案

### 5.1 要学习什么

Coach 不应该只记住“用户喜欢短一点”这种静态偏好，而要持续学习四类策略信息：

1. **技能有效性**
   - 哪些 skill 被接受、完成、标记有帮助。
   - 哪些 skill 经常被延后、忽略、标记打扰。

2. **干预通道**
   - `chat_inline` 是否更适合情绪和困惑场景。
   - `agent_panel` 是否更适合低优先级建议。
   - `desktop_notification` 是否经常被认为打扰。

3. **时机**
   - 用户在哪些时间段更容易接受提醒。
   - 连续几次忽略后需要冷却多久。
   - 番茄钟完成后、任务逾期后、复习债务升高后，哪种提醒更有效。

4. **语气和行动粒度**
   - 用户更喜欢一句最小下一步、完整计划、情绪支持、复盘追问，还是直接跳转到任务。
   - 建议是否太难、太简单、太长、太频繁。

### 5.2 新增数据模型

#### 5.2.1 `coach_skill_stats`

用于承接长期统计，不再只依赖 `coach_feedback` 记忆。

```text
coach_skill_stats
  id integer primary key
  user_id integer not null indexed
  skill_id string not null indexed
  channel string not null default ''
  event_type string not null default ''
  shown_count integer not null default 0
  accepted_count integer not null default 0
  completed_count integer not null default 0
  helpful_count integer not null default 0
  snoozed_count integer not null default 0
  dismissed_count integer not null default 0
  too_disruptive_count integer not null default 0
  too_hard_count integer not null default 0
  too_easy_count integer not null default 0
  irrelevant_count integer not null default 0
  not_my_style_count integer not null default 0
  recent_score float not null default 0
  lifetime_score float not null default 0
  last_shown_at datetime nullable
  last_positive_at datetime nullable
  last_negative_at datetime nullable
  updated_at datetime
```

建议唯一键：

```text
(user_id, skill_id, channel, event_type)
```

原因：同一个 skill 在不同通道和不同事件下表现可能完全不同。例如 `review_debt_rescue` 在桌面通知里可能打扰，但在 Agent 面板里可能有价值。

#### 5.2.2 `coach_learning_profiles`

用于保存可解释的学习画像。

```text
coach_learning_profiles
  user_id integer primary key
  profile_json json not null default {}
  generated_from_stats_at datetime nullable
  generated_from_feedback_at datetime nullable
  confidence float not null default 0
  version integer not null default 1
  updated_at datetime
```

建议 JSON 结构：

```json
{
  "preferred_channels": [
    {"value": "agent_panel", "confidence": 0.72, "reason": "低优先级建议接受率更高"}
  ],
  "avoid_channels": [
    {"value": "desktop_notification", "confidence": 0.81, "reason": "多次被标记 too_disruptive"}
  ],
  "effective_skills": [
    {"skill_id": "minimum_next_step", "confidence": 0.76, "reason": "过载场景接受率高"}
  ],
  "sensitive_skills": [
    {"skill_id": "review_debt_rescue", "confidence": 0.69, "reason": "复习债务提醒被延后较多"}
  ],
  "preferred_styles": [
    {"value": "short_next_step", "confidence": 0.74}
  ],
  "avoid_styles": [
    {"value": "long_plan", "confidence": 0.61}
  ],
  "best_times": [
    {"value": "20:00-22:00", "confidence": 0.58}
  ],
  "quiet_patterns": [
    {"value": "连续两次 dismiss 后冷却 24 小时", "confidence": 0.8}
  ],
  "locked_items": [],
  "ignored_items": []
}
```

### 5.3 服务层设计

新增服务：

```text
backend/app/services/coach_learning_service.py
```

职责：

- `record_skill_shown(db, user_id, nudge)`：nudge 展示时增加 shown_count。
- `record_skill_feedback(db, user_id, nudge, outcome)`：反馈时更新计数和 score。
- `get_skill_stats(db, user_id, skill_id=None)`：供 policy 和 UI 查询。
- `build_learning_profile(db, user_id)`：从统计和近期反馈生成 profile。
- `reset_learning_profile(db, user_id)`：用户重置 Coach 学习。
- `ignore_profile_item(db, user_id, path)`：用户忽略某条学习结果。
- `lock_profile_item(db, user_id, path)`：用户锁定某条学习结果，防止自动覆盖。

### 5.4 策略评分

当前 `evaluate_coach_policy` 可以保留为硬边界，新增一个软评分层：

```text
final_score =
  event_relevance_score
  + urgency_score
  + skill_success_score
  + channel_preference_score
  + style_preference_score
  - disruption_penalty
  - cooldown_penalty
  - daily_fatigue_penalty
```

硬边界永远优先：

- Coach disabled：直接不提醒。
- proactive disabled：不做主动提醒。
- quiet hours：不发桌面通知。
- max nudges per day：非高优先级不突破。
- disabled_skill_ids：永不触发对应技能。
- 需要写入或修改用户数据：必须确认。

建议初始分值：

```text
event_relevance_score: 0-40
urgency_score: 0-25
skill_success_score: -20 到 +20
channel_preference_score: -15 到 +15
style_preference_score: -10 到 +10
disruption_penalty: 0-35
cooldown_penalty: 0-30
daily_fatigue_penalty: 0-20
```

阈值：

```text
score >= 55: 可以生成 nudge
score 40-54: 只进入 Agent Panel，不主动弹出
score < 40: 不提醒，仅记录 reason
```

### 5.5 UI 设计

在设置或 Coach 面板增加“Coach 学习”区域：

- 学到了什么
  - 偏好通道
  - 避免通道
  - 有效技能
  - 敏感技能
  - 偏好语气
  - 最佳时机
- 每条展示：
  - 内容
  - 置信度
  - 来源：反馈统计 / 最近行为 / 明确设置
  - 操作：不准确、忽略、锁定、删除
- 全局操作：
  - 暂停自学习
  - 重置 Coach 学习
  - 导出学习画像用于排查

### 5.6 验收标准

1. 用户连续两次把 `review_debt_rescue` 标记为 `too_disruptive` 后，该 skill 在主动提醒中显著降权，优先转为 Agent Panel 或直接冷却。
2. 用户多次接受 `minimum_next_step` 后，过载场景优先选择该 skill。
3. 用户可以看到 Coach 学到的偏好，并能删除或锁定其中一条。
4. 重置 Coach 学习后，策略回到默认规则。
5. 显式偏好永远高于自动学习结果，例如关闭桌面通知后学习画像不能重新打开它。

## 6. 搜索结果质量优化方案

### 6.1 目标

现有搜索链路已经能用，下一步要提升“结果质量”和“引用体验”：

- 去除重复和近重复结果。
- 给来源可信度排序。
- 对搜索摘要做缓存。
- UI 展示更清楚的来源引用。
- 搜索上下文接入 Token 预算。

### 6.2 搜索处理流水线

建议把 `backend/app/services/web_search.py` 中的搜索结果处理拆成可测试的 pipeline：

```text
query
  -> provider search
  -> normalize result
  -> canonicalize URL
  -> dedupe
  -> source credibility scoring
  -> relevance scoring
  -> freshness scoring
  -> snippet cleanup
  -> budget-aware truncation
  -> cache write
  -> UI / prompt output
```

可以新增：

```text
backend/app/services/search_quality.py
backend/app/services/search_cache_service.py
```

### 6.3 去重规则

当前 `_dedupe_results` 只按 `url.rstrip("/")` 去重。建议升级为：

1. URL canonical key
   - scheme 小写。
   - host 小写。
   - 删除 `utm_*`、`fbclid`、`gclid` 等跟踪参数。
   - 删除 fragment。
   - 末尾 `/` 归一化。
   - 移动端域名归一，例如 `m.example.com` 视情况映射到 `example.com`。

2. 标题近重复
   - 标题标准化：小写、去标点、去站点后缀。
   - 标题相似度高于阈值时只保留可信度更高或 snippet 更完整的一条。

3. 内容近重复
   - snippet 前 200 字 hash。
   - 同 URL 不同参数但 snippet 接近时合并。

合并策略：

- Tavily 结果优先保留结构化 score。
- 官方来源优先。
- snippet 更长且更具体者优先。
- 保留 `merged_from_providers` 字段，方便调试。

### 6.4 来源可信度排序

新增 `source_credibility_score`，范围 0-1。

初始规则：

```text
0.95: 官方文档、政府、标准组织、学校机构
0.85: 知名技术文档、论文数据库、主流新闻机构
0.70: GitHub、产品博客、公司工程博客
0.55: 普通博客、论坛、问答站
0.35: SEO 聚合站、转载站、无明确作者来源
```

可以先用启发式 domain 分类：

```text
official_domains:
  docs.*、*.gov、*.edu、w3.org、ietf.org、python.org、react.dev、openai.com 等

lower_quality_patterns:
  /tag/、/category/、大量广告聚合、标题含 download free crack 等
```

最终排序建议：

```text
rank_score =
  0.45 * relevance_score
  + 0.30 * source_credibility_score
  + 0.15 * freshness_score
  + 0.10 * snippet_quality_score
```

如果 Tavily 提供 `score`，可作为 `relevance_score` 的主要来源；本地 fallback 没有 score 时用排序位置反推。

### 6.5 搜索摘要缓存

新增缓存表：

```text
web_search_cache
  id integer primary key
  user_id integer indexed
  query_hash string indexed
  normalized_query text
  mode string
  provider string
  results_json json/text
  summary text nullable
  source_count integer
  created_at datetime
  expires_at datetime
```

缓存策略：

- 默认 TTL：6 小时。
- 明显实时查询 TTL：15 分钟，例如“今天、最新、价格、天气、新闻、股价、版本发布”。
- 学术 / 概念查询 TTL：24 小时。
- Tavily 失败结果不缓存，避免短期故障污染体验。
- 本地 fallback 结果可短缓存 30-60 分钟。

缓存 key：

```text
sha256(normalized_query + mode + provider + search_depth + max_results)
```

### 6.6 UI 引用展示

当前 SSE 已返回 `web_search_results`。前端可进一步增强：

- 在回答上方或下方展示“本次联网来源”。
- 每条来源展示：
  - 编号 `[1]`
  - 标题
  - 域名
  - provider 标签：Tavily / DuckDuckGo / Bing / Hosted
  - 可信度标签：官方 / 高 / 中 / 低
  - 发布时间或检索时间
- 回答正文建议保留 URL 或 `[1]` 引用编号。
- 搜索失败时显示“联网搜索失败，已降级为普通回答”，避免用户误解。

### 6.7 验收标准

1. 同一 URL 带不同 tracking 参数时只展示一次。
2. Tavily 和 Bing 返回同一页面时能合并为一条，并保留 provider 来源。
3. 官方文档在排序中优先于低质量转载站。
4. 连续两次相同查询命中缓存，第二次不请求外部 provider。
5. 前端能清楚展示来源列表、provider 和引用编号。
6. 搜索结果注入 prompt 前会经过 Token 预算裁剪。

## 7. Token 预算精细化方案

### 7.1 目标

把“只裁剪聊天历史”升级为“统一上下文预算分配”。每次请求前，系统应先组装不同来源的候选上下文，再按预算分配和优先级裁剪。

需要预算的来源：

- system prompt / 模式 prompt
- 最新用户消息
- 聊天历史
- 对话摘要
- 长期记忆
- RAG 资料片段
- 手动选择的小资料全文
- 网页搜索结果
- Coach / Agent brief
- 图片说明或多模态提示

### 7.2 新增服务

```text
backend/app/services/context_budget_service.py
```

核心类型：

```python
class ContextItem:
    source: str              # chat_history / memory / rag / web_search / coach / system
    content: str
    priority: int            # 0-100
    token_estimate: int
    metadata: dict
    required: bool = False

class ContextBudget:
    max_context_tokens: int
    reserved_output_tokens: int
    system_reserved_tokens: int
    allocations: dict[str, int]
```

核心函数：

```python
estimate_tokens(text_or_message) -> int
allocate_context_budget(max_context_tokens, max_output_tokens, enabled_sources) -> ContextBudget
trim_context_items(items, budget) -> tuple[list[ContextItem], BudgetReport]
render_context_items(items) -> str
```

### 7.3 初始预算比例

默认分配：

```text
system + latest user message: required，先扣除
chat_history: 35%
RAG / notes / selected materials: 25%
web_search: 20%
memory / conversation summary: 12%
coach / agent brief: 8%
```

动态调整：

- 未开启 web search：web_search 预算转给 RAG 和 chat_history。
- 未选择资料且 RAG 无命中：RAG 预算转给 chat_history。
- Coach 未启用：Coach 预算转给 memory。
- 用户明确要求“结合资料”：RAG / selected materials 提升到 35%，chat_history 降到 25%。
- 用户明确要求“最新 / 搜索”：web_search 提升到 30%。

### 7.4 裁剪规则

不同来源不能用同一种裁剪方式：

1. **聊天历史**
   - 保留最近几轮。
   - 优先保留用户消息和紧邻 assistant 回答。
   - 旧消息先转为 conversation summary，而不是直接消失。

2. **RAG**
   - 按 score 排序。
   - 同一 material 避免占满全部预算，设置 per-material cap。
   - 保留标题、chunk score、material_id，方便解释。

3. **记忆**
   - 锁定记忆优先。
   - 与当前 topic 匹配的目标、薄弱点、风格优先。
   - 低 confidence 或 ignored 记忆不注入。

4. **网页搜索**
   - 按 rank_score 排序。
   - 每条保留标题、URL、可信度、短 snippet。
   - 低可信或重复来源先裁剪。

5. **Coach / Agent**
   - 只注入当前决策必要摘要。
   - 不注入长列表和完整私密历史。

### 7.5 Budget Report

每次请求生成调试报告，默认只写日志或开发环境返回，不直接暴露给普通用户。

```json
{
  "max_context_tokens": 32000,
  "estimated_total_before_trim": 48200,
  "estimated_total_after_trim": 29800,
  "sources": {
    "system": {"used": 2400, "dropped": 0},
    "chat_history": {"used": 9800, "dropped": 6200},
    "rag": {"used": 7600, "dropped": 4000},
    "web_search": {"used": 5200, "dropped": 3000},
    "memory": {"used": 2800, "dropped": 600},
    "coach": {"used": 900, "dropped": 0}
  },
  "dropped_items": [
    {"source": "web_search", "reason": "duplicate_url"},
    {"source": "rag", "reason": "lower_score_over_budget"}
  ]
}
```

### 7.6 接入步骤

第一步：不改变最终回答质量，只把现有上下文构建过程包装起来。

- `_build_system_prompt_with_rag` 输出 RAG candidate items，而不是直接拼长 prompt。
- `build_memory_prompt_fragment` 可以先保留旧接口，同时新增 candidate item 接口。
- `_build_external_web_search_prompt` 返回 search candidate items 和 UI results。
- `_trim_messages_for_context_budget` 迁移到 `context_budget_service`。

第二步：统一裁剪。

- 在 `chat_send` 中创建 provider 后读取 `max_context_tokens` 和 `max_output_tokens`。
- 构建所有 ContextItem。
- 调用 budget service。
- 渲染成 system prompt + messages。

第三步：加测试和日志。

### 7.7 验收标准

1. 同时开启 RAG、记忆、搜索时，总上下文估算不会超过 provider 的 `max_context_tokens`。
2. 搜索结果不会挤掉最新用户消息和必要 system prompt。
3. RAG 未命中时，预算自动转给聊天历史或记忆。
4. 高分 RAG chunk 和高可信搜索结果优先保留。
5. 测试能覆盖预算分配、裁剪原因、不同来源启停后的动态比例。

## 8. 分阶段实施计划

### Milestone 1：搜索质量层

建议优先级：高  
预计范围：后端为主，少量前端展示

交付：

- `search_quality.py`
- canonical URL 去重
- provider 合并
- 来源可信度评分
- 搜索结果排序
- 基础缓存表与服务
- 搜索结果 UI 标签增强

验收：

- 重复 URL 和近重复标题被合并。
- 官方来源排序更靠前。
- 相同查询可命中缓存。
- UI 能看到 provider、域名、引用编号。

### Milestone 2：统一 Context Budget

建议优先级：高  
预计范围：后端 chat / RAG / memory / search 入口

交付：

- `context_budget_service.py`
- ContextItem / BudgetReport
- chat history、RAG、memory、web search 的预算接入
- 日志或开发调试输出
- 单元测试

验收：

- 长对话 + RAG + 搜索不会超过预算。
- 预算报告能说明每类上下文保留和丢弃情况。
- 输出 token limit 继续正常传给 provider。

### Milestone 3：Coach Skill Statistics

建议优先级：高  
预计范围：Coach 后端为主

交付：

- `coach_skill_stats` 表和 migration
- `coach_learning_service.py`
- nudge shown / feedback -> stats 更新
- policy 读取 skill stats 并调整分数
- stats API

验收：

- 负反馈会降低同类 skill 后续触发概率。
- 正反馈会提高对应 skill 排名。
- 统计按 user 隔离。

### Milestone 4：Coach Learning Profile UI

建议优先级：中高  
预计范围：后端 API + 前端 Coach 设置面板

交付：

- `coach_learning_profiles` 表
- profile 生成 / 读取 / 重置 API
- UI 展示“Coach 学到了什么”
- 用户可忽略、锁定、删除单条学习结果

验收：

- 用户能看到学习画像。
- 修改画像会影响后续 policy。
- 重置后恢复默认行为。

### Milestone 5：Coach Reflection Job

建议优先级：中  
预计范围：定时任务或手动按钮

交付：

- 每日轻量统计刷新。
- 每周策略反思。
- 手动“刷新 Coach 学习”按钮。
- 结构化反思输出。

验收：

- Coach 能解释策略变化。
- 反思结果可回滚。
- 不会把原始私密笔记无限制喂给 LLM。

## 9. 测试计划

### 9.1 后端单元测试

新增或扩展：

- `backend/tests/test_web_search_service.py`
  - canonical URL 去重
  - Tavily + Bing 同源合并
  - 来源可信度排序
  - 缓存命中

- `backend/tests/test_search_settings.py`
  - 搜索设置不泄露 Tavily key
  - fallback 开关生效

- `backend/tests/test_context_budget_service.py`
  - 多来源预算分配
  - required item 不被删除
  - 动态预算转移
  - dropped reason 正确

- `backend/tests/test_coach_kernel.py`
  - stats 更新
  - policy 根据 stats 降权 / 加权
  - disabled_skill_ids 高于学习画像

- `backend/tests/test_motivation_personalization.py`
  - Coach 学习画像不影响非 Coach 激励逻辑，除非明确接入。

### 9.2 前端测试

新增或扩展：

- `frontend/src/services/coachApi.test.ts`
  - learning profile API 类型。

- `frontend/src/components/AISettingsDrawer` 相关测试
  - 搜索设置展示 provider、fallback、测试结果。

- Coach 设置面板测试
  - 展示学习画像。
  - reset / ignore / lock 操作。

### 9.3 手工验收场景

1. 无 Tavily key，开启联网搜索，能通过 DuckDuckGo / Bing fallback 返回来源。
2. 配置 Tavily key，搜索优先使用 Tavily。
3. Tavily 故障且 fallback 开启，自动降级。
4. 同一问题重复搜索，第二次命中缓存。
5. 用户连续 dismiss 某个 Coach skill，该 skill 不再频繁出现。
6. 用户重置 Coach 学习后，之前的自动降权失效。
7. 长对话中同时使用资料、记忆、搜索，回答仍能流式返回且不会报上下文过长。

## 10. 风险与处理

### 10.1 Coach 过度自适应

风险：少量反馈导致策略过度偏移。

处理：

- 使用置信度和最小样本数。
- 近期反馈影响短期冷却，长期画像需要更多样本。
- 自动学习永远不能覆盖显式设置。

### 10.2 搜索缓存过期导致信息陈旧

风险：实时问题使用了旧缓存。

处理：

- 查询分类，实时查询短 TTL。
- UI 展示检索时间。
- 回答中涉及“最新”时提示来源时间。

### 10.3 Token 估算不准

风险：字符估算和真实 tokenizer 有偏差。

处理：

- 初期保留 10%-15% safety margin。
- 后续可按 provider 引入 tokenizer。
- provider 报上下文过长时降级重试一次。

### 10.4 UI 控制复杂

风险：用户被太多设置吓到。

处理：

- 默认只展示简洁开关和摘要。
- 高级选项折叠。
- 使用预设：保守 / 平衡 / 长上下文 / 高质量搜索。

## 11. 推荐执行顺序

推荐按以下顺序实现：

1. **先做搜索质量层**  
   当前 Tavily 和 fallback 已经接好，做去重、排序、缓存能最快提升可感知质量。

2. **再做统一 Context Budget**  
   搜索质量提升后，必须避免搜索结果挤占 RAG、记忆和聊天历史。

3. **然后做 Coach Skill Statistics**  
   当前 Coach 已能记录反馈，补统计表和 policy scoring 是自然增量。

4. **最后做 Coach Learning Profile UI 和 Reflection**  
   先有真实统计，再做“Coach 学到了什么”的展示和周期反思。

不建议现在优先做：

- 大规模引入外部 Agent 框架。
- 让 LLM 自动改写 Coach policy。
- 在没有预算器前继续增加更多上下文来源。

## 12. 后续实施提示词

后续可以按下面的粒度发起实现任务：

```text
请按照 docs/midterm-product-power-plan-2026-06-22.md 的 Milestone 1，
实现搜索质量层：canonical URL 去重、来源可信度评分、结果排序、搜索缓存，
并补充后端测试。
```

```text
请按照 docs/midterm-product-power-plan-2026-06-22.md 的 Milestone 2，
实现 context_budget_service，把聊天历史、RAG、记忆和网页搜索结果纳入统一 Token 预算，
并补充预算报告和测试。
```

```text
请按照 docs/midterm-product-power-plan-2026-06-22.md 的 Milestone 3，
实现 Coach skill statistics，让用户反馈影响后续提醒频率、通道和 skill 排序。
```

```text
请按照 docs/midterm-product-power-plan-2026-06-22.md 的 Milestone 4，
实现 Coach Learning Profile UI，让用户能查看、忽略、锁定和重置 Coach 学到的偏好。
```

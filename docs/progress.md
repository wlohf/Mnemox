# Mnemox 项目进度

> 状态：维护中
>
> 更新日期：2026-07-26
>
> 当前版本：v1.3.0
> 当前阶段：Beta 稳定化与闭环验证（2026-07-26 起按新方向基线执行）

本文件记录可执行的项目状态。需求范围见 [需求文档](requirements.md)，工程实现见 [技术文档](technical.md)，按周变化记录见 `docs/updates/`。

## 1. 阶段判断

Mnemox 已完成核心学习工具、个性化学习闭环、Agent/Coach 和 Windows 桌面交付的第一轮实现。当前处于 **v1.3.0 的 Beta 稳定化与真实使用验证阶段**，重点是稳定性、安全边界、可解释性和闭环效果，而不是无边界扩展功能。

2026-07-26 完成方向基线梳理：产品哲学（知行差距 / 行为转化北极星）、知识层（概念图谱 + ContextStore 检索底座）、Agent 升级（自研 AgentKernel + 后台调度 + 自学习）与集成战略（Obsidian / FSRS / MCP）已固化为 [架构决策文档](superpowers/specs/2026-07-26-knowledge-layer-context-substrate-agent-architecture.md)（D1–D6），阶段顺序以 [路线图](roadmap.md) 为唯一权威来源，需求基线同步修订。

## 2. 当前交付快照

| 范畴 | 状态 |
| --- | --- |
| 版本与发布 | `v1.3.0` 已完成发布准备；应用、包、更新清单和发布脚本版本已同步。 |
| 后端能力 | 28 个路由模块、22 个模型模块、26 个服务模块，覆盖学习、AI、RAG、笔记上下文、Agent 与 Coach。 |
| 前端能力 | 17 个业务页面，主工作台、学习工具、洞察、设置和笔记上下文提示均已接入。 |
| 桌面端 | Electron 壳、Windows NSIS 构建、更新器和桌面提醒桥接已存在。 |
| 自动化测试 | 后端 30 个测试文件；前端 19 个测试文件；桌面端 7 个测试文件。 |

## 3. v1.3.0 已完成

- 将本地 `feature/voice-rag-motivation-agent` rebase、审查并合并到 `main`。
- 聊天按当前用户、关键词、标题、标签和更新时间检索相关笔记。
- 检索笔记经过 Prompt Safety 包装与 1,800 字符预算限制，异常时自动降级为正常聊天。
- 流式聊天通过 SSE 返回笔记上下文指示器，前端提示本轮参考的笔记标题。
- 新增笔记检索排序、跨用户隔离、不可信上下文、指示器裁剪和聊天流式事件测试。
- 新增 `scripts/seed_showcase_account.py`，用于本地 Demo 账号和学习闭环数据准备。
- 建立需求、技术、进度三份项目基线文档，并接入根 README 与文档导航。

## 4. 发布前验证

| 模块 | 结果 |
| --- | --- |
| 后端 | `152 passed, 53 subtests passed` |
| 前端测试 | `19 passed files, 60 passed tests` |
| 前端构建与 lint | `npm.cmd run build`、`npm.cmd run lint` 通过 |
| 桌面端 | `21 passed` |
| 文档与 Git | 文档已接入导航，`git diff --check` 通过 |
| 演示脚本 | `seed_showcase_account.py --help` 加载和参数解析通过 |

## 5. Git 与 GitHub 状态

- 原本未合并的笔记上下文功能已进入 `main`。
- v1.3.0 发布提交、tag 和 Windows 安装包将作为同一发布流程推送到 GitHub。
- `scripts/seed_showcase_account.py` 已纳入版本控制；它包含固定本地 Demo 凭据，只能用于本地演示，不能作为生产初始化方式。

## 6. 下一阶段工作

阶段顺序、完成标准与冻结清单以 [路线图](roadmap.md) 为唯一权威来源，此处仅保留执行快照：

| 轨道 | 主题 | 状态（2026-07-26 实施轮） |
| --- | --- | --- |
| 立即（小胜利） | 自引激励收尾（接入低动力 Coach 技能 + 防疲劳 + 反馈）、FSRS 替换 SM-2 调度 | ✅ 完成 |
| Phase 0 | Beta 稳定化：授权审计、注入防护、RAG 可见化、关键路径冒烟、仓库卫生 | ✅ 主体完成（1 HIGH + 5 MEDIUM 越权修复、10 处注入包装、冒烟测试、快照清理；RAG 可见化核查确认已于 v1.2.0 落地） |
| Phase 1 | 知识层：OpenViking spike、ContextStore、概念图谱 MVP、Obsidian 同步、联想引擎、概念级掌握度 | 🔶 后端完成；spike 关 1 不通过已裁决走保底；概念级掌握度前端 UI 待做 |
| Phase 2 | Agent 升级：AgentKernel 循环、后台调度器、干预效果自学习、知识巩固与周报 | 未开始 |
| Phase 3 | 生态：MCP Server、语音、AnkiConnect 评估、一键 Demo、发布自动化 | 未开始 |

2026-07-26 实施轮验证：后端全量回归通过（含新增 FSRS、自引激励、授权加固、注入边界、冒烟、概念图谱、ContextStore、联想引擎、vault 同步共 8 个新测试文件）。冒烟测试额外发现并修复了上传文件相对路径解析不对称 bug（data/data 双重目录）。

原 P1"闭环效果优化"中的 token 预算分层由 ContextStore 承接（决策文档 D3），Coach 效果评估并入 Phase 2 自学习；搜索质量与离线冲突处理作为持续项随相关阶段推进。

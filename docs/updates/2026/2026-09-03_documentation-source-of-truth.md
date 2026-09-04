# 文档来源唯一性治理

## 本次目标

- 让根目录 `README.md` 保持耐久的项目总览，不再复制容易变化的 Phase/Stage 状态。
- 明确文档导航、当前阶段状态和当前实现各自的唯一权威来源。
- 修正根 README 中已经落后于仓库基线的 Mnemox V2 描述。

## 来源规则

- `docs/README.md` 是文档入口、分类和导航结构的权威来源。
- `docs/roadmap.md` 是当前 Phase/Stage 状态、执行顺序、完成标准和冻结清单的权威来源。
- `docs/technical.md` 是当前代码实现、运行边界和维护约定的权威来源。
- `docs/progress.md` 可以汇总发布版本、验证证据和已知限制，但不得与路线图并行维护另一套 Phase/Stage 状态。
- 根 `README.md` 只承担产品定位、耐久能力概览、快速开始和文档入口；阶段推进时不在根 README 同步状态表或检查清单。

## 本次修正

- 将首页的 Mnemox V2 描述改为耐久的 Claim 中心知识层概览，不绑定阶段编号。
- 删除“Stage 0～2 已完成、Entity Resolution 尚未开始”等已经失效的状态陈述。
- 删除根 README 中重复维护的“当前状态 / 接下来计划”长清单，阶段状态和执行顺序统一回到路线图。
- 将外部图 Shadow 的阶段编号条件改为能力和验收门槛条件，具体时点仍由路线图管理。
- 本次没有实现或启动 Stage 4，也没有修改产品代码、测试、配置、数据库或运行时行为。

## 涉及文件

- `README.md`
- `docs/README.md`
- `docs/updates/2026/2026-09-03_documentation-source-of-truth.md`

## 验证

- 检查根 README 不再包含旧的 Entity Resolution “尚未开始”表述。
- 检查根 README 不再维护 Mnemox V2 Stage 完成状态或另一份后续阶段清单。
- 检查文档入口明确链接到 `docs/README.md`、`docs/roadmap.md` 和 `docs/technical.md`。

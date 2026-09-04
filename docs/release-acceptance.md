# 正式发布验收

> 更新日期：2026-09-03
>
> 当前状态：候选验收门禁和本地 PostgreSQL 16 历史 dump 恢复升级演练已完成；尚未选择新候选版本、运行远程签名候选、创建 tag/GitHub Release、升级正式 PostgreSQL 或把当前开发基线发布为安装包。

本文定义“代码完成”到“正式发布”之间的硬门禁。发布候选失败时不得覆盖已有 tag 或 Release 资产，也不得跳过备份直接升级正式数据库。

## 1. 自动门禁

常规 CI 会执行 `python3 scripts/release_preflight.py`，检查后端、前端、桌面端、lockfile 和根环境示例中的版本一致。手动触发 `.github/workflows/release-candidate.yml` 后，还会：

1. 复用完整 CI，运行后端、前端、PostgreSQL 16、多 worker、浏览器和 Windows smoke 门禁。
2. 核对候选版本、`release-manifest/latest.json`、发布说明、下载 URL 和安装包文件名。
3. 拒绝让新提交复用已经指向其他提交的 tag。
4. 构建后端、前端和 Windows NSIS 安装包。
5. 核对安装包、blockmap、`latest.yml` 及安装包 SHA-512。
6. 默认要求有效的 Windows Authenticode 签名。
7. 静默安装到隔离目录，并核对 Electron 主程序、后端可执行文件和前端入口。
8. 只上传保留 14 天的候选工件，不创建 tag 或 GitHub Release。

仓库需配置 `WINDOWS_CSC_LINK` 与 `WINDOWS_CSC_KEY_PASSWORD` 才能通过默认的签名门禁。关闭签名校验只允许用于诊断，不得作为正式发布通过证据。

## 2. 候选发布顺序

1. 选择高于当前正式版的新语义版本；同步所有版本来源、发布说明和 release manifest。当前 `v1.3.0` 已属于既有正式版，不能用于当前开发提交。
2. 在干净且已提交的候选提交上手动运行 `Release candidate acceptance`，输入完全一致的版本号，并保持签名校验开启。
3. 下载候选工件，在真实 Windows 环境完成首次安装、启动、登录、关键学习路径、升级覆盖和卸载检查；CI 的静默安装布局检查不等于真实 Electron E2E。
4. 按 PostgreSQL 发布演练流程冻结写入、保留快照、恢复到一次性数据库、升级到代码 head，并核对 schema drift、稳定数据量、Vault、时态记忆、检索投影和 AgentRuntime 生命周期字段。
5. 验收通过后才在同一候选提交创建 `v<version>` tag。`scripts/publish_desktop_release.ps1` 会再次要求干净工作树、正确 tag、元数据和工件哈希全部一致，随后才允许修改 GitHub Release。
6. 发布后复核 Release 页面、下载链接、`latest.yml` 更新通道、安装包签名与生产健康状态，并保留回滚快照和上一个应用版本。

## 3. 停止条件

出现以下任一情况即停止发布：版本或 tag 不一致、工作树不干净、完整 CI 失败、签名无效、安装布局缺失、哈希不匹配、PostgreSQL 演练出现 drift 或数据量异常、真实 Electron 关键路径失败、没有可验证的数据库与应用回滚路径。

## 4. 当前尚未完成

- 尚未选择并同步 `v1.3.0` 之后的新候选版本。
- 新迁移 `20260830_16`、`20260901_17`、`20260901_18`、`20260902_19`、`20260903_20`、`20260903_21` 已在全新一次性 PostgreSQL 16 本地候选库通过空库升级、10 项门禁与 drift 检查；新增门禁覆盖 durable extraction run、知识 projection outbox 的真实 `SKIP LOCKED`、grounded pending Claim/Evidence、exact/alias 解析和 pending 语义候选。
- 已从旧迁移点创建 PostgreSQL 16 custom-format dump，恢复到独立一次性库后经正式 `run_migrations.py` 入口升级到 `20260903_21`；历史固定数据保留专项 `1 passed`，`alembic check` 无 drift。临时容器和纯测试数据已删除。该本地演练不替代发布窗口对正式快照、真实数据量和回滚路径的核验。
- 应用版本一致性 preflight 通过；带 `--require-clean` 的候选 preflight 按设计拒绝当前包含大量既存未提交改动的工作树。本地环境没有 PowerShell 和 Windows 签名凭据，因此不能在此生成可接受的签名候选。
- FastAPI 桌面静态入口的 CSP 已与 Nginx 策略收敛；真实 Chromium 加载 `/dashboard` 后无内联样式违规，打包静态/CSP 安全专项 `12 passed`。这只消除了本地发现的样式阻断，不能替代签名安装包上的真实 Electron E2E。
- 远程候选 workflow 尚未在干净、已提交且选择了新版本的候选提交上运行；正式数据库连接/发布窗口也未提供，因此远程候选与生产升级保持未执行。
- 签名后的 Windows 候选、真实 Electron 安装/升级/卸载 E2E 尚未执行。
- 正式数据库冻结、快照、显式升级和发布后核对尚未执行。
- 新 tag、GitHub Release、公开安装资产和更新清单尚未创建。

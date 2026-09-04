# 安全运行说明

这份说明记录 Mnemox 当前上线边界与依赖例外，部署时应与
[公网部署说明](deployment.md) 一起使用。

## 已启用的默认保护

- 浏览器会话使用 `HttpOnly`、`SameSite=Lax` Cookie；JWT 不再写入
  `localStorage` 或 URL 查询参数。退出登录会使该账户所有现有 JWT 失效。
- 公网部署经 Caddy、前端 Nginx 到后端，后端本身不暴露端口；只有该固定
  两跳代理链可提供真实客户端 IP 用于限流。
- 用户配置的 AI 与 RAG Embedding 地址在公网模式仅可使用 HTTPS，且 DNS
  解析结果必须全部是公网 IP；请求不跟随重定向。
- RAG Embedding 是服务器全局配置。公网环境中只有
  `RAG_SETTINGS_ADMIN_USERNAMES` 明确列出的账号可以在 UI 修改或测试它；未
  配置该变量时，UI 修改默认关闭，仍可通过部署环境变量配置。
- 图片会校验真实格式与像素上限；资料会校验格式、DOCX 解压体积与解析
  时间/文本长度。上传内容仍应由部署层接入病毒扫描服务后再用于高合规场景。
- 静态站点与 API 都发送拒绝嵌入、禁止 MIME 嗅探、严格来源策略和 CSP 等
  响应头；公网 HTTPS 响应另发送 HSTS。
- Electron 仅允许其本地 UI 导航与调用 IPC；更新安装只由
  `electron-updater` 的已签名发布链负责，渲染页面不能下载或运行任意安装包。

## ChromaDB 依赖例外

截至 2026-08-27，`pip-audit` 对当前最新 ChromaDB 仍报告
`PYSEC-2026-311`、`CVE-2026-45830`、`CVE-2026-45831` 和
`CVE-2026-45833`，没有可升级到的修复版本。它们影响 Chroma 的服务器/API
攻击面；Mnemox 仅使用进程内的 `chromadb.PersistentClient`，不启动 Chroma
服务、不暴露 Chroma 端口，也不接收外部 Chroma API 请求。

CI 会仅忽略这四个已记录的、当前不可修复的条目，其他 Python 依赖漏洞仍会
阻断合并。若将来改为远程 Chroma、开放 Chroma 端口，或上游发布修复版本，必须
先重新评估并移除该例外。

## 部署检查

- 生产环境必须替换 `SECRET_KEY`、数据库密码和 AI 密钥；密钥不要提交进仓库。
- 后端只能位于私有 Docker 网络；不要给它添加宿主机 `ports` 映射。
- 生产环境保持 `ALLOW_PRIVATE_AI_ENDPOINTS=false`。若确有内网模型服务，需
  在独立、受控的私有部署中显式启用，并确保该服务本身有访问控制。
- 若要在公网 UI 管理 RAG Embedding，设置
  `RAG_SETTINGS_ADMIN_USERNAMES=你的管理员用户名`；不要把该权限授予普通
  学习账号。
- 上传高风险或受监管材料前，在反向代理或独立扫描容器中配置杀毒扫描。

# 公网部署：Caddy + Docker Compose

本文记录当前 Mnemox 的单机公网部署方式。它以 Caddy 统一处理 HTTPS，应用本身只加入 Caddy 已使用的 Docker `web` 网络；PostgreSQL、后端和持久化卷都不发布到公网。

## 前提

- 域名 A/AAAA 记录已经指向服务器，并已开放 80/443。
- Caddy 容器（或主机 Caddy）已接入名为 `web` 的 Docker 网络。
- 根目录 `.env` 只保存在服务器上，至少设置强随机的 `DB_PASSWORD`、`SECRET_KEY` 和 `AI_KEY_ENCRYPTION_SECRET`；不要提交该文件。

首次在该服务器使用时，确认网络存在：

```bash
docker network inspect web >/dev/null 2>&1 || docker network create web
```

## Caddy 站点

在 Caddyfile 增加下面站点，并把域名替换成实际公网域名：

```caddyfile
example.com {
    encode zstd gzip
    request_body {
        # 200 MB 文件加上 multipart 边界的缓冲。
        max_size 205MB
    }
    reverse_proxy mnemox-frontend:80 {
        transport http {
            read_timeout 360s
            write_timeout 360s
        }
    }
}
```

验证并热加载 Caddy 配置。若 Caddy 以容器运行，可在它的容器内执行相同的 `caddy validate` 和 `caddy reload` 命令。Caddy 会自动申请及续期 HTTPS 证书。

## 启动和更新

公网环境使用专用 Compose 覆盖文件，它会：

- 将前端加入 `web` 网络并固定别名为 `mnemox-frontend`；
- 只接受对应 HTTPS 域名的跨域请求；
- 不发布应用、后端或数据库端口。

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
```

更新代码后重复同一命令即可。数据保存在 Docker 命名卷中；更新前应对 PostgreSQL 卷做可恢复备份。

## PostgreSQL 备份

每次发布前和定期运维时，使用仓库提供的只创建、不清理历史文件的脚本。备份目录必须是服务器上的绝对路径，且不应位于仓库中：

```bash
./scripts/backup_postgres.sh /srv/backups/mnemox
```

脚本会生成 PostgreSQL custom-format dump 和对应 SHA-256 校验文件，不打印任何密钥。恢复是破坏性操作，必须先在独立的非生产数据库验证 dump，再经明确发布决定执行；不要在日常更新命令中自动恢复或删除备份。

仓库还提供只用于**恢复演练**的验证脚本；它会在同一个 PostgreSQL 容器中创建一个名称以 `mnemox_restore_verify_` 开头的临时库，恢复该 dump、检查用户表、表数量和 Alembic 版本，然后自动删除临时库。它不会读取、修改或替换正式 `study_assistant` 数据库：

```bash
./scripts/verify_postgres_backup.sh /srv/backups/mnemox/mnemox-postgres-20260827T000000Z.dump
```

这只能证明备份可恢复，不能替代“把恢复数据切换为正式服务”的人工发布决定。

## 验收

```bash
curl -fsS https://example.com/ >/dev/null
curl -sS -o /dev/null -w '%{http_code}\n' https://example.com/api/auth/me
docker compose -f docker-compose.yml -f docker-compose.public.yml ps
docker exec mnemox-backend-1 alembic check
```

第二条在未登录时应返回 `401`，说明同域前端已能把 API 请求转发到后端；最后一条应显示没有未生成的迁移。随后使用真实账号完成注册、登录、番茄钟、复习和 Coach 回放验收。

## AI 能力

站点在没有 Provider Key 时仍能注册、记录学习行为和使用规则型 Coach 闭环；AI 聊天、生成和语义 RAG 需要在设置页配置自己的 Provider Key，或由运维通过服务器 `.env` 提供。不要把 Key 写入前端构建变量或 Caddyfile。

## 主动 Coach 的默认边界

服务器会启动低频的 AgentRuntime 扫描器，但它默认不会评估任何用户。用户必须先在设置中开启“定时评估”，才会检查“复习积压”这一个场景；生成的结果只会进入 Agent 面板，仍受每日上限、冷却、稍后提醒和“太打扰”反馈控制。它不会自动开始番茄钟、改动计划、创建任务或发送网页推送。

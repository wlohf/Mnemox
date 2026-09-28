# 旧 Docker 数据升级

旧版本可能将文件写在容器的 `/data`，而卷挂在 `/app/data`。**在执行 `up --build`、重建或删除旧容器前，先保存 `/data`。** PostgreSQL 卷不受本次路径调整影响，但仍应按常规备份数据库。

以下命令在项目目录执行；如部署使用额外 Compose 文件，请对所有 Compose 命令使用相同的 `-f` 参数。

```bash
legacy_backend=$(docker compose ps -aq backend)
test -n "$legacy_backend"
docker compose stop backend
runtime_backup="$PWD/runtime-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$runtime_backup"
docker cp "$legacy_backend:/data/." "$runtime_backup/"
```

确认备份中存在原来的上传文件、图片、Chroma 文件和配置；不要把 `docker cp` 失败当成空数据。如果旧容器已经删除，容器可写层中的文件无法通过本次代码修复找回，需使用既有备份。

新配置显式设置 `MNEMOX_DATA_DIR=/app/data`，保留原 uploads/chromadb 卷，并为根目录配置文件增加 runtime_data 卷。构建后先迁移，后启动：

```bash
docker compose build backend
docker compose run --rm --no-deps -v "$runtime_backup:/legacy:ro" --entrypoint python backend scripts/migrate_runtime_data.py --source /legacy
docker compose run --rm --no-deps -v "$runtime_backup:/legacy:ro" --entrypoint python backend scripts/migrate_runtime_data.py --source /legacy --apply
docker compose up -d backend
```

迁移工具拒绝覆盖内容不同的文件；发生冲突时保留备份并逐项确认。验证旧资料下载、旧图片、检索和容器重建后的数据，再处理旧备份。备份包含用户数据和可能的加密配置，不应加入 Git。

本次版本还隔离历史 AI 密钥：旧提供商记录不再自动发送已有密钥，用户需在 AI 设置重新填写自己的 Key。曾配置在服务器且被旧版本复制过的密钥应在供应商处撤销或轮换；修改本地代码不能撤销已泄露的凭证。后台无用户任务的服务器密钥与用户 BYOK 配置分开管理。

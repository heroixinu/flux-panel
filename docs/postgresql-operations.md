# PostgreSQL 安装、迁移与恢复

新版本默认使用 PostgreSQL 16，`gost-schema.sql` 是结构，`gost.sql` 是新安装初始数据。Compose 只在全新 `postgres_data` 卷上执行初始化；重启不会重建数据。首次登录后立即修改默认管理员密码。版本 1.5.0 的脚本和镜像必须全部发布后，安装器中的下载地址才能使用；本分支尚不代表已发布。

## 1Panel 外部 PostgreSQL：自动初始化

旧版初始化仅通过数据库镜像的 `/docker-entrypoint-initdb.d` 执行，不能初始化由 1Panel 管理的独立 PostgreSQL。
此分支的后端现已在 Spring Boot 启动时运行打包在 JAR 中的 `db/init/schema.sql` 与 `db/init/data.sql`：
幂等创建 8 张表，仅在用户表为空时创建初始管理员，仅在缺少 `app_name` 配置时添加该项。
不会清空业务表、覆盖已有管理员密码或重置主键序列。已存在的部分表也会保留。

启动初始化默认启用；当外部系统管理表结构时可配置 `DB_SQL_INIT_MODE=never` 关闭。
初始化失败（例如没有创建表权限、已有表结构不兼容）会直接导致后端启动失败，避免继续对外提供损坏的 API。

**1Panel 权限：** Flux 连接用户需要在目标数据库 `public` Schema 拥有 `USAGE, CREATE`，
否则 PostgreSQL 15/16 默认权限可能会拒绝建表。请以管理员身份连接 `flux` 数据库执行：

```sql
GRANT USAGE, CREATE ON SCHEMA public TO flux;
```

这里的 `flux` 只是示例，实际应使用 `DB_USER`。对其他角色已经创建的表，
还需另外授予业务表及序列的读写权限，或将所有权交给该用户。

**迁移顺序：** 启动自动初始化并不等于迁移旧 MySQL 数据。若要导入含管理员 ID 的历史数据库，
应先停掉后端、在空的 PostgreSQL 数据库执行 `gost-schema.sql` 并导入历史数据，
然后再启动新版后端；否则默认管理员可能占用 `app_user.id=1` 导致后续导入主键冲突。
不要将此自动初始化视为 1Panel 的 `pg_restore` 恢复功能。

## 现有 MySQL 用户

普通更新会拒绝 MySQL 安装，不会自动转换或删除 `mysql_data`。不要用旧版安装器更新、直接覆盖旧 Compose、将旧 MySQL 数据卷挂载给 PostgreSQL，或在迁移目标库执行 `gost.sql`。以下流程需要维护窗口。先阅读 [迁移评估](postgresql-default-migration-plan.md) 的数据对账、停机和回滚边界。

1. 停止相关转发或确认节点断连后的流量上报行为；隔离面板、API、定时任务及节点写入。备份原 MySQL（例如原版导出菜单）、`.env`、Compose 和旧镜像版本，并将备份恢复到隔离环境验证。保留原 MySQL 卷不变。
2. 创建独立 PostgreSQL 16 数据库，只执行 `gost-schema.sql`，不要运行种子文件。目标数据库必须为空，执行用户应拥有目标表和序列。运行工具的主机需要能够连接两个数据库；使用本机受限网络或加密隧道，不要为迁移将数据库端口暴露到公网。
3. 安装 Python 3.9+ 和依赖：`python3 -m venv .venv-migration`，然后执行 `.venv-migration/bin/pip install -r scripts/requirements-migration.txt`。设置 `MYSQL_HOST`、`MYSQL_PORT`（默认 3306）、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`、`PGHOST`、`PGPORT`（默认 5432）、`PGDATABASE`、`PGUSER`、`PGPASSWORD` 环境变量，再运行 `.venv-migration/bin/python scripts/migrate_mysql_to_postgresql.py`。密码使用安全方式注入，避免写入命令历史、仓库或日志。远程连接应通过加密隧道，PostgreSQL 也可用 `PGSSLMODE` 配置 TLS。

   使用项目默认 Docker 部署时，可在旧网络创建一次性 PostgreSQL 容器。先确认 `postgres_data` 卷不存在，然后准备权限为 600 的临时 `postgres-migration.env`，仅写入与原 `.env` 对应的 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`。运行 `docker volume create postgres_data`，再运行 `docker run -d --name gost-postgres-migration --network gost-network --env-file postgres-migration.env -v postgres_data:/var/lib/postgresql/data -v "$PWD/gost-schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro" postgres:16`。确认容器初始化成功后再迁移；旧 `mysql_data` 不可挂载到该容器。核对通过后停止并删除临时容器，保留 `postgres_data`，由新版 Compose 挂载同名卷；Compose 会跳过初始化和种子。切换前保存旧 Compose 和 `.env`，切换后删除临时凭据文件。
4. 工具要求源库恰好包含当前 8 张 InnoDB 表，列集合必须与目标一致；历史版本多列、缺列或非 InnoDB 会拒绝迁移，先在副本分析处理，禁止盲目删列。工具使用 MySQL 一致性只读快照，在单个 PostgreSQL 事务中复制并逐行对比全部字段，重置序列，并检查用户名大小写冲突。输出的每表行数仅在最后出现 `Migration committed` 后才表示提交成功。异常时表数据回滚，序列值可能已变化；重试会重新设置序列。不要在目标数据库并发写入。
5. 对照原库检查表行数、最大 ID、关键流量、账号、节点密钥、转发和隧道关系，并在隔离环境验证登录、查询、创建新记录和节点联通。用户名查询和配置名唯一性采用 PostgreSQL `lower()`，可保留常见大小写不敏感行为，但不保证与 MySQL `utf8mb4_unicode_ci` 在重音、Unicode、尾随空格上的比较完全一致；必须对现有账号和配置进行专项核对。
6. 将新版后端指向迁移后的数据库，保留原 `.env` 中的 JWT 密钥和业务端口；通过全部核对后才恢复节点和面板写入，并记录切换时间。隔离保存原 MySQL 卷和备份。

切换前可用旧 Compose 和旧卷回退。PostgreSQL 已接收写入后，旧库已落后；直接切回会丢失新写入和流量统计，需要先完成经验证的反向迁移，或明确接受数据损失。当前工具只支持 MySQL → PostgreSQL，不支持自动反向同步。

## PostgreSQL 备份与恢复

安装器菜单的导出功能使用 `pg_dump -Fc` 生成权限受限的 `.dump` 文件。恢复前先备份当前库；在独立的空 PostgreSQL 数据库执行，例如：

```bash
docker exec -i gost-postgres sh -c 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' < postgres_backup_YYYYMMDD_HHMMSS.dump
```

上例的 `POSTGRES_DB` 必须是已创建、没有业务表的恢复目标；生产恢复应先停止所有应用和节点写入，并核对数据库名。恢复完成后验证表、账号、配置和流量。不要把备份导入仍有数据的库；卸载默认保留数据库卷，但删除 `.env` 前应单独保存其中的 JWT 密钥和连接信息。

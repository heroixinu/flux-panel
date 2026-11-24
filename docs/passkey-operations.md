# Passkey 登录与运维

## 部署

Passkey 默认关闭，原有账号和密码登录方式保持不变。现有 SQLite / PostgreSQL 数据库会在默认的 SQL 自动初始化流程中新增 `passkey_credential` 与 `passkey_policy`，不重置任何用户。

部署前先备份数据库，同时升级前端与后端。新前端仅在旧后端缺少登录方式接口（401/404/明确资源不存在）时显示传统登录兼容入口，网络故障不自动降级。最终登录权限始终由后端判定。使用自定义 Compose 时在 backend.environment 增加：

```yaml
PASSKEY_ENABLED: ${PASSKEY_ENABLED:-false}
PASSKEY_ORIGIN: ${PASSKEY_ORIGIN:-}
PASSKEY_RECOVERY_PASSWORD_LOGIN: ${PASSKEY_RECOVERY_PASSWORD_LOGIN:-false}
```

在项目 .env 设置：

```dotenv
PASSKEY_ENABLED=true
PASSKEY_ORIGIN=https://panel.example.com
PASSKEY_RECOVERY_PASSWORD_LOGIN=false
```

```bash
docker compose pull
docker compose up -d
```

- `PASSKEY_ORIGIN` 必须为浏览器看到的准确 HTTPS Origin，包含非默认端口，不含路径、查询参数、末尾斜杠。仅本地开发允许 http://localhost[:port]。RP ID 为该 Origin 的主机名。不要填写内部 backend:6365 或反代的源站地址。反代可正常终止 TLS，后端不需要 TLS。
- 同一实例配置一个 Origin；域名变更会影响已有 Passkey，禁止在仅 Passkey 模式下直接切换到未经验证的新域名。
- 如果自行关闭了 SQL 初始化（DB_SQL_INIT_MODE=never），先使用 db/init 下对应引擎的幂等 SQL 创建新增表。
- 当前支持标准 WebAuthn 可发现凭证、UV=required、ES256/RS256，不限制平台或漫游认证器；实际兼容性受设备、浏览器、系统验证设置影响。内嵌 WebView 不保证支持，请使用外部 HTTPS 浏览器。旧移动客户端若只有账号密码入口，切换纯 Passkey 后无法登录。
- 使用专用域名、强密码及反向代理限流；建议管理员注册两个独立认证器或使用已同步并可恢复的 Passkey。

## 使用

1. 用原有账号密码登录；默认 admin_user 必须先修改用户名和密码。
2. 从桌面用户菜单或移动端个人中心进入「Passkey 与登录安全」。
3. 输入当前密码、设置凭证名称，添加 Passkey。设备将通过系统生物识别、PIN 或安全密钥完成验证。此处不采集生物识别数据。
4. 点「验证已绑定的 Passkey」或重新通过登录页登录，确认凭证可在无用户名、无密码的发现式认证中使用。
5. 管理员可在全部启用用户均拥有成功验证的 Passkey 后，重新验证本人身份并关闭全局账密登录。此时服务器拒绝旧版客户端的 /api/v1/user/login 调用；现有 JWT 会话按原有有效期继续，不等于撤销所有已签发 JWT。此策略针对面板登录，旧的 /api/v1/open_api/sub_store 只读流量订阅接口（不签发 JWT）及节点独立密钥鉴权不改变。
6. 纯 Passkey 模式禁止删除最后一枚已验证凭证。新增用户或启用未绑定凭证的用户，须先恢复账密登录，完成绑定验证后再关闭。正常恢复混合模式也需要管理员 Passkey 重新验证。

## 应急恢复

若丢失凭证、域名变更或不再使用 Passkey，不要删除数据库。通过服务器控制台设置：

```dotenv
PASSKEY_RECOVERY_PASSWORD_LOGIN=true
```

保留 JWT_SECRET，重建后端容器（docker compose up -d --force-recreate backend）。此模式临时恢复账密登录，不自动改写原持久化策略。如果原域名配置无效，可同时设置 PASSKEY_ENABLED=false 再恢复。使用管理员原有密码登录，在安全页面选择「永久恢复账密登录」，再次输入管理员密码确认；也可先绑定、验证新凭证。恢复持久策略后撤掉应急环境变量，重建容器。若无法使用原管理员密码，需要由拥有服务器管理权限的人员按既有密码恢复流程处理。

应急开关不应长期启用。纯 Passkey 持久化策略存在但 Passkey 未配置、当前 RP 无完整可用凭证覆盖时，后端拒绝正常启动，避免静默降级为密码登录。

## 数据迁移与回滚

- SQLite 在线备份包含所有凭证公钥和登录策略；恢复同一域名、端口、JWT_SECRET 与环境变量。备份不包含认证器私钥。
- 旧 MySQL/PG 备份缺少两张 Passkey 表是合法的，导入后使用默认密码登录策略。新版 PG 全量备份和在线 PG→SQLite 迁移保留两张表、用户关联、计数器、验证状态及策略；只存在其中一张安全表的备份拒绝导入。迁移时须停旧服务，防止签名计数器在切换过程中变化。
- 降级到不含 Passkey 的旧版本会失去 Passkey 登录与禁用密码的服务端限制。请先恢复混合登录、验证原有密码并备份，切勿直接用旧镜像覆盖纯 Passkey 部署。

## 自动测试

CI 验证 SQLite 和 PostgreSQL、JVM、Spring AOT、GraalVM Native Image；协议测试模拟真实 ES256/RS256 签名，检查错误 Origin、UV、签名、挑战替换及重放、用户绑定、策略限制、重启与备份恢复，并通过 Chromium 虚拟 CTAP2 认证器验证生产前端。Apple、Windows、Google 等实体设备仍需在部署域名上做人工验收。

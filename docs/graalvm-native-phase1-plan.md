# Flux Panel 一期：轻量化与 GraalVM Native Image

基线：codex/postgresql-support @ 8c26157b99b3ea1ee85838b81116763240b114fd。开发分支：codex/graalvm-native。不直接修改 main 或 PostgreSQL 稳定分支，不覆盖稳定镜像。

## 目标与范围

- Java 21、Spring Boot 3.5.x、Spring Framework 6.2、支持 AOT 的 MyBatis-Plus 3.5.x；依赖版本在 CI 验证后固定。
- PostgreSQL 16、已有数据库、SQL 自动初始化、JWT、密码修改、REST、GOST 节点通信与协议、现有业务功能保持兼容。
- 完全退役图形验证码：删除 Tianai Captcha、图片、字体及前端 UI；旧 /api/v1/captcha/check 返回 R.ok(0)，不访问数据库；旧 captchaId 兼容接收但不使用；旧配置不生效，不破坏已有数据。
- Passkey / WebAuthn、凭证存储与撤销、账户恢复留在二期。关闭验证码意味着公网登录需要代理层频率限制；不得把 Passkey 作为一期发布条件。
- 同一源码产生 JVM 和 Native 两种镜像；Linux AMD64/ARM64 分别在对应架构构建，不在 1GB 服务器编译。前端和 GOST 不做无关升级。

## 实施里程碑

| 里程碑 | 实施内容 | 通过条件 |
| --- | --- | --- |
| M1 验证码退役 | 后端删除组件及资源；前端直接登录；后台不能重新开启；旧数据兼容 | 已有 captcha_enabled=true 仍可正常密码登录，错误密码失败，旧状态接口返回 0，前端构建通过 |
| M2 JVM 迁移 | Boot 3.5、javax→jakarta（保留 Java SE javax.crypto/sql 等）；ORM、HTTP Client 5、JSON、AOP 检查；无用依赖清理 | PostgreSQL 集成测试、API JSON/GOST 协议回归、WebSocket、任务通过 |
| M3 轻量化 | JVM 默认 Xms32m/Xmx192m/SerialGC；Hikari 最大5、最小1；Tomcat max32/min2，max connections512；环境变量可覆盖 | 1GB 环境可启动；负载测试无连接池/线程饥饿 |
| M4 Native | Boot AOT Maven profile；MyBatis Mapper/实体/DTO、资源 SQL/XML、JSON 反射/代理、HTTP、JWT 配置检查 | native:compile 成功；启动后 SQL 初始化、REST 登录、节点交互、流量和任务测试通过 |
| M5 CI/CD | JVM 和 Native 分离；独立原生 CI、AMD64/ARM64；先仅实验标签/构建产物，避免发布稳定标签 | 两架构构建和 smoke test 通过，镜像可单独回滚 |
| M6 性能与发布 | 统一 workload、相同 PostgreSQL 和节点数量，测冷启动/空闲 RSS、cgroup 内存、峰值、24–72h 稳定性 | 目标 idle <=80 MiB、应用 ready <=3s（非保证）；无回归；手动批准正式发布 |

## 数据与回滚

不删除历史业务数据，不修改密码哈希、JWT secret、数据库 schema 或协议；旧验证码配置仅不再生效。PostgreSQL schema/data 脚本保持幂等。先备份数据库，原镜像标签固定；前端、后端版本共同发布；如回退，恢复原前后端并核对历史验证码配置。

## 验收和测试

- 空库、现有库、外部 1Panel PostgreSQL；重复初始化；错误密码及默认密码强制修改；旧前端 captcha check。
- CRUD/权限、分页、关联查询、节点 WebSocket 握手/重连、加密通信、流量上报/定时任务、日志、健康检查、SIGTERM。
- JVM 和 Native 运行同一 smoke suite；动态字段及 JSON 字段名不能变化。Native 镜像以实际测试为准，不以编译通过代替验收。
- 基线 142.75 MiB 容器内存，记录启动 ready、cgroup memory.current、docker stats、进程 RSS；对比优化 JVM 与 Native，包含峰值和长时间测试。

## 参考

- https://docs.spring.io/spring-boot/3.5/how-to/native-image/developing-your-first-application.html
- https://baomidou.com/guides/graalvm-native/

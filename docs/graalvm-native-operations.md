# Flux Panel Native Image 运维与验证

当前开发基线：codex/graalvm-native。生产 PostgreSQL 分支与既有稳定标签不变。CI 成功前不得将实验镜像视为正式可用。

## 镜像及切换

JVM: ghcr.io/heroixinu/flux-panel-backend:graalvm-jvm
Native: ghcr.io/heroixinu/flux-panel-backend:graalvm-native（AMD64 验证与发布成功后）
Frontend: ghcr.io/heroixinu/flux-panel-frontend:graalvm-jvm

Compose 使用 IMAGE_TAG=graalvm-jvm 选择前后端的 JVM 基线，BACKEND_IMAGE_TAG=graalvm-native 单独选择原生后端。1Panel 自建 Compose 可只替换 backend 镜像标签。保持 DB_HOST、DB_PORT、DB_NAME、DB_USER、DB_PASSWORD、JWT_SECRET、LOG_DIR、端口及日志挂载。先备份数据库，再重新创建后端容器。Native 不读取 JAVA_OPTS，默认堆为 Xms32m/Xmx192m；若需要覆盖，使用容器 command 参数，保留 -Duser.timezone=Asia/Shanghai。

回滚：将 BACKEND_IMAGE_TAG 改回匹配的已验证 JVM 标签，并重新创建 backend。若回退到改造前的 PostgreSQL 镜像，前端也应回退到同一版本；检查历史 captcha_enabled 是否曾开启。数据库 schema、密码哈希和 JWT 签名协议未变更。

## 本地构建

需要 JDK 21、Maven；Native 另需 Linux 同架构 GraalVM Community 21、GCC 与 zlib 开发库。建议仅在构建机或 GitHub Actions 上编译，不在 1GB 机器上编译。

```bash
cd springboot-backend
mvn -B -ntp package -DskipTests
# Native：按测试环境设置数据库连接、JWT_SECRET、LOG_DIR（AOT 阶段需要配置环境）
mvn -B -ntp -Pnative -DskipTests native:compile
mkdir -p native
cp target/flux-panel native/flux-panel
docker build -f Dockerfile.native -t flux-backend:native .
```

## CI 与验收

当前阶段仅构建、测试和发布 Linux AMD64；ARM64 暂停，源码和安装脚本的架构兼容逻辑保留。实验分支生成的镜像及 GOST release 资产不再包含 ARM64。稳定分支未修改。

docker-build.yml: MySQL→PG 迁移回归、JVM 集成测试、前端构建、GOST AMD64、JVM AMD64 镜像。
native-image.yml: JVM/Native × AMD64 的实际容器测试。两种产物使用同一套 smoke_backend.py，包括空库初始化、历史验证码关闭、密码及 JWT、普通用户权限限制、节点握手与重连、AES-GCM 双向命令、Mapper XML 查询、隧道批量更新、流量上报、统计/重置定时任务、重启数据保留。

Native 编译前先以 Spring AOT 模式在独立的 flux_aot 测试数据库运行同一套业务 smoke 测试；若 Mapper 装配或 AOT 运行失败，不进入 GraalVM 编译。MapperScan 显式引用 sqlSessionTemplate，避免 Native 运行时丢失隐式依赖注入。RuntimeHints 显式注册 SqlSessionTemplate.getSqlSessionFactory 的反射调用，覆盖 MyBatis-Plus 批量写入/更新路径。WebSocketServer 使用具体类型的组件和构造器注入，WebSocketConfig 注册已初始化的 handler 实例，避免接口返回类型隐藏资源注入点。

CI 共用标准 JVM Maven 缓存，并在 AOT 打包成功后立即保存 Native 依赖缓存，不受后续容器测试失败影响。仅在 Central 临时限流或网络故障时切换官方 Central 备用地址及 Google Central 镜像，设置有限网络超时；不跳过编译或运行时测试。

所有 smoke 检查只应在隔离的 PostgreSQL 测试库运行。CI 容器统一 512MiB 内存、2 CPU、不使用 swap；报告包含冷启动到 HTTP ready 时间、重启 ready、空闲 cgroup memory.current、进程 RSS、负载后与峰值内存。测试报告是 GitHub Actions artifact，不应把构建成功或估算值当作实测。

目标：1GB 实际部署中 Native 空闲内存低于 80MiB、ready 低于 3 秒为优化目标而非承诺；以生产机器同负载的 cgroup 和 docker stats 为最终判断。持续运行 24–72 小时、真实 GOST 节点、网络异常及长时间内存增长是上线前人工验收，不可能用短 CI 替代。

## 安全边界

图形验证码退役且后台不可启用；Passkey / WebAuthn 留待二期。公网登录应启用反向代理的请求频率限制、HTTPS、强随机密码、默认密码修改。当前为兼容已有数据保留旧密码哈希方案；Passkey 二期同时规划密码哈希升级与凭证恢复机制。

Spring Native 的 bean 集合在 AOT 构建时确定；不要依赖运行时切换 Spring profile 或影响 bean 是否存在的配置属性。数据库地址、密码、JWT_SECRET 等普通运行时参数仍使用环境变量；SQL 初始化相关开关须用目标镜像验证。

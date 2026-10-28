# M1X 测试环境部署

本机菜单由 `python3 scripts/configure-m1x-test.py` 写入 `config/projects.local.yaml`，使用现有 ConfigStore 的版本校验、备份和原子保存；私有配置不入库。可重复执行，不改动现有生产目标和其他项目。

| deploySys 入口 | 操作 | 目标 |
|---|---|---|
| M1X → M1X API 测试环境 → test | 发布、重启、状态检查 | 172.27.182.61，m1x-test-api.service，18080 |
| M1X → M1X Manage OSS → test | 发布、状态检查 | m1x-manage-test，https://m1x-man-test.svision100.com |
| M1X → M1X Exam OSS → test | 发布、状态检查 | m1x-exam-test，https://m1x-exam-test.svision100.com |

API 公网健康检查为 `https://m1x-api-test.svision100.com/actuator/health`，预期 HTTP 200 / `{"status":"UP"}`。API 状态检查经 SSH 读取服务、端口归属、健康状态及 Jar 哈希，不读取私有配置内容，不执行重启。前端状态检查请求对应 OSS 域名 `/index.html`；尚未上传时返回失败，不能据此认定 API 不健康。

## API 发布规则

- `scripts/m1x-test-api.py deploy` 固定构建已部署的兼容提交 `88cacbcab99f5ab8c8e804c209b41dd7120884ca`。当前阶段禁止使用工作分支或 release 的最新提交替代；匿名渠道白名单必须等待既定验收。待条件满足后，通过明确的代码变更调整锁定提交。
- 在临时目录导出该提交，跳过 application 文件、部署目录和环境文件。使用 JDK 8 构建 API 及其依赖，执行 AccountChannelService、AccountChannelContract、ReportWebviewServiceImpl、TokenSigningIsolation 的定向测试；不构建或发布 Worker。
- 验证 Spring Boot API 制品及无 application 配置后上传；服务端校验 SHA-256、备份旧 Jar、停止 API、替换并启动。健康、端口归属或哈希验收失败则恢复旧 Jar；恢复未确认时返回失败，需先检查状态，不盲目重发。
- 仅操作 `/opt/m1x-test` 下已存在的 API 和 `m1x-test-api.service`。保留当前外部配置、独立签名、云数据服务、网络规则及服务启用状态；不安装数据服务、前端静态站点或 Worker。
- SSH 沿用用户指定的售后测试服务器文档，只在运行进程内解析；密码通过匿名管道交给 sshpass。使用已信任的主机指纹，不自动接受新指纹。需要本机 Python 3、sshpass、Git、Maven、JDK 8 及测试服务器网络可达。
- 发布备份保留在 API releases 目录，脚本不自动清理历史备份；不迁移数据库、不创建账号、不执行生产发布。

## 前端发布规则

两个 test 目标显式配置 `M1X_OSS_BUCKET`、`M1X_OSS_DOMAIN` 和 `M1X_OSS_BUILD_COMMAND='npm run build:test'`，调用前端仓库已有的 OSS 发布脚本。不会修改其生产默认参数，也不会触发生产分支收口。

前端源码为本机各仓库当前检出版本，发布前核对分支及本次变更。要求项目支持的 x64 Node 14 / node-sass 环境，并沿用已有 OSS 凭据获取流程。本机当前 ARM Node22 与现有原生绑定不兼容，新增菜单不会绕过该限制；须在兼容环境构建。也可按原流程手工上传 `dist/` 内容到对应 bucket 根目录。

此次接入仅保存菜单、验证构建与只读运行态，不触发菜单中的 API 发布、重启或 OSS 上传。前端上传后的多渠道登录、切号、多标签、报告免登录和匿名接口依赖验收仍遵守原计划。

## 本次接入验证

- deploySys 私有菜单保存成功；对照保存前备份逐项断言，所有既有目标及其他项目保持一致。
- 5 项定向测试通过，覆盖菜单幂等、生产目标保留、构建排除配置、API 制品校验、失败启动恢复旧 Jar 且不改私有配置，以及 check 操作不连接服务器。
- 经新脚本完成测试 API 只读状态核验：服务 active、18080 端口归属正确、健康 UP，运行 Jar 哈希仍为 `e002b376e35e781c0793c6247eb059730b4017b20f6cb1d13327bcff92366b50`。
- 通过新构建函数成功构建锁定提交并执行上述后端定向测试，生成的 API 制品校验通过；临时构建目录已清理，没有上传或替换现有服务。
- 构建使用本机现有 ARM JDK 8（`jdk-1.8.jdk`）和已有 Maven；Temurin 8 的 x64 二进制在本机不可执行，未修改或安装全局运行时。
- Python 语法与 `git diff --check` 通过；尚未执行真实 API 重发、重启、OSS 上传或前端完整浏览器验收。

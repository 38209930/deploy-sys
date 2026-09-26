# .NET ACS 标准发布手册

适用范围：北京 `ruishi-prod-acs` 本轮五项目。本文规定顺序与停止条件。实际创建资源时使用经代码会话验证的镜像、端口、环境变量和配置版本；任何变量尚未查实就停在该步。每项目各留一份填写完整的[发布记录](release-records.md)。

## 当前阶段：API 零副本预部署

本阶段独立于下文的生产启动与切换。ACR 的 `ruishi-dotnet-prod` 是镜像命名空间；ACS 按项目使用 `ai-study`、`service-order`、`points-mall`、`new-retail`、`agent-query`。执行记录见[2026-09-26 预部署记录](zero-replica-predeploy-2026-09-26.md)。

1. 每次阿里云 API 调用显式指定 `ruishi-prod-acr` Profile 和北京地域，先以 STS 核对账号 `1442361567788059`；同时检查 CLI 退出码及响应业务码。当前默认 Profile 属于其他账号。只有指定 Profile 的凭据实际失效时才提示用户重新登录；RAM/RBAC 拒绝单独报告。
2. 通过 ACR API 查询、创建私有仓库，绑定 Codeup，按每角色已交付的独立 Dockerfile 和冻结源码引用创建规则。`CreateRepoSourceCodeRepo` 返回 `SOURCE_ACCOUNT_NOT_AVAILABLE` 时停止该代码源绑定并核对实例级 Codeup 账号状态，不重复盲试。构建一次只启动一个任务，读回源码 SHA、构建结果及镜像 digest。
3. 通过 ACS/ACK OpenAPI 取得短时私网集群访问配置，再经 Kubernetes API 进行服务端校验、创建对应 Namespace、ServiceAccount、零副本 Deployment 和 API ClusterIP Service。临时配置不得进入聊天、日志或 Git；本阶段不创建资源配额、生产 Secret、Ingress、HPA 或 CronJob，不追加 ACR 凭据助手范围。
4. 没有合格镜像 digest 的角色不创建 Deployment。读回确认所有新 Deployment 的期望及实际 Pod 数均为零，且现有 Java 工作负载无配置或副本变更。项目阻断项交独立代码会话完成。

下文第 1 节起属于后续公网出口、生产启动与切换阶段；不因零副本资源准备完成而自动执行。

## 0. 发布前冻结

1. 刷新每个目标仓库远端引用，复核提交祖先关系；整理本机未提交业务修改，排除生成文件、个人配置和客户数据。新零售与积分商城虽然共用 Codeup 远端，但业务分支不同，必须分别冻结 SHA。代码会话完成评审、Release 构建、必要测试后再确认 `release` 基线。
2. 锁定每角色镜像 **digest**、构建 run 和源码 SHA；容器内不得包含生产配置。确认 Linux x64、固定 SDK/ASP.NET Runtime 版本、非 root 运行、可写临时目录和日志路径。Worker 无 HTTP Service。
3. 按[公共 NAT 出口手册](egress-nat.md)完成**实际启用**的生产外呼表、SDK 真实调用证据、供应商白名单、路由及来源隔离方案和预算；必需外呼缺项则不接入该项目。未启用的历史代码路径明确标注为禁用。
4. 冻结数据库结构与配置版本。证明旧新 API 并行期兼容、连接池总数可承受、无启动自动迁移和不受控 HostedService。经销商还须完成独立库数据转换演练和前端契约验收。
5. 记录旧服务实例、启动/停机/自动拉起机制和回滚命令；确定旧 Worker 已执行事件查询方式。各项目业务负责人确定验收场景及维护窗口。确认正式 DNS 的管理账号、记录修改人和回滚权限；当前 CLI 身份对 `svision100.com` 返回 `IncorrectDomainUser`，不能承担 DNS 切流。

## 1. 公共 NAT 出口准备

先执行[公共 NAT 出口手册](egress-nat.md)的只读核对及路由/来源隔离修订。**当前七个 vSwitch 共用一张系统路由表，首次建 NAT 会自动改变其默认路由，尚不具备生产创建条件。** 修订方案、受影响资源、窗口、回滚和实时报价获批后，才按手册通过 API 创建跨可用区 NAT、一个 EIP及精确 SNAT；诊断 Pod、七个 Java 项目和新 .NET 项目逐项验证。不能用 `curl` 出网代替 SDK 及供应商侧来源 IP 验收。

北京官方标价的跨可用区 NAT 为 ¥0.23/小时，加 EIP 保有及流量；本轮不采购出口 ECS。10 Mbps 是初始上限，先用外呼表和实测带宽复核。不得对现有混用的 ACS `/20` 网段直接创建整段 SNAT。

## 2. 项目零副本资源

按 [资源清单](inventory.md) 指定顺序逐项目操作。创建前保存现有 Java 命名空间、ACR 凭据助手及 ALB Host 规则的只读基线。

1. 创建项目 Namespace、ServiceAccount 与 ResourceQuota。只在 ACR 凭据助手的 `watchNamespace` 和 `serviceAccount` 追加该项目同名条目，保留旧列表；拉取权限验收后复查既有项目。
2. 建立每角色单独的 ACR 仓库和 `release` 固定 SHA 构建规则。构建失败时先排查公网依赖和 Dockerfile，不修改生产服务。镜像引用使用 digest。需核对仓库存储量、构建并发与产生费用。
3. 在获得具体授权后，通过受控通道下发**项目专用**生产 Secret；只记录名称、键、版本/摘要，不打印值。确认私网数据库/Redis/Mongo、SmsCore `172.27.182.18:3090` 仍走私网，第三方实际调用走已核验的 NAT EIP；检查并定向处理旧代理变量及 SDK 显式代理设置。变更 Secret 后显式滚动目标 Deployment。
4. 生成 Front/Admin/Worker Deployment，均以 `replicas: 0` 创建；`strategy.type: Recreate`、`requests=limits`、无 HPA。API 目标为容器 HTTP `8080`，逐项目实测监听与 Service `targetPort` 一致；售后工单当前 Kestrel 配置为 Front `3080`、Admin `3081`，若沿用 8080，需显式覆盖 `Kestrel__EndPoints__Http__Url` 并验证，单设 `ASPNETCORE_URLS` 不足以证明已覆盖。Worker 不创建 Service/Ingress。
5. API 探针：`/health/live` 只判进程；`/health/ready` 检查必要数据库、Redis 和所需结构。startup 5 秒×60、liveness 10 秒×3、readiness 5 秒×3，超时均 2 秒；如果实测启动时间不同，先更新清单与维护窗口。Worker 使用启动预检、心跳和任务结果，不配置伪 HTTP 探针。
6. `ASPNETCORE_ENVIRONMENT` 和 `DOTNET_ENVIRONMENT` 均为 `Production`；HTTP 绑定 `0.0.0.0:8080`；不以仓库默认配置覆盖 Secret。可信代理范围按 ALB **当前** Local IP 精确配置，`ForwardLimit=1`，实际经 ALB 请求核对 scheme、来源 IP、Cookie Secure、重定向和 CORS。
7. 在新 ALB 上由 Ingress Controller 创建精确 Host 规则。Ingress 使用 `ingressClassName: alb`，443 对应已核实证书，不改既有 Host 和监听器 ACL。此时 DNS 仍指旧 ALB。以指定 Host/SNI 请求新 ALB 做无流量切换的验收，证书校验必须通过；不要用 `curl -k` 掩盖证书问题。

## 3. 单项目启动与切换

正式域名目前仍解析旧 ALB；先获取对象明确的首次生产启动/停旧服务/切流授权，再按下述步骤执行：

1. **首次启动新 API 前**核对旧新 API 并行访问数据无冲突，逐项列出 API 内启动的定时器、队列消费者和其他 `HostedService`。若任一消费者可能与旧实例同时处理业务，先由该项目代码会话评审幂等及隔离/交接机制，写入项目发布记录并演练；未完成前不得启动新 API 与旧 API 并行。积分商城 Api 已确认会启动 Redis 消费者，属于此阻断项。若 API 无法先与旧版并行，停止并按该项目已评审的独立维护方案执行，禁止现场发明双写策略。
2. 前一步通过后，将 Front/Admin API 扩至 1，观察镜像拉取、进程、startup/readiness、数据库与缓存连接、内存峰值。通过新 ALB 的 Host/SNI 验证登录、读写主链、回调模拟或受控真实请求；401/403/404 只证明网关可达。
3. 对有 Worker 的项目：停止旧 Worker 并禁用自动拉起；确认进程退出、在途任务结束或状态明确、锁与待办队列可解释；再扩 ACS Worker 到 1。验证调度加载、首次到期任务、心跳、业务结果和重复执行防护。资金任务不自动批量补跑。
4. 确认证书、新 ALB 精确 Host 转发、客户端实测、回调白名单和生产业务验收。再将该项目域名由旧 ALB 记录切到新 ALB DNS `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`；检查权威 DNS、递归 DNS 和实际 HTTPS 请求。旧 API 保留至 TTL 与在途请求结束，旧 Worker 继续停止。
5. 记录切换时间、镜像 digest、Secret 版本、结构版本、Ingress/ALB 规则、DNS 前后值、业务证据和回滚入口。观察至少 24 小时并覆盖一次关键任务周期，随后才开始下一项目。经销商没有 Worker，但必须冻结旧后台写入、做最终数据导入与校验后切流。

## 4. 回滚门槛与动作

- 数据串库、鉴权绕过、重复扣款/退款/积分/短信：立即停止受影响新流量或任务，留存事件证据，不等待 10 分钟。
- 持续 10 分钟明显错误率/P95 恶化、OOM/CrashLoop、长期探针失败或关键业务结果不符：暂停下一项目并执行该项目回滚。
- API：先确认旧版对当前数据库结构和已发生写入兼容，再把精确 Host/DNS 恢复到旧入口；恢复旧镜像和其**配套 Secret/非秘密配置版本**，复核证书、登录和回调。DNS 回滚有缓存窗口，记录双入口请求。
- Worker：先把新 Worker 缩至 0 并确认 Pod 实际退出，核对已执行事件、待办队列和在途状态，随后恢复旧 Worker。不得以强制删除 Pod 后立即启动旧 Worker 代替交接。
- 经销商：若新库已有生产写入，必须先处理增量数据，不能单靠 DNS 回切。回滚方案在首次切流前通过迁移演练确认。

## 5. 关闭发布

对照 [项目验收表](inventory.md) 检查实际外呼出口、SmsCore 私网调用、API/Worker 业务记录、旧新执行重叠、CPU/内存和监控告警；内存峰值原则上不超过 limit 80%。保留发布及回滚证据，完成 `release` 到 `master` 的已验收变更同步。核对旧服务停用范围，不停止 AI Front、以旧换新或 SmsCore。最后对比 Java 应用和共享 ALB 的变更前后状态。

## 官方依据

- [ACS Pod 网络路径](https://help.aliyun.com/zh/cs/user-guide/accessing-the-external-network-in-the-pod)、[ResourceQuota](https://help.aliyun.com/zh/cs/user-guide/using-capacity-scheduling)、[ACS 计费](https://help.aliyun.com/zh/cs/product-overview/product-billing-rules)
- [ALB Ingress 工作原理](https://help.aliyun.com/zh/slb/application-load-balancer/alb-ingress)、[Kubernetes Deployment 替代 Pod 的行为](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [ASP.NET Core 健康检查](https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/health-checks?view=aspnetcore-10.0)、[可信代理与转发头](https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/proxy-load-balancer?view=aspnetcore-10.0)、[公网 NAT 与路由](https://help.aliyun.com/zh/nat-gateway/user-guide/use-internet-nat-gateway-for-public-network-access)

# 北京 ACS 部署复盘与风险清单（2026-09-27）

核验时间：2026-09-27 08:32 CST。范围为本轮 Java/.NET 的 ACS、ACR、ALB、公共 NAT、保留 ECS 的 SmsCore 及相关发布记录。本文是**只读复核快照**；本次没有修改云资源、数据库、Secret、业务代码或发送短信/资金请求。生产状态以每次变更前重新读回为准。

## 1. 证据口径与本次限制

| 证据级别 | 本次得到的内容 | 不能由此推出 |
|---|---|---|
| 云 OpenAPI 实时读回 | STS 为账号 `1442361567788059`；NAT/EIP/SNAT、三张路由表、五个关键 vSwitch、ALB 16 条精确 Host 规则、SmsCore/AI/售后/积分旧 ECS 状态、SmsCore 安全组 | Pod 实际副本、进程内任务、供应商已受理结果 |
| 公网请求实时测试 | 9 个 .NET API Host 的 `/health/ready` 均为 200 且 `curl` 证书校验成功；两个后台网页返回 200；AI 与经销商实际管理端 Origin 的登录预检均为 204 并返回对应 `Access-Control-Allow-Origin` | 有效账号登录、浏览器完整页面、订单/退款/短信/ERP 业务可用 |
| 2026-09-26/27 历史变更记录 | 售后 Worker 00:21 启动；Yangu/M1X 已迁新网段；AI/积分/新零售等角色的先前副本与 Pod IP | 08:32 的 ACS 副本和选址仍与记录相同 |
| 本次无法直接核验 | 本机到 ACS 私网 API `172.31.238.204:6443` 超时；系统路由走本地网关 `192.168.31.1`，未进入 OpenVPN | 不把历史 `kubectl` 快照写成今天的实时状态；不以此推断集群故障 |

本次尝试了 ACS `DescribeClusterUserKubeconfig` 的临时配置，返回的 API 端点仍是上述私网地址。配置只在受保护临时目录使用并自动清理，未输出凭据。恢复本机 OpenVPN 路由后，先按[API 操作说明](aliyun-api-operations.md)只读核对 Deployment、Pod、Ingress、Service、ServiceAccount、配置引用和事件；不需为此改生产网络。

## 2. 当前能够确认的部署事实

### 入口和应用

- ACS ALB `alb-olyb9enxszy3f42nnn` 的 443 监听当前有 16 条精确 Host 规则。Java Host 为 `rsapi`、`vet-api`、`stop-mp-api`、`m1x-api`、`et-bst-api`、`dgye-api`、`ddmpapi`；.NET Host 为 `rsst-back-api`、`rsod-front-api`、`rsod-back-api`、`rsjf-back-api`、`ns-front-api`、`ns-back-api`、`4l-api`、`rsqapi-ft`、`rsqapi-bk`（均为 `svision100.com`）。`4l-api` 与两个 `rsqapi` Host 指向同一个 ALB 服务器组；不能再称后两者为“历史未接入域名”。
- 本次 9 个 .NET API Host 的 `/health/ready` 都返回 200；测试保留了真实 Host/SNI、证书验证，没有发送认证或写请求。`ai-study-admin.svision100.com` 与 `agent-admin.svision100.com` 网页均返回 200。前者调用 `rsst-back-api`，后者调用 `rsqapi-bk`；两条登录预检的 CORS Origin 各自通过。此前“自习室后台仍完全无法访问”的报告，在**入口和预检层**已不复现；有效登录及页面后续接口仍未验收。
- ALB 当前**没有 SmsCore AdminApi 的 Host 规则**。SmsCore ECS `i-2ze38hdx1sufodad2kz0` 为 `Running`，私网 `172.27.182.18`，自带公网 IP `39.107.141.33`。安全组 `sg-2ze9w6ueqcnfc9wuov8k` 的入站 3090、3091、22 仅允许 `172.16.0.0/12`；本次未见这三个端口向 `0.0.0.0/0` 开放。ECS `Running` 不证明 SmsCore 的 systemd 服务和供应商发送均正常。
- AI 旧 ECS `i-2ze2s8pzq0kvqu28iml8`、售后旧 ECS `i-2ze710cj1qpe7s7zv5sq` 当前均为 `Stopped`；积分旧 ECS `i-2ze3w6i78cobsmmfo2y9` 为 `Running`。AI FrontApi 曾被设计为“保留 ECS”，但宿主机当前停机；是否仍有前台用户依赖，必须按真实入口确认，不能把“保留架构”写成“正在运行”。

### 出口和私网

- 公网 NAT `ngw-2zetnd6golba2sju2q7jo` 为 `Available`；EIP `eip-2zeapte07xmvayr4852h5` / `39.96.67.239` 为 `InUse`，绑定该 NAT、按流量计费、带宽上限 10 Mbps。
- SNAT 表 `stb-2zewws9r3mpb7ne3b6to8` **恰有两条 Available 规则**：`172.31.240.0/24` 和 `172.28.64.0/24`，均指向 `39.96.67.239`。旧 ACS Pod 网段 `172.31.224.0/20`、`172.28.48.0/20` 不在其中。
- 两个旧 Pod vSwitch 仍关联无默认路由的 `vtb-2ze9057j04btdfr3bofhy`；两个新 Pod vSwitch 关联有 NAT 默认路由的 `vtb-2zedknif7nxu7z397b4o6`；NAT 专用 vSwitch 关联系统表 `vtb-2zebvv47akvfr0cq15njq`。三张表均保留 `10.0.0.0/24` 的更具体路由，以及 `172.27.176.0/20` 等 VPC 私网路由。它们的存在不能代替 Pod 到 MySQL/Redis/MongoDB/SmsCore 的认证和业务测试。
- 历史 00:30 记录：Yangu 和 M1X API/Worker 已迁到新 Pod 网段；从 M1X API Pod 实测出口为固定 EIP，Yangu 的 MongoDB 启动连接成功。**未见 M1X Worker、Yangu 各自真实供应商请求的独立验收证据**。STOPMP、ETBST、DDMP、新零售、经销商按历史快照仍在旧网段；本次无法读回实时 Pod IP，不能断言目前未变化。
- SmsCore 路径为业务 Pod → 私网 `172.27.182.18:3090` → SmsCore ECS → 短信供应商。SmsCore ECS 不在本次 NAT SNAT 来源范围；`39.107.141.33` 是它的实例公网地址，**供应商实际看到的出口 IP 尚未取证**。

### 历史发布进度与时间边界

2026-09-27 00:30 的[交接记录](HANDOVER-2026-09-26.md)显示：DGYE、VET 0 副本；其余列出的 Java API 运行，M1X Worker 单独运行；AI Back/Worker、售后 Front/Back/Worker、积分 Back/Worker、新零售 Front/Back/Worker、经销商单体 API 已启动。积分 Front 仍在 ECS。**这些是历史读回值，不是本次 08:32 的 Kubernetes 实时读回。** Worker 唯一执行、旧服务自动拉起、镜像摘要与配置版本也不能仅凭副本数证实。

## 3. 复盘：做对了什么，哪里失准

1. 网络改动先分离旧业务路由，再创建 NAT 与新 Pod vSwitch，避免把包含网站 ECS 的旧 `/20` 整段纳入 SNAT；本次路由和 SNAT 读回仍符合这个隔离设计。[阿里云 NAT 文档](https://help.aliyun.com/zh/nat-gateway/user-guide/use-internet-nat-gateway-for-public-network-access)说明系统默认路由和 vSwitch 粒度 SNAT 的作用边界。
2. ALB 由 ACS Ingress 管理，精确 Host 规则和证书的公网验证比“控制台能看到 ALB”更有用；此前把 ALB 域名加 `Host` 头的 TLS 失败误判为故障，已在手册中修正。阿里云说明 Controller 会同步 Service/Endpoint 到服务器组，直接改托管资源可能被拒绝或覆盖。[ACS ALB Ingress 说明](https://help.aliyun.com/zh/cs/user-guide/troubleshooting-alb-ingress-exceptions)、[托管资源错误码](https://help.aliyun.com/zh/slb/application-load-balancer/developer-reference/api-alb-2020-06-16-errorcodes)。
3. 先前把健康 200 近似当成上线完成，使 AI 与经销商的浏览器 CORS 问题在用户实际登录时才暴露；现已分别修正并通过真实 Origin 预检，但有效登录仍须业务验收。今后发布门槛必须同时包含真实前端 Origin、认证接口、主业务接口和回调，健康接口只做第一层检查。
4. 之前把经销商前后台域名、AI 管理端域名及 API 混淆，造成错误排查方向。已核对前台网页与 API 的一一对应，维护单一域名清单，不从仓库旧字符串推断线上地址。
5. 文档以“当前”描述历史快照，又在后续变更记录单独修补，导致 README、发布手册、运维手册仍写售后 Worker 为 0，经销商 Host 错标。今后每次变更先更新当前索引和风险清单，历史操作记录保留时间戳，不回写成无时间边界的现状。

## 4. 发现项与处置优先级

| 优先级 | 发现与证据 | 影响及明确动作 |
|---|---|---|
| P1 | AI FrontApi 的保留 ECS 当前 `Stopped`；是否还有前台流量未知 | 核对 `rsst-front-api` 的 DNS、旧 ALB 后端和访问日志，再由业务负责人确认是否停用或恢复；在确认前不得把 AI 前台列为“运行正常”。本次不启动旧 ECS。 |
| P1 | 旧 Pod 网段无本次 NAT 出口；历史记录中至少新零售 Front/Worker 调微信支付超时 | 重读实时 Pod IP；对仍需外呼的项目补“短信旧通道/白名单/任务副作用/真实 SDK”门槛后逐项目迁移，不给整个旧 `/20` 加 SNAT。经销商仅用已验证私网查询时可保持原位置。 |
| P1 | 售后、AI、积分、新零售等 Worker/消费者已经或曾经启动；缺少旧 systemd 自启、首次到期任务、幂等与 24 小时业务结果的成套证据 | 按每个 Worker 的业务事件 ID、锁和外部平台结果核对；资金、积分、短信结果不明时先查证，禁止因健康 200 直接认定无重放。售后 ECS Stopped 只能证明实例不运行，不能替代完整交接记录。 |
| P1 | 本次会话历史中出现过疑似生产管理员账号的明文登录请求；AI 短信凭据曾出现在受控命令输出（发布记录称已轮换） | 若管理员口令仍有效，应由凭据所有人轮换并审查相关登录审计；复核旧短信凭据确已禁用。不要把口令、密钥及完整请求复制进文档或工单。本次未读取凭据，也未测试该口令。 |
| P1 | 运维手册承认告警接收渠道未落实；缺少 NAT、ALB、Pod、Worker、支付/短信业务告警的实测闭环 | 明确接收人和升级链，先做无业务副作用的告警测试；记录触达时间、项目和处理人。未配置完成前，不能声称有 24×7 告警保障。 |
| P2 | SmsCore AdminApi 尚无 ACS ALB Host；直接改托管 ALB 曾收到 `OperationDenied.ServiceManagedResource` | 如需用此 ALB 发布后台，先确认具体被拒绝的 API 对象，再评估[官方 ALB Ingress 混合挂载](https://help.aliyun.com/zh/cs/user-guide/use-alb-ingresses-to-configure-hybrid-backend-server-groups)对**独立创建**服务器组的支持与账号权限；先做配置校验、访问控制和证书/回滚评审。本次没有发布 SmsCore 后台。 |
| P2 | SmsCore 安全组对 3090、3091、SSH 允许整个 `172.16.0.0/12`，覆盖远大于已知 Pod/运维来源的私网范围 | 盘点实际 VPC/对等/VPN 来源，再按应用鉴权和管理端权限收窄；不得直接改共享安全组造成现网中断。公网未见这三个端口对任意地址开放。 |
| P2 | 新 NAT 一个 EIP、10 Mbps，上线项目增加后存在共享带宽、SNAT 连接数和供应商白名单集中风险 | 以 CloudMonitor 和账单实测峰值、失败率、连接容量；记录每个外部平台的新出口白名单及其所有者。当前未取得指标，不能评估容量已足够。 |
| P2 | 生产短信路由“全部仅走 SmsCore”仍主要依据管理员确认；外部依赖表对多项目写“待核对” | 逐项目只读比对**生效**通道、模板、SmsCore 鉴权/来源白名单与成功回执；禁止把“ruishi 优先级最高”当作旧通道已停。真实发送需单独业务授权。 |
| P2 | 本机 OpenVPN 当前缺 ACS 私网 API 路由，影响只读巡检和故障诊断 | 恢复预期 VPN 连接/路由后重做 ACS 全量副本、选址、Service/Ingress 对账；本次未改 VPN、VPC 或云集群。 |

以上为**部署与运行配置复核**；未执行完整源码安全审计、容器镜像漏洞扫描、真实支付/短信投递或生产破坏性测试。SSRF、幂等、鉴权绕过等代码层风险仍需项目独立会话按实际实现审查，不能把“待审查”写成已发现漏洞。

## 5. 补验顺序与关闭标准

1. 恢复本机到 ACS 私网 API 的 OpenVPN 路由，读回各 Deployment 副本、Pod IP、镜像 digest、Service/Ingress/Endpoint、探针、ServiceAccount 与旧 Java 状态；把差异追加为新时间戳快照。
2. 对 AI Front 旧入口、积分 Front ECS 和各旧 Worker 逐个确定实际服务状态、自动拉起及业务归属。先处理可能的用户入口故障，再处理资源整理。
3. 按项目补全生产外呼与短信路由清单，先验新零售的实际支付路径和旧网段出口问题，再处理其他尚需公网的项目；Yangu/M1X 的真实 SDK/白名单与 M1X Worker 分角色验收。
4. 完成真实前端登录及业务读写验收、首次到期任务、短信发送/回执、资金回调和 24 小时观察；每项记录时间、项目、镜像 digest、配置版本、关联业务 ID的脱敏引用与验收人。缺一项就标“未验收”，不宣称项目整体完成。
5. 配置并实测告警；按月核对 ACS、ACR、ALB、NAT/EIP、OSS/日志和旧 ECS 账单。历史费用公式是预算，不是实账。

文档使用顺序：本页作为**最近一次有边界的复核** → [API 操作说明](aliyun-api-operations.md)重新读回 → [发布记录](release-records.md)找历史镜像和配置 → [NAT 执行记录](egress-nat-execution-2026-09-26.md)找网络变更证据 → [发布手册](runbook.md)与[值班手册](ops-playbook-2026-09-27.md)执行。历史预部署、变更单和旧快照只记录当时状态，不作为“当前”来源。

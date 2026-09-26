# .NET ACS 公共公网出口：实施前复核与落地清单

状态：**方案已复核，生产出口未实施**。复核日期：2026-09-26。适用本轮五个 .NET 项目的九个 API、四个 Worker；不改变既有七个 Java 项目和 SmsCore 的网络路径。本文件是出口建设和切流门槛，不构成采购或生产变更授权。

## 1. 现状与设计决定

2026-09-26 只读核对：北京 ACS `ruishi-prod-acs` 位于 VPC `vpc-2zervez1jgscsglpenrzo`；Pod 当前使用 `172.31.224.0/20`、`172.28.48.0/20` 两个 vSwitch 网段，同网段还有既有 Java 应用。目标 VPC 的公网 NAT 网关查询为 **0**。现有部署记录没有代理 ECS/EIP 的资源 ID、配置版本或验收记录；.NET Namespace 尚未创建。因此本轮 .NET 的**固定公网出口尚未建成**。ECS/EIP 名称查询未发现标注为出口代理的资源，但不能仅凭名称排除无标注资源，采购前仍要按资源 ID 与账单复核。

**采用的实施路径**：同 VPC、北京地域新建独立 ECS，绑定独立固定 EIP，ECS 私网 `3128` 提供**TLS 加密的正向代理入口**。ACS 项目 Pod 经私网连接代理；代理按批准的目的域名/端口建立 HTTP CONNECT，由 EIP 出公网。SmsCore 仍走 `172.27.182.18:3090` 私网，数据库、Redis、同地域 OSS 私网端点也直走私网；外部平台回调仍从 ALB 进入 API。

```
.NET Pod ──私网──> 出口代理 ECS:3128 ──独立 EIP──> 已批准的外部 HTTP(S) 服务
        ├──私网──> SmsCore / 数据库 / Redis / 私网 OSS
外部回调 ──HTTPS──> 既有 ALB ──> 对应 API
```

选此路径的原因：不为当前与 Java 共用的 vSwitch 创建 SNAT，避免把 Java Pod 一并开放到公网；也不修改集群默认 vSwitch/安全组。阿里云说明：Pod 到同 VPC ECS 可走私网；公网 NAT 必须配置 SNAT 才生效，按当前两个 vSwitch 建 SNAT 会影响其上的其他 Pod。[ACS 网络路径](https://help.aliyun.com/zh/cs/user-guide/accessing-the-external-network-in-the-pod)、[ACS 公网访问](https://help.aliyun.com/zh/cs/user-guide/enable-public-network-access-for-an-existing-cluster)

**能力边界**：HTTP/HTTPS 正向代理不能保证所有 SDK 或非 HTTP 协议都走该 EIP。Linux 上 .NET `HttpClient` 默认代理可读环境变量，但显式 `HttpMessageHandler`、第三方 SDK、原生 Socket/gRPC/WebSocket 等须逐项实测；未验证调用不计入已覆盖。`NO_PROXY` 使用精确主机名或前导点域名，不用 CIDR 或 `*` 作为已验证规则。[Microsoft DefaultProxy](https://learn.microsoft.com/en-us/dotnet/api/system.net.http.httpclient.defaultproxy?view=net-10.0)

| 备选 | 当前结论 | 启用条件 |
|---|---|---|
| 当前 vSwitch 上建公网 NAT + SNAT | 不采用；会扩大既有 Java Pod 的公网出口范围 | 只有在重新设计独立网络边界、验证 Java 不受影响并另行授权后评估 |
| 每个 Pod 独立 EIP | 不采用；13 个角色的公网 IP 和供应商白名单难以维护 | 个别无法代理且必须直连的角色，独立评审 |
| 独立 vSwitch + NAT | 暂不采用；ACS 指定 Pod vSwitch 要求交换机属于集群已配置列表，添加集群 vSwitch 后默认 Pod 选址也可能变化 | 作为下一轮架构方案，先验证隔离与现有 Java Pod 重建行为，再变更共享集群配置。[Pod 指定 vSwitch](https://help.aliyun.com/zh/cs/user-guide/specify-vswitch-and-securitygroups-for-the-pod) |

## 2. 上线前必须冻结的事实

按**生产实际启用的调用路径**登记，不以代码中未启用的历史功能阻塞项目；但任何启用而未登记的调用均是切换阻断项。每条记录填写：

`项目 / 角色 / 业务动作 / 目标域名与端口 / HTTP协议或其他协议 / SDK与版本 / 实际代理设置方式 / 请求超时 / 失败与重试规则 / 幂等业务键 / 平台回调地址 / 旧与新出口IP白名单 / 测试证据 / 负责人`。

特别核对支付、退款、ERP、微信/小程序、OSS、地图或 AI 接口、邮件及短信。短信项目仍应走 SmsCore 私网，不把旧短信供应商列为新代理出口。OSS 若已使用同地域私网端点，保留该路径；若是公网端点，先查能否改为私网。`HTTP_PROXY`/`HTTPS_PROXY` 只对经证实读取它们的客户端生效；不能用一次 `curl` 成功替代 SDK 真实请求。回调入口与外呼出口分别验证。

每项目最少提供一个真实业务调用的代理日志关联号与供应商侧来源 EIP 证据；资金、退款或短信测试涉及真实外部副作用时按该对象取得授权。供应商白名单应在切换期同时包含旧出口和新 EIP，观察稳定后再删旧 IP。未知的非 HTTP 必需调用、SDK 无法遵从代理或平台拒绝代理流量时，暂停该项目发布，交给该项目代码会话适配；不要在切流现场临时加全 VPC NAT。

## 3. 代理资源、隔离与基线

1. **采购前核价**：以现时报价核对非突发 ECS `ecs.u1-c1m1.large`（2 vCPU/2 GiB）、40 GiB 系统盘、独立 EIP 和公网流量。10 Mbps 只是待测的初始带宽上限，按最大并发、响应体和上传下载量复核；不把旧报价当承诺。确认配额、可用区、EIP 可绑定条件和代理软件包版本。
2. **ECS**：放在同 VPC 的独立安全组，选不影响已有资源的 vSwitch；固定私网 IP 或稳定的内部 DNS 名称写入项目发布记录。仅允许受控运维入口登录，代理进程以独立低权限用户运行，systemd 自动启动，配置和软件版本留哈希/备份；磁盘日志限额与轮转明确。EIP 绑定后 ECS 可能具有公网入站路径，所以 `3128` 只绑定私网 IP，安全组与主机防火墙均拒绝公网入站，且实际从公网做拒绝测试。不要将“绑定 EIP”误写成“只能出站”。
3. **来源边界**：代理安全组只允许经核实的 ACS Pod 网段到私网 `3128`；因为网段与 Java 共用，此规则**不等于只允许 .NET**。代理再按项目设置凭据和允许目的域名，且每项目分别轮换。凭据仅经生产 Secret 下发，不写入 Git、命令行、日志或文档。代理入口使用 TLS 和可信证书，客户端必须校验证书；Squid 软件包需有 `https_port` 所需的 TLS 支持。代理拟用专用名称 `egress-proxy.svision100.com`（先确认未占用），私网 DNS 解析到 ECS 私网地址；使用独立证书，不复制 ALB 通配符证书的私钥。证书以 DNS 验证方式签发，签发/续期权限与到期告警在阶段 A 明确；没有域名管理权限或可信证书时不得启用生产代理。项目级认证与各 SDK 的 HTTPS 代理支持须一起实测；不支持的 SDK 交由项目代码会话适配，不能静默降级到明文认证。TLS 到代理与通过 CONNECT 到供应商的 TLS 是两段不同的连接，均不关闭证书校验。[Squid HTTPS 监听](https://www.squid-cache.org/Doc/config/https_port/)
4. **目的边界**：锁定经验证的软件包主版本和配置语法。Squid ACL 按顺序拒绝不安全端口、非 443 CONNECT、回环、RFC1918、链路本地、云元数据 `100.100.100.200` 和未授权来源；仅放行登记的目的域名，结尾显式 `deny all`。拒绝直接以 IP 字面量 CONNECT、未知域名、DNS 解析到私网/保留网段、代理访问自身；通过真实解析和重绑定测试确认行为。禁止 TLS 解密与替换业务证书。注意 Squid 官方 `http_access` 页面标示适用至 v7，使用的软件包版本必须与所用语法一致。[Squid ACL](https://www.squid-cache.org/Doc/config/http_access/)
5. **Pod 侧**：仅在本轮 .NET Deployment 中注入经验证的代理地址和凭据；`NO_PROXY` 只列经核实的内部 HTTP 主机及私网 OSS/SmsCore 名称或精确 IP。数据库原生 TCP 不依赖这些 HTTP 变量。部署前逐项目比对环境变量大小写、SDK 显式代理配置和 Secret 加载顺序。已有 Java Deployment/Secret/ServiceAccount 均不修改。
6. **强制出口声明**：在未核实隔离控制前只能承诺“已登记的外呼通过固定 EIP”，不能宣称整个 Namespace 所有出网被技术强制到代理。若需要强制阻断旁路，先只读核查 ACS Poseidon/NetworkPolicy 是否启用，再在新 .NET Namespace 定向验证 DNS、私网依赖、ALB 回包和代理允许规则；启用 Poseidon 是共享集群变更，必须单独评审。阿里云说明该能力要求 Poseidon、Pod 注解，且仅支持指定算力/IPv4。[ACS NetworkPolicy](https://help.aliyun.com/zh/cs/user-guide/use-network-policies-in-container-compute)

## 4. 单机故障与恢复选择

初始单台代理 ECS 是**所有新项目公网调用的共同单点**。其故障可影响支付、退款、ERP 等外呼，而 ALB 入站、数据库私网和 SmsCore 私网链路可以继续可用。不能把 API 的 `/health/ready` 简单绑定代理或任意第三方状态，否则代理故障可能使所有 API 同时摘流。

正式采用单机前，业务负责人须接受经演练得到的恢复时间目标（RTO）和允许停发/排队的业务行为；目前 RTO **未实测、未承诺**。维护版本化代理配置、系统镜像/安装清单和 EIP 资源 ID，演练“停代理 → 业务超时/队列行为 → 恢复同机服务”以及“替代 ECS 私网地址或 DNS 更新 + EIP 重绑 + 供应商来源核验”。**EIP 重绑本身不会改变 Pod 指向的旧 ECS 私网地址**，恢复步骤必须同时处理 Pod 连接目标。恢复前确认未知结果的支付/退款先查单再重试，Worker 不盲目重放。

如果不能接受单机的演练 RTO，应在首个资金类项目上线前升级为高可用设计：两台跨可用区代理 ECS、各自 EIP，内部稳定的代理入口/故障切换机制，并让供应商白名单同时覆盖两枚 EIP；增加负载均衡与健康检查，分别测单机故障、出口 IP 漂移、会话中断和费用。此升级单独核价与评审，不把“两台 ECS + 单枚 EIP”误当自动高可用。

## 5. 实施顺序与停机线

| 阶段 | 操作 | 进入下一阶段的证据 |
|---|---|---|
| A 事实冻结 | 完成五项目启用外呼表；核查现有 NAT/EIP/安全组、Poseidon、供应商白名单、实时价格；落实代理专用域名的私网 DNS、证书签发/续期权限；确认单机 RTO 是否可接受 | 业务/技术共同确认调用覆盖、网络边界、费用、证书和恢复选择；缺失则不采购 |
| B 采购与基线 | 对明确的 ECS、盘、EIP、流量计费及必要安全组取得生产/付费授权；创建并记录资源 ID、IP、版本、配置哈希与原有 Java 基线 | ECS/EIP、私网路由及安全组仅影响新资源；公网 `3128` 被拒绝 |
| C 代理验收 | 配置 ACL/认证和日志；验证许可域名、拒绝域名、非 443、私网/元数据、无凭据、错误凭据、DNS 指向私网、直接公网绕过、重启恢复、容量和带宽 | 全部负例拒绝；代理侧与供应商侧确认同一固定 EIP；无敏感日志 |
| D 项目接入 | 逐项目在代码会话完成 SDK 真实请求验证和必要适配；经具体授权下发代理 Secret；在项目 Pod 中验证私网依赖仍直连 | 每个启用外呼有真实结果或受控模拟证据，超时/重试/幂等行为可解释 |
| E 首项试运行 | 按总发布顺序先迁 AI 自习室，观察出口连接、失败率、带宽、CPU/内存与业务结果至少 24 小时 | 故障恢复演练/RTO、日志告警、白名单和回滚步骤可复现，再迁下一项目 |

任何阶段出现未登记必需外呼、代理绕过、开放代理、来源 IP 不匹配、支付/退款结果不明而会重试、现有 Java/SmsCore 受影响，立即停止新项目推进。已上线项目的代理故障按[运维备忘录](operations.md)暂停或排队相关外呼，恢复后逐条查证业务结果；不临时开放全网 SNAT。

## 6. 交付记录

出口资源记录：ECS ID、私网地址/内部 DNS、EIP ID 和地址、安全组 ID、系统与 Squid 版本、配置哈希、凭据版本（不含值）、域名 ACL 版本、第三方白名单核对日期、日志与告警、演练 RTO、月费实账。每项目记录其调用表版本、SDK 代理证据、`NO_PROXY` 验证、真实来源 EIP、业务验收与回滚路径。首个项目生产启动前，这两类记录必须齐全。

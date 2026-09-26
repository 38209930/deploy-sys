# ACS 公共公网出口：执行手册与当前门槛

状态：**阶段 A 只读网络核对完成一部分；未创建 NAT、EIP、路由或 SNAT，生产项目尚未接入。** 更新：2026-09-26。本手册取代原单机 Squid 代理方案。业务代码适配在各项目独立会话完成。

## 1. 固定架构与边界

北京 `ruishi-prod-acs` 使用一个跨可用区容灾增强型公网 NAT 网关及一个普通 BGP 固定 EIP；只配置 SNAT，初始带宽上限 10 Mbps。用户、微信及支付回调继续经现有 ALB 入站；Pod 到 MySQL、Redis、MongoDB、同地域私网 OSS 和 SmsCore `172.27.182.18:3090` 保持私网。SmsCore 仍由其 ECS 出公网调用短信供应商，不属于本次 SNAT 来源。Worker 只出站，不创建公网入口。API 使用 ClusterIP Service。

NAT 是网络层出口，不要求 Java 和 .NET SDK 统一使用 HTTP 代理；禁止给新部署注入 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 或 Java `http.proxyHost` 作为本出口的必需配置。显式代理残留须逐角色核对实际用途后处理。NAT 不提供域名级控制，安全组、第三方鉴权、用户可控 URL 的 SSRF 防护和业务幂等仍需分别验证。入站 ALB 可信转发头设置与出站 NAT 无关。

范围：已上线 DGYE、VET、STOPMP、ETBST、DDMP、Yangu、M1X；随后迁移 AI 自习室、售后工单、积分商城、新零售、经销商查询。AI FrontApi、以旧换新及 SmsCore 保留 ECS 和原出口。本次不改项目业务代码、支付协议、数据库结构及任务调度；发现缺口交对应项目会话，未修复前停止该来源接入。

## 2. 2026-09-26 只读核对结果

| 对象 | 已核实事实 |
|---|---|
| ACS / VPC | `cebc88343a44b4d759aa983a47b787835` / `vpc-2zervez1jgscsglpenrzo`，北京 |
| ACS 当前两个 vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`，北京 k，`172.31.224.0/20`；`vsw-2zec5qkbaiafqu3pyuamo`，北京 i，`172.28.48.0/20` |
| VPC 路由 | **仅一张系统路由表** `vtb-2zebvv47akvfr0cq15njq`，关联七个 vSwitch；当前无 `0.0.0.0/0`。已有 VPC 本地、`100.64.0.0/10` 服务及 `10.0.0.0/24` 对等连接路由 |
| 公网 NAT / EIP | 公网 NAT 数量为 0；现有 EIP 均已绑定其他资源，不可直接复用 |
| 范围外来源 | 网站 ECS `i-2ze1j9z5b6vggyjr4bxv` 的私网 IP `172.31.238.203` 落在 ACS 北京 k 的 `/20` 内；同一系统路由表还服务其他五个 vSwitch |
| SmsCore | ECS `i-2ze38hdx1sufodad2kz0`，私网 `172.27.182.18`，实例自带公网地址 `39.107.141.33`；**该地址不是本次新 EIP**。供应商观察到的实际源地址、白名单仍待核对 |

**生产创建阻断：**[阿里云 CreateNatGateway 文档](https://help.aliyun.com/zh/nat-gateway/developer-reference/api-vpc-2016-04-28-createnatgateway-natgws)说明，首次创建增强型公网 NAT 会自动给 VPC 系统路由表加入指向 NAT 的 `0.0.0.0/0`。官方进一步说明，系统路由会引导关联的全部 vSwitch 流量；没有匹配 SNAT 的来源可能无法访问公网。[路由与 SNAT 粒度说明](https://help.aliyun.com/zh/nat-gateway/user-guide/use-internet-nat-gateway-for-public-network-access)。因此“先给诊断 Pod 配 `/32` SNAT”**不能隔离创建 NAT 时的自动路由影响**。当前七个 vSwitch 均使用系统表，直接创建会改变本次范围外来源的路由；本手册禁止按原顺序继续阶段 B。网站 ECS 虽有自带公网 IP，官方记载实例自带公网 IP 优先于 SNAT，但这不足以证明其他私网实例和服务不受影响。当前两个 `/20` 整段 SNAT 也会覆盖范围外来源。不能把 Namespace 视为 NAT 隔离边界。

### 解除阻断所需的网络修订

1. 逐 vSwitch 枚举 ECS、ACS Pod/ENI、ALB ENI及其他资源，按来源和现有出站方式分类；特别核验范围外 ECS 与 SmsCore 的实际出口。保存全部路由表关联、路由条目及关键业务基线。
2. 先设计并评审**路由表隔离**：可采用事先创建自定义路由表并迁移不应受 NAT 默认路由影响的 vSwitch；关联变更本身影响共享网络，须列出逐交换机窗口、验证与回退。禁止仅凭“没有 SNAT 就不会受影响”下结论。预演新路由表是否保留本地及对等连接路由；检查阿里云对系统路由传播的实际行为。
3. 再解决**来源隔离**：优先给纳入项目使用专用 ACS Pod vSwitch，并明确 Pod 选址、重建和与现网 Java 的迁移窗口；或提出可随 Pod 重建稳定生效、且不覆盖网站 ECS 的等效方案。ACS 官方要求 Pod 指定的 vSwitch 已在集群配置中；把新 vSwitch 加入集群后，未指定的 Pod 可能随机选中它，故必须同时设计已有工作负载的显式选址或其他全量隔离办法，不能只给新项目写 Annotation。[ACS 指定 vSwitch](https://help.aliyun.com/zh/cs/user-guide/specify-vswitch-and-securitygroups-for-the-pod)、[ACS 扩展 vSwitch](https://help.aliyun.com/zh/cs/user-guide/use-additional-vpc-segments-to-expand-the-virtual-switches-of)。临时 Pod `/32` 只用于诊断和单 Pod 灰度，不得当成最终规则。所有改造须保持 SmsCore 与现有 Java 私网路径、ALB 入站可用。
4. 修订后的路由/来源拓扑、资源 ID、CIDR、变更窗口、回滚命令与范围外验证证据形成独立变更单；获得该**扩大后的生产网络变更范围**授权后，才可采购并创建 NAT/EIP。未通过评审，不为赶进度在共享系统表上试建。

## 3. 阶段 A：每项目发布门槛

每个实际启用的调用登记：`项目 / API或Worker / 业务动作 / 配置来源及版本 / 目的域名和端口 / 协议及SDK版本 / 应用商户标识引用 / 超时与重试 / 幂等依据 / 回调URL / 来源IP白名单归属 / 验收证据`。数据库通道、Secret、外部文件、环境变量、SDK 显式配置均需核对，但不把秘密值写入文档或日志。源码存在而生产未启用的路径单独标注。

| 范围 | 必须通过的业务核对 |
|---|---|
| 七个 Java 项目 | 逐项目确认微信、支付及其他实际启用公网调用；**旧短信直连供应商通道全部禁用**，不是仅调高 SmsCore 优先级；检查公网恢复后定时任务、失败队列是否自动补发。M1X 的 API、Worker 分开验收，保持 `APP_ROLE` 与唯一 Worker |
| AI 自习室 | 旧 ECS FrontApi 留用；核对共享微信 token、数据库、消息状态与新 BackApi/Worker 兼容，不重复刷新或同步 |
| 售后工单 | 聚水潭 token 与游标、发货/退款、飞书、支付；核对 Kestrel 端口与 ERP/短信幂等索引 |
| 积分商城 | 三方积分、微信、支付退款、快递、地图、OCR；API 内 Redis 消费者必须单独交接 |
| 新零售 | 按实际启用功能检查支付/退款/分账；新 Worker 若无禁用调度参数，旧 Worker 停止前保持零副本 |
| 经销商查询 | 只保留门店查询维护、登录及必要地图/图片调用，不启动 Apollo 无关支付、训练、ERP 或任务 |
| SmsCore | 各项目私网来源白名单、API Key/HMAC 与发送幂等；其 ECS 的真实公网源 IP和供应商白名单保持原路径 |

任何生产外呼清单缺失、旧短信通道仍启用、资金写请求超时重试行为不明、告警接收渠道未落实，均阻断该项目的生产来源 SNAT。不能用 `curl` 出网成功替代真实 SDK、签名、回调和业务结果验收。

## 4. 修订获批后的 API 实施顺序

下面是执行门槛和顺序，**不是当前可直接运行的命令**。每个写 API 保存 RequestId、参数摘要、资源 ID、前后状态；使用接口支持的固定 ClientToken，结果不明先只读查询。

1. 实时报价、余额与配额核验；确认 NAT 可用区、专用 NAT vSwitch 的不重叠 CIDR、一个普通 BGP 按流量 EIP 的 10 Mbps 带宽上限及具体授权。跨可用区容灾模式保持官方默认或在 API 明确指定；不误选单可用区。专用 NAT vSwitch 不加入 ACS Pod 自动选址。
2. 按获批的隔离设计完成自定义路由表关联及前后验证；保存现有七 vSwitch 的路由快照。创建 NAT 前检查是否出现新的默认路由或未登记出口。
3. 创建按量增强型公网 NAT（`NetworkType=internet`、`NatType=Enhanced`）、等待 `Available`；立即核验系统表自动 `0.0.0.0/0` 的关联范围及范围外服务。创建 EIP、绑定 NAT，记录唯一固定公网 IP；只做 SNAT，不建 DNAT。
4. 诊断 Pod 使用精确源 `/32` 建临时 SNAT。核对 Pod 经 EIP 的公网出站、私网 MySQL/Redis/Mongo/SmsCore、ALB 入站及拒绝入站；DNS/TLS/非 443 端口按外呼表测试。若诊断失败，先查路由、安全组、网络策略，不扩展来源规则。
5. Java 按 DGYE → VET → STOPMP → ETBST → DDMP → Yangu → M1X 逐项接入。每项 `/32` 源仅用于首轮灰度，Pod 重建后 IP 会变化；最终必须迁到经评审的专用 Pod vSwitch SNAT 或其他稳定精确来源。每次验证真实客户端外呼、供应商侧源 IP、短信只经 SmsCore、任务副作用、私网路径与 ALB。M1X 双角色单独记录。全体观察至少 24 小时并覆盖关键任务周期。
6. 仅在该 vSwitch **全部当前与未来来源**均属获批范围后，改为稳定的 vSwitch SNAT；验证 Pod 重建后仍从同一 EIP 出网，移除临时 `/32` 规则。禁止对原混用 `172.31.224.0/20` 直接整段创建 SNAT，禁止 VPC 通配 SNAT。
7. .NET 迁移顺序为 AI → 售后工单 → 积分商城 → 新零售 → 经销商；每项目单独完成代码会话交付、配置授权、Worker/消费者交接、业务验收与 24 小时观察。详细 API/Worker 切换见[发布手册](runbook.md)。

## 5. 跨语言外呼及业务验收

- Java HTTP 客户端、.NET `HttpClient`/`HttpWebRequest`、支付、微信、ERP SDK 分别用实际请求验证 TLS、CA、超时、来源 IP。JDK 8 镜像特别核对 CA/TLS；保持服务器证书校验和连接复用。普通幂等短查询在缺少项目策略时建议连接超时 5 秒、总超时 30 秒、最多两次退避重试；429 尊重 `Retry-After`。文件上传和长连接另记。
- 支付、退款、扣积分、发货及短信不套通用网络重试；超时结果不明先按原业务号查证，安全重试保持原幂等标识。公网恢复不自动补跑历史任务。外部供应商故障不默认使所有 API readiness 失败。
- 微信逐 AppID 区分公众号、小程序、开放平台和企业微信；只向确有服务器 IP 白名单的平台追加新 EIP。合法域名、网页授权及回调仍使用正式域名。旧新并行时验证 token 缓存隔离、刷新协同、回调验签解密与去重。
- 各支付产品分别登记商户、SDK/协议、证书或公钥版本、notify_url、查单及回调应答规则；验证订单、金额、币种、重复和乱序通知。真实资金测试另按订单、金额、次数和善后范围授权。不要因 NAT 改动升级支付协议。
- 短信固定为项目 Pod → 私网 `172.27.182.18:3090` → SmsCore ECS → 供应商。核对全局来源白名单和项目身份鉴权、模板映射、业务事件去重及发送回执；HTTP 200 不代表供应商送达。发生路由修改的项目逐个验收。
- 聚水潭、积分、飞书、地图、快递、OCR、AI、OSS 与非 HTTP 调用按**实际启用**配置验收。OSS 同地域已验证私网端点保持私网。大文件、流式响应另评估 10 Mbps 上限、超时与出流量。
- 安全组只放行有依据的目的端口，项目级规则不得误改共享 Java/ECS 安全组；IPv4 出口验收并确认 ACS 实际 IPv6 状态。NAT 无域名 ACL，SSRF 缺口由项目代码会话处理。

## 6. 监控、成本与回滚

监控 NAT 状态、SNAT 失败/连接容量、EIP 带宽、项目外呼失败率/P95、429/超时及支付待确认、短信失败、ERP 积压。带宽持续 5 分钟超过上限 70%预警；超过 85%且出现业务失败时处理。5 分钟至少 20 次调用且失败率超过 5%告警。告警渠道须先实测；日志初始保留 7 天且不记录密钥、手机号、完整报文。

按北京官方标价估算，跨可用区 NAT `0.23 元/小时`、EIP 保有约 `0.02 元/小时`，720 小时固定费约 **180 元**；再加 `0.23 元 × NAT 双向处理 GiB` 与约 `0.80 元 × 公网出流量 GiB`。流量口径和账单优惠以下单页及当月账单为准。首月 400 元预警、600 元升级复核；阈值不自动断网。[NAT 计费](https://help.aliyun.com/zh/nat-gateway/nat-gateway-billing)、[EIP 计费](https://help.aliyun.com/zh/eip/pay-as-you-go/)、[CDT](https://help.aliyun.com/zh/cdt/internet-data-transfers/)。

临时 `/32` 灰度异常，只撤销对应临时 SNAT 并检查已发生外部结果。最终共享 SNAT 后，单项目优先回滚版本/配置，不撤销所有项目出口。共享网络故障须按事先批准的路由及 SNAT 回滚顺序处理，并逐项复核范围外来源、全部 Java、SmsCore；保留 EIP，不新申请出口。Worker 回滚先停新后启旧，未知支付/退款/短信结果先查证。跨可用区切换可能中断现有连接，不能承诺零中断。

## 7. 执行记录模板（不填秘密值）

`变更单 / 授权对象与范围 / 时间窗口 / 操作人 / 前置路由和资源快照 / 路由隔离方案 / CIDR与vSwitch / NAT及EIP资源ID / RequestId及ClientToken摘要 / SNAT来源清单 / 各项目配置版本与镜像SHA / 外呼与私网验收证据 / 供应商白名单 / 告警通知测试 / 回滚演练 / 24小时观察 / 实账`。

当前所有生产创建、项目生效配置、短信旧通道状态及真实业务调用均为**待验证**，不能将本手册中的目标设计写成已上线事实。

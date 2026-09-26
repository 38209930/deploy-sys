# ACS 公共公网出口：执行手册与当前门槛

状态：**跨可用区 NAT、固定 EIP、旧业务路由隔离和两个新 Pod vSwitch 的稳定 SNAT 已创建并完成网络验收；原有业务 Pod 未迁移，项目 SDK 与业务验收待执行。** 更新：2026-09-26。本手册取代原单机 Squid 代理方案。业务代码适配在各项目独立会话完成。实际资源和验证证据见[网络实施记录](egress-nat-execution-2026-09-26.md)，准备及回滚细节见[生产网络变更单](egress-nat-change-order.md)和[网段记录](network-constraints-2026-09-26.md)。

## 1. 固定架构与边界

北京 `ruishi-prod-acs` 使用一个跨可用区容灾增强型公网 NAT 网关及一个普通 BGP 固定 EIP；只配置 SNAT，初始带宽上限 10 Mbps。用户、微信及支付回调继续经现有 ALB 入站；Pod 到 MySQL、Redis、MongoDB、同地域私网 OSS 和 SmsCore `172.27.182.18:3090` 保持私网。SmsCore 仍由其 ECS 出公网调用短信供应商，不属于本次 SNAT 来源。Worker 只出站，不创建公网入口。API 使用 ClusterIP Service。

NAT 是网络层出口，不要求 Java 和 .NET SDK 统一使用 HTTP 代理；禁止给新部署注入 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 或 Java `http.proxyHost` 作为本出口的必需配置。显式代理残留须逐角色核对实际用途后处理。NAT 不提供域名级控制，安全组、第三方鉴权、用户可控 URL 的 SSRF 防护和业务幂等仍需分别验证。入站 ALB 可信转发头设置与出站 NAT 无关。

范围：已上线 DGYE、VET、STOPMP、ETBST、DDMP、Yangu、M1X；随后迁移 AI 自习室、售后工单、积分商城、新零售、经销商查询。AI FrontApi、以旧换新及 SmsCore 保留 ECS 和原出口。本次不改项目业务代码、支付协议、数据库结构及任务调度；发现缺口交对应项目会话，未修复前停止该来源接入。

## 2. 2026-09-26 网络实施状态

| 对象 | 已核实事实 |
|---|---|
| ACS / VPC | `cebc88343a44b4d759aa983a47b787835` / `vpc-2zervez1jgscsglpenrzo`，北京 |
| ACS 当前两个 vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`，北京 k，`172.31.224.0/20`；`vsw-2zec5qkbaiafqu3pyuamo`，北京 i，`172.28.48.0/20` |
| VPC 路由 | 七个旧 vSwitch 已关联无默认路由的 `vtb-2ze9057j04btdfr3bofhy`；系统表只关联 NAT 专用 vSwitch；两个新 Pod vSwitch 关联 `vtb-2zedknif7nxu7z397b4o6`。系统表与出口表的默认路由指向同一 NAT，旧业务表保留本地、服务和 MongoDB 对等路由且无默认路由 |
| 公网 NAT / EIP | `ngw-2zetnd6golba2sju2q7jo`，跨可用区增强型；EIP `39.96.67.239` / `eip-2zeapte07xmvayr4852h5`，普通 BGP、按流量计费、10 Mbps 上限；仅两个新 Pod vSwitch 有稳定 SNAT |
| 范围外来源 | 网站 ECS `i-2ze1j9z5b6vggyjr4bxv` 的私网 IP `172.31.238.203` 落在 ACS 北京 k 的 `/20` 内；同一系统路由表还服务其他五个 vSwitch |
| SmsCore | ECS `i-2ze38hdx1sufodad2kz0`，私网 `172.27.182.18`，实例自带公网地址 `39.107.141.33`；**该地址不是本次新 EIP**。供应商观察到的实际源地址、白名单仍待核对 |
| ACS 运行配置 | `acs-profile` 保留旧 k/i 并追加新 k/i，默认 selector 已实测仍选旧 k/i；10 个现有运行中业务 Pod 未迁移，两区诊断 Pod 已清理 |

[阿里云 CreateNatGateway 文档](https://help.aliyun.com/zh/nat-gateway/developer-reference/api-vpc-2016-04-28-createnatgateway-natgws)说明首次创建增强型公网 NAT 会给 VPC 系统路由表自动加入指向 NAT 的 `0.0.0.0/0`。实施前已逐个把旧七个 vSwitch 迁入路由内容相同、无默认路由的自定义表；系统表随后只承载 NAT 专用 vSwitch。新网段的 vSwitch 级 SNAT 仅覆盖经明确选址的新 Pod；Namespace 本身不构成 NAT 来源隔离。实际路由和读回见[实施记录](egress-nat-execution-2026-09-26.md)。

### 已确定的隔离设计

七个旧 vSwitch 先转到没有默认路由的自定义表，完整保留 VPC local、云服务和对等连接路由；NAT 专用 vSwitch 单独保留在系统表，承接创建 NAT 时自动加入的默认路由。另建两个 ACS 业务 Pod 专用 vSwitch 与出口自定义路由表，只有该表指向 NAT。`acs-profile` 先设置旧 k/i 兜底选址 selector，再追加新 vSwitch；业务 Pod 逐个显式迁入，两个新 vSwitch 各建一条稳定 SNAT，指向同一个 EIP。现有旧 k/i 网段、网站 ECS、SmsCore 不加入新出口。具体 CIDR、七个旧交换机、API 顺序及安全回滚见[生产网络变更单](egress-nat-change-order.md)。

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

## 4. API 实施顺序与当前进度

每个写 API 保存 RequestId、参数摘要、资源 ID、前后状态；接口支持时使用固定 ClientToken，结果不明先只读查询。完整逐步门槛见[生产网络变更单](egress-nat-change-order.md)。

1. **已完成：**MongoDB 新网段回程、白名单及双区 TCP 检查；实时报价、路由内容对比；七个旧 vSwitch 逐个迁入旧业务表。本机 OpenVPN 仅在需要直连新 Pod 时另行调整。
2. **已完成：**创建隔离的新 Pod/NAT vSwitch、跨可用区增强型公网 NAT（`EipBindMode=NAT`）、单一 EIP；系统表默认路由只作用于 NAT 专用 vSwitch，出口表默认路由只作用于两个新 Pod vSwitch。
3. **已完成：**ACS 默认旧 k/i 选址护栏、新 k/i 诊断 Pod 临时 `/32` 测试和重建、两个新 vSwitch 的稳定 SNAT；临时条目与诊断 Pod 均已清理。两区私网和固定 EIP 验证见[实施记录](egress-nat-execution-2026-09-26.md)。
4. 按 DGYE → VET → STOPMP → ETBST → DDMP → Yangu → M1X 逐项把已通过业务门槛的 Deployment 显式迁入新 vSwitch。每次验收真实 SDK外呼、私网、ALB、SmsCore 和任务状态；M1X 双角色分别核对。全部观察至少 24 小时并覆盖关键任务周期。
5. .NET 按 AI → 售后工单 → 积分商城 → 新零售 → 经销商顺序迁移，各项目代码交付、配置、Worker/消费者交接及业务验收另按[发布手册](runbook.md)执行。

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

按北京官方标价估算，跨可用区 NAT `0.23 元/小时`、EIP 保有约 `0.02 元/小时`，720 小时固定费约 **180 元**。本次账号报价 API 对 NAT 实例费显示当前优惠后 `0.1955 元/小时`，对应 720 小时约 `140.76 元`；加按官方标价估算的 EIP 保有费约 `14.40 元`，静态项合计约 `155.16 元`，**另计** NAT 双向处理量与 EIP 公网出流量。账单优惠和流量单价以实际账单为准。首月 400 元预警、600 元升级复核；阈值不自动断网。[NAT 计费](https://help.aliyun.com/zh/nat-gateway/nat-gateway-billing)、[EIP 计费](https://help.aliyun.com/zh/eip/pay-as-you-go/)、[CDT](https://help.aliyun.com/zh/cdt/internet-data-transfers/)。

诊断 `/32` 异常时撤销相应临时 SNAT，不影响旧网段。业务项目异常时优先恢复该 Deployment 的旧选址并检查已发生外部结果；不得直接撤销其他项目依赖的共享 SNAT。NAT 创建后，旧 vSwitch **不得直接解绑回系统表**，因为系统表已有默认路由；共享网络回滚需按[变更单](egress-nat-change-order.md)的阶段顺序操作，并逐项复核范围外来源、全部 Java、SmsCore。保留 EIP，不新申请出口。Worker 回滚先停新后启旧，未知支付/退款/短信结果先查证。跨可用区切换可能中断现有连接，不能承诺零中断。

## 7. 执行记录模板（不填秘密值）

`变更单 / 授权对象与范围 / 时间窗口 / 操作人 / 前置路由和资源快照 / 路由隔离方案 / CIDR与vSwitch / NAT及EIP资源ID / RequestId及ClientToken摘要 / SNAT来源清单 / 各项目配置版本与镜像SHA / 外呼与私网验收证据 / 供应商白名单 / 告警通知测试 / 回滚演练 / 24小时观察 / 实账`。

网络资源与双区数据面已按[实施记录](egress-nat-execution-2026-09-26.md)验证；项目生效配置、短信旧通道状态、真实 SDK 和业务调用仍为**待验证**，不能把网络验收写成项目上线验收。

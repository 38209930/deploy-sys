# .NET 10 项目接入现有北京 ACS

状态：**公共 NAT 已建；五个 .NET 项目均有 ACS 运行对象，售后 Worker 为 0、副本状态和业务验收各不相同。** 更新：2026-09-26 23:39 CST。当前值先看[现场交接快照](HANDOVER-2026-09-26.md)，再按[阿里云 API 使用说明](aliyun-api-operations.md)读回。本页说明架构与文件入口；业务代码适配在各项目独立会话完成。任何“待验证”项都不能在切换时凭经验补齐。

## 范围

本轮范围是新零售、积分商城、售后工单、AI 自习室和经销商查询，设计共 8 个 API Deployment、4 个 Worker；经销商的前后台接口由同一个 `agent-query-api` 承载。AI FrontApi、积分商城 FrontApi、以旧换新和 SmsCore 仍留原 ECS。当前 ACS 实际创建 **7 个 API、4 个 Worker**，其中积分 Front 未创建、售后 Worker 为零副本；细节以交接快照为准。Worker 的唯一执行还须靠旧服务退出确认和业务幂等，不能只靠单副本。每项发布后至少观察 24 小时并覆盖关键任务周期，尚未取得完整观察证据。

接手先看 [交接快照](HANDOVER-2026-09-26.md) 和 [阿里云 API 使用说明](aliyun-api-operations.md)。日常运维执行入口见[运维值班手册](ops-playbook-2026-09-27.md)（每日/每周/每月巡检、变更 SOP、故障速查、遗留项清单）。逐项目版本与验收见 [发布记录](release-records.md)，外呼见 [公共出口核对表](external-dependencies.md)，网络实操与证据见 [NAT 执行手册](egress-nat.md)、[实施记录](egress-nat-execution-2026-09-26.md)，发布与故障见 [发布手册](runbook.md)、[运维备忘录](operations.md)。[资源清单](inventory.md)保留早期规划参数，不能代替当前读回。这些文件不包含凭据、配置值和客户数据。

## 已查实的共享环境

| 资源 | 当前事实 |
|---|---|
| ACS | 北京 `ruishi-prod-acs`，集群 ID `cebc88343a44b4d759aa983a47b787835`；此前只读盘点为 Java 项目，随后新零售和经销商查询已发布到各自 Namespace，变更前须重新盘点实际运行状态 |
| VPC | `vpc-2zervez1jgscsglpenrzo` |
| vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`（`172.31.224.0/20`，盘点时可用 IP 4076）；`vsw-2zec5qkbaiafqu3pyuamo`（`172.28.48.0/20`，可用 IP 4085） |
| 新 ALB | `alb-olyb9enxszy3f42nnn`，公网，DNS `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`；HTTPS 443 监听 `lsn-3hl3j4qtjt8b1z7jkl`；集群 IngressClass 为 `alb` |
| ACR | 企业版经济型 `ruishi-prod`，实例 `cri-73ffxebpi6ruw6sn`；`ruishi-dotnet-prod` 已创建。当前 ACS Deployment 的镜像均为 ACR digest；各角色构建记录以发布记录和 ACR API 读回为准 |
| 既有应用 | 2026-09-26 23:39 读回：Java 的 STOPMP、ETBST、DDMP、Yangu、M1X API/Worker 为 1/1，DGYE、VET 为 0；.NET 的新零售三角色、AI 两角色、积分 Back/Worker、售后 Front/Back、经销商 API 为 1/1，售后 Worker 为 0。SmsCore 仍在 ECS |

上述内容由只读云 API/集群查询得到；在每次生产变更前需重新核对。尤其 ALB 的 Local IP 可能变化，可信代理地址必须在发布前按实时地址刷新，并用实际请求验证。不得把整个 Pod 子网当可信反向代理来源。

现有 ACR 经济版的官方规格为 5 个镜像命名空间、1 个并发构建任务。当前占用 3 个命名空间；本轮 13 个角色的云构建必须串行安排，不把等待队列当构建失败。[ACR 企业版规格](https://help.aliyun.com/zh/acr/product-overview/billing-of-container-registry-enterprise-edition-instances)

## 当前进度及阻断项

- 公共 NAT、EIP、旧路由隔离、两个新 Pod vSwitch 和稳定 SNAT 已按[实施记录](egress-nat-execution-2026-09-26.md)完成；2026-09-26 23:39 OpenAPI 再次读回 NAT `Available`、EIP `InUse`、两条 SNAT `Available`。AI、售后、积分的运行 Pod 已有部分落入新网段；Java、新零售和经销商的当前 Pod 仍在旧网段。不能再沿用“空的新业务网段”的历史结论。
- AI Back/Worker、积分 Back/Worker、售后 Front/Back、经销商单体 API、新零售三角色在 ACS 为 1/1；售后 Worker 为 0，积分 Front 仍留 ECS。七个正式 .NET HTTPS `/health/ready` 本次返回 200，**业务验收、Worker 到期任务和供应商侧出口证据不能由此推断**。
- 每项目代码审查、实际公网调用/SDK/白名单、短信真实投递、资金和 ERP 结果、告警与 24 小时观察仍需逐项核对。`points-mall-front` 的 Codeup 绑定曾失败，该角色目前不在 ACS，不能使用预部署计划中的“三角色均上线”说法。
- NAT 创建前的准备快照见[网段记录](network-constraints-2026-09-26.md)；它不是当前资源状态。当前资源状态统一看[交接快照](HANDOVER-2026-09-26.md)。

发布不得以编译通过、Pod Ready、HTTP 401/404 代替真实业务验收。任何一项阻断未消除，保持旧系统运行并停在对应阶段。

## 权限边界

只读盘点和文档维护可继续。生产采购、生产配置读取与下发、扩大镜像拉取范围、首次启动生产实例、旧服务启停、数据库写入和正式切流，按项目规则分别记录对象、环境、动作和范围并取得明确授权。五个代码会话只处理各自开发验证，不改生产资源。

# .NET 10 项目接入现有北京 ACS

状态：**分项目部署中；新零售与经销商查询已在 ACS 运行，其余项目按各自发布记录核对。公网 NAT 尚未上线。** 更新：2026-09-26。本文是本轮部署的入口；业务代码适配在各项目独立会话完成。任何“待验证”项都不能在切换时凭经验补齐。

## 范围

本轮迁移新零售、积分商城、售后工单、AI 自习室和经销商查询，共 8 个 API Deployment、4 个 Worker；经销商的前后台接口由同一个 `agent-query-api` 承载。AI FrontApi、以旧换新和 SmsCore 留在原 ECS。单角色一个副本，API 使用 `Recreate`，Worker 还须通过旧服务退出确认和业务幂等保障唯一执行。每项上线后至少观察 24 小时并覆盖关键任务周期；实际发布顺序以逐项目授权和依赖就绪情况确定。

具体资源与域名见 [资源清单](inventory.md)，逐项目外呼见 [公共出口核对表](external-dependencies.md)，.NET 阻断项见 [五项目发布记录](release-records.md)，公共公网出口见 [NAT 执行手册](egress-nat.md)，生产路由与来源隔离见 [网络变更单](egress-nat-change-order.md)，操作顺序见 [发布手册](runbook.md)，故障与费用见 [运维备忘录](operations.md)。这些文件不包含凭据、配置值和客户数据。

## 已查实的共享环境

| 资源 | 当前事实 |
|---|---|
| ACS | 北京 `ruishi-prod-acs`，集群 ID `cebc88343a44b4d759aa983a47b787835`；此前只读盘点为 Java 项目，随后新零售和经销商查询已发布到各自 Namespace，变更前须重新盘点实际运行状态 |
| VPC | `vpc-2zervez1jgscsglpenrzo` |
| vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`（`172.31.224.0/20`，盘点时可用 IP 4076）；`vsw-2zec5qkbaiafqu3pyuamo`（`172.28.48.0/20`，可用 IP 4085） |
| 新 ALB | `alb-olyb9enxszy3f42nnn`，公网，DNS `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`；HTTPS 443 监听 `lsn-3hl3j4qtjt8b1z7jkl`；集群 IngressClass 为 `alb` |
| ACR | 企业版经济型 `ruishi-prod`，实例 `cri-73ffxebpi6ruw6sn`；`ruishi-dotnet-prod` 已创建，本轮 13 个私有镜像仓库已通过 API 创建；代码源、构建规则和镜像仍待完成 |
| 既有应用 | 2026-09-26 复核为 10 个运行中业务 Pod：ETBST、DDMP、STOPMP、Yangu、M1X API/Worker、新零售三个角色及经销商 API；DGYE、VET 当前零副本。SmsCore 仍在 ECS |

上述内容由只读云 API/集群查询得到；在每次生产变更前需重新核对。尤其 ALB 的 Local IP 可能变化，可信代理地址必须在发布前按实时地址刷新，并用实际请求验证。不得把整个 Pod 子网当可信反向代理来源。

现有 ACR 经济版的官方规格为 5 个镜像命名空间、1 个并发构建任务。当前占用 3 个命名空间；本轮 13 个角色的云构建必须串行安排，不把等待队列当构建失败。[ACR 企业版规格](https://help.aliyun.com/zh/acr/product-overview/billing-of-container-registry-enterprise-edition-instances)

## 当前进度及阻断项

- 已完成：五项目范围、初始规格、旧域名和实例盘点；同仓库的新零售/积分商城基线差异已识别；五项目代码适配已交给各自独立会话。AI 自习室、积分商城、新零售、售后工单的适配分支已交付且目标 Release 构建或 publish 通过，镜像运行与生产业务尚未验收。
- ALB 的目标 Host、证书和后端规则须在每个项目发布时重新核对；此前“全部 .NET 目标域名均返回 503”的预部署记录已不适用于现已运行的新零售和经销商查询。此前核验的通配符证书覆盖 `*.svision100.com`，有效期至 2027-02-28 23:59:59 UTC；正式发布仍须重新核对。
- 2026-09-26 零副本预部署：已使用显式 `ruishi-prod-acr` Profile 核对生产账号并创建 13 个私有镜像仓库；ACS 私有 API 可达且当前身份具备创建 Namespace、Deployment、Service 的权限。`points-mall-front` 的 Codeup API 绑定返回 `SOURCE_ACCOUNT_NOT_AVAILABLE`，需完成代码源绑定后再配置构建。详见[预部署执行记录](zero-replica-predeploy-2026-09-26.md)。
- 尚未完成：各项目代码会话的完整评审及运行验收；实际启用的外部调用/SDK/白名单清单；NAT 生产网络变更；Worker 及 API 内消费者的交接核对、业务验收。经销商合并 API 已通过私网连接原生产 MySQL、Redis，并以单副本接通 `4l-api.svision100.com`；图片真实上传、管理员登录与维护操作仍待业务验收，详见[发布记录](release-records.md)。
- 出口复核：目标 VPC 的公网 NAT 网关为 0；七个旧 vSwitch 仍共用无默认路由的系统表。首次创建 NAT 会自动添加系统默认路由，影响全部关联 vSwitch 的路径。本次已创建两张私网/出口自定义表、三个隔离新 vSwitch，并配置 ACS 默认选址护栏。新网段到 MySQL、Redis、SmsCore 私网 TCP 已双区通过；MongoDB 对端已补齐两个回程路由及独立白名单，新 k/i Pod 至两个私网节点的 TCP 建连均通过，认证和业务读写待项目启动时验收。OpenVPN 的本机直连新 Pod 路由不阻断云侧诊断。见[网段记录](network-constraints-2026-09-26.md)。旧 vSwitch 和业务 Pod 未迁移。
- 公共出口阶段仍**未采购 NAT/EIP**；经销商单体 API 已复用原生产 RDS、Redis、OSS 的私网路径并创建专用 Ingress。新零售及经销商的实际启动与入口状态以[发布记录](release-records.md)为准；未修改既有 Java 资源。

发布不得以编译通过、Pod Ready、HTTP 401/404 代替真实业务验收。任何一项阻断未消除，保持旧系统运行并停在对应阶段。

## 权限边界

只读盘点和文档维护可继续。生产采购、生产配置读取与下发、扩大镜像拉取范围、首次启动生产实例、旧服务启停、数据库写入和正式切流，按项目规则分别记录对象、环境、动作和范围并取得明确授权。五个代码会话只处理各自开发验证，不改生产资源。

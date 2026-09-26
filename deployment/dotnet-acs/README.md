# .NET 10 项目接入现有北京 ACS

状态：**部署准备中，未发布**。更新：2026-09-26。本文是本轮部署的入口；业务代码适配在各项目独立会话完成。任何“待验证”项都不能在切换时凭经验补齐。

## 范围

本轮迁移新零售、积分商城、售后工单、AI 自习室和经销商查询，共 9 个 API、4 个 Worker。AI FrontApi、以旧换新和 SmsCore 留在原 ECS。单角色一个副本，API 使用 `Recreate`，Worker 还须通过旧服务退出确认和业务幂等保障唯一执行。项目顺序固定为：AI 自习室 → 售后工单 → 积分商城 → 新零售 → 经销商查询；每项至少观察 24 小时并覆盖关键任务周期。

具体资源、域名和待验证项见 [资源与发布清单](inventory.md)；操作顺序见 [发布手册](runbook.md)；故障与费用见 [运维备忘录](operations.md)。这些文件不包含凭据、配置值和客户数据。

## 已查实的共享环境

| 资源 | 当前事实 |
|---|---|
| ACS | 北京 `ruishi-prod-acs`，集群 ID `cebc88343a44b4d759aa983a47b787835`；目前只有既有 Java 项目 Namespace，没有本轮 .NET Namespace |
| VPC | `vpc-2zervez1jgscsglpenrzo` |
| vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`（`172.31.224.0/20`，盘点时可用 IP 4076）；`vsw-2zec5qkbaiafqu3pyuamo`（`172.28.48.0/20`，可用 IP 4085） |
| 新 ALB | `alb-olyb9enxszy3f42nnn`，公网，DNS `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`；HTTPS 443 监听 `lsn-3hl3j4qtjt8b1z7jkl`；集群 IngressClass 为 `alb` |
| ACR | 企业版经济型 `ruishi-prod`，实例 `cri-73ffxebpi6ruw6sn`；当前 10 个仓库，均非本轮 .NET 镜像。本轮仓库、配额和构建规则尚待创建/核验 |
| 既有应用 | DGYE、VET、STOPMP、ETBST、DDMP、Yangu、M1X 的 Namespace 与工作负载保持原状；SmsCore 仍在 ECS |

上述内容由只读云 API/集群查询得到；在每次生产变更前需重新核对。尤其 ALB 的 Local IP 可能变化，可信代理地址必须在发布前按实时地址刷新，并用实际请求验证。不得把整个 Pod 子网当可信反向代理来源。

## 当前进度及阻断项

- 已完成：五项目范围、初始规格、旧域名和实例盘点；同仓库的新零售/积分商城基线差异已识别；四项目代码适配已交给独立会话，现有少量探针/转发头修改的 Release 构建均通过。
- 尚未完成：各代码会话的评审、测试和冻结 SHA；全部外部调用目的域名/SDK/代理兼容表；代理 ECS/EIP 价格及购买；镜像仓库、镜像 digest、生产配置 Secret、证书绑定、Worker 交接核对、业务验收；经销商 Apollo 契约和独立数据迁移。
- 因上述缺口，本轮**尚未采购出口 ECS/EIP，未创建 .NET Namespace/镜像仓库/Ingress，未启动任何新 Pod，未停旧服务，未修改 DNS 或既有 Java 资源**。

发布不得以编译通过、Pod Ready、HTTP 401/404 代替真实业务验收。任何一项阻断未消除，保持旧系统运行并停在对应阶段。

## 权限边界

只读盘点和文档维护可继续。生产采购、生产配置读取与下发、扩大镜像拉取范围、首次启动生产实例、旧服务启停、数据库写入和正式切流，按项目规则分别记录对象、环境、动作和范围并取得明确授权。五个代码会话只处理各自开发验证，不改生产资源。

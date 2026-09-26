# 五项目发布记录

状态：预填的部署记录，所有「待验证」均为切换阻断项。只填资源 ID、版本和证据位置，不填配置值、密钥、手机号或客户数据。每项目分别记录实际授权、维护窗口、切换时间、24 小时观察起止和回滚决定。

## 2026-09-26 零副本预部署状态

ACR `ruishi-dotnet-prod` 下本页所列 13 个私有仓库已通过 API 创建；[资源 ID 和 RequestId 见执行记录](zero-replica-predeploy-2026-09-26.md)。镜像构建、digest、ACS 项目 Namespace、Deployment 和 Service 均未完成；所有新角色实际 Pod 数为零。Codeup 绑定 API 对 `points-mall-front` 返回 `SOURCE_ACCOUNT_NOT_AVAILABLE`，其余仓库未重复尝试同一失败条件。项目源码与构建门槛继续以各节记录为准。

## AI 自习室（第一项）

- 目标：`ai-study` Namespace；`ai-study-back` 1 CPU/2 GiB、`ai-study-worker` 0.5 CPU/1 GiB；FrontApi 留旧 ECS `i-2ze2s8pzq0kvqu28iml8`。
- Host：`rsst-back-api.svision100.com`。旧 DNS 为 `39.105.188.147`；新 ALB 证书握手已验证，Host 规则尚无。
- 源码：`/Volumes/SSD/work/mall/ai自习室/prod@aliyun/ai-study-api`；ACS 适配分支 `deploy/dotnet-acs-ai-study` 已推送 `213984d`，交接说明在 `RuishiStore/ACS_DEPLOYMENT.md`。两个 Release 构建通过，Docker 基础镜像下载未完成，镜像运行未验收。本机业务改动仍未纳入该提交；最终 `release` SHA、两个镜像 digest、Secret 版本、结构版本：待验证。
- 切换关键点：后台登录、卡与账户管理、同步任务、旧 FrontApi 与新 BackApi/Worker 对同一数据库的兼容；旧 Worker 停机及自动拉起、锁和首个到期任务：待验证。适配分支的 Worker 默认为不注册定时任务，开启需 `Worker__ScheduledJobsEnabled=true` 和项目专用 `Worker__QuartzLockName`；新 MySQL 命名锁不约束旧 ECS Worker，旧进程退出仍是硬门槛。
- 生产授权、旧服务命令、外呼表、第三方白名单、任务结果、24 小时观察及回滚证据：待验证。

## 售后工单（第二项）

- 目标：`service-order` Namespace；`service-order-front` 1 CPU/2 GiB、`service-order-back` 0.5 CPU/1 GiB、`service-order-worker` 1 CPU/2 GiB；旧 ECS `i-2ze710cj1qpe7s7zv5sq`。
- Host：`rsod-front-api.svision100.com`、`rsod-back-api.svision100.com`。旧 DNS 为 `101.201.60.62`；新 ALB 证书握手已验证，Host 规则尚无。
- 源码：`/Volumes/SSD/work/mall/售后工单系统/service-order-api`；ACS 适配分支 `deploy/dotnet-acs-service-order` 已推送 `fb36c8a`，交接说明在 `Doc/release/ACS容器部署适配说明.md`。三个 Linux x64 Release publish 通过；Docker 基础镜像下载未完成，容器运行未验收。远端尚无 `release` 分支，最终发布基线、三个 digest、Secret/结构版本：待验证。
- 切换关键点：工单创建/流转、ERP 同步、发货与退款状态、聚水潭 token、任务游标和 Redis 锁、短信业务事件幂等；旧 Worker 首次停机和队列核验：待验证。Front/Admin 当前 Kestrel 端口为 **3080/3081**，与本轮统一容器端口 8080 不同；若沿用 8080，应显式覆盖 `Kestrel__EndPoints__Http__Url` 并实测探针与 Service，不能只设置 `ASPNETCORE_URLS`。Worker 无 HTTP；Redis 任务锁为固定 TTL，不能单靠锁保证跨副本独占。短信及 ERP 幂等所需唯一索引须只读核对。构建产物包含被代码会话标为非敏感的 `appsettings.Production.json`，发布前仍需检查镜像没有真实生产连接与密钥，敏感值全部由外部注入。
- 生产授权、外呼白名单、真实业务回调、24 小时观察及回滚证据：待验证。

## 积分商城（第三项）

- 目标：`points-mall` Namespace；`points-mall-front` 1 CPU/2 GiB、`points-mall-back` 0.5 CPU/1 GiB、`points-mall-worker` 0.5 CPU/1 GiB；旧 ECS `i-2ze3w6i78cobsmmfo2y9`。
- Host：`rsjf-front-api.svision100.com`、`rsjf-back-api.svision100.com`。旧 DNS 为 `101.201.60.62`；新 ALB 证书握手已验证，Host 规则尚无。
- 源码：`/Volumes/SSD/work/mall/积分商城/jifen-api-release`；ACS 适配分支 `deploy/dotnet-acs-points-mall` 已推送 `af33e93`，交接说明在 `scripts/deploy/acs/README.md`。三个 Release 构建通过；Docker 基础镜像下载未完成，容器运行未验收。最终 `release` SHA、三个 digest、Secret/结构版本：待验证。
- 切换关键点：积分余额与兑换、扣减幂等、退单返还、现金支付相关流程、短信和 Worker 错过任务规则：待验证。Worker 可通过 `Worker__EnableQuartz=false` 预启动；启用调度前必须确认旧 Worker 退出。**Api 启动时还会启动 Redis 消息消费者**，旧新 Api 并行可能同时消费；在评审消费者的队列语义、幂等和交接步骤前，禁止按通用的「先启动新 API、保留旧 API」流程切换。
- 生产授权、第三方白名单、旧 Worker 交接、24 小时观察及回滚证据：待验证。

## 新零售（第四项）

- 目标：`new-retail` Namespace；`new-retail-front` 1 CPU/2 GiB、`new-retail-back` 0.5 CPU/1 GiB、`new-retail-worker` 0.5 CPU/1 GiB。2026-09-26 经 ECS API 确认旧 ECS `i-2ze68mprzc2jzea57xfz` 为 `Stopped`；ACS 三个 Deployment 均 1/1 Ready，Worker 保持单副本，无 Service/Ingress。
- 新 Host：`ns-front-api.svision100.com`、`ns-back-api.svision100.com`。已创建各自精确 Host 的 `new-retail-front-alb`、`new-retail-back-alb`，使用现有 ALB 的 HTTPS 443、ClusterIP Service 8080；两域名直接连接 ALB 时 `/health/live`、`/health/ready` 均返回 200，TLS 校验通过。
- 源码：`/Volumes/SSD/work/mall/新零售/newsale-api`；分支 `deploy/dotnet-acs-new-retail` 冻结提交 `5ad04591a4701164d9d4b0dcd1d64e011051abb4`，业务基线为 `product/new-retail`，不可误用同远端积分商城的 `release`。ACR 分别使用仓库根目录的 `Dockerfile.frontapi`、`Dockerfile.backapi`、`Dockerfile.worker`，`linux/amd64`，无 `PROJECT` 构建参数。三个构建记录依次为 `01A0DCBD-9EDC-5B77-A49E-538F78D51E29`、`01A0DCC3-49E9-53C3-8DDE-DB2A45746ED7`、`01A0DCC3-4C01-5DFE-88AF-7583B7872294`，均成功且日志确认提交及 Dockerfile。
- 生产镜像摘要：FrontApi `sha256:552035b32f766fefa0e68682dace4637c046d5aa229e1b127bb35431b15a315b`；BackApi `sha256:a3d4eff38a1e9cea5fd1673b1ae9ff6aea146a1722bfd3417357453c3df27268`；Worker `sha256:b78eb8691895073dba8ac9cdb98e0a94b5ff446da7526d45ac6a3ba2efb6a3ab`。Front、Back 分别挂载专用运行 Secret；Worker 挂载 Back 的运行 Secret 至所需配置文件路径，停机宽限 130 秒。旧 ECS 停机后已启用 Front 的 Redis 消费者；Back 数据库结构就绪检查保持启用，探针超时 25 秒。三个 Pod 均无重启；Worker 启动日志无错误，但尚无任务执行结果证据。
- 出口与业务验收：当前 VPC 无公网 NAT，Front 和 Worker 到微信支付 `api.mch.weixin.qq.com:443` 均超时，到私网 SmsCore `172.27.182.18:3090` 可达。用户指定公网 NAT 和固定 EIP 在另一个任务中处理，本次只完成新零售部署与入口接入。因此登录、下单、支付回调、退款、短信真实投递、第三方白名单、Worker 任务结果及 24 小时观察均待验收；不得将 HTTP 200 的健康检查当作业务通过。

## 经销商查询（第五项）

- 目标：`agent-query` Namespace 中**一个** `agent-query-api` Deployment（0.5 CPU/1 GiB）、一个 ClusterIP Service，同时承载前台与后台接口；**无 Worker**。旧 ECS `i-2ze6v19gpeg6t864exra` 上的以旧换新不受影响。
- 正式 Host：`4l-api.svision100.com` 已指向新 ALB；尚未创建该 Host 的 Ingress，未接入正式流量。旧 `rsqapi-ft.svision100.com`、`rsqapi-bk.svision100.com` 是历史入口，不作为本次两个新服务部署。
- 源码：`/Volumes/SSD/work/mall/经销商查询/agent_query_api_net10`，`release` SHA `5fc6913727c7ab084424bb601f13ee7e5b4acd16`；合并宿主图片上传使用原有 OSS。ACR `agent-query-api` 构建成功，镜像 digest `sha256:064dc0aa46145cf44e907c5567f3bb607139fb17c7063c083e11aa4e0b111ea5`。
- ACS 已创建单体 Deployment 和 Service，Deployment 固定上述 digest，期望副本 **0**。先前试运行的旧镜像未通过 `/health/ready`：当前生产 MySQL 与 Redis 主机解析到公网 IP，Pod TCP 连接超时。试运行实例已停止；没有创建 Ingress。运行 Secret 已有数据库、Redis 等配置，但尚缺新宿主所需的 OSS 写入凭据；需受控补齐并验证。
- 上线门槛：MySQL、Redis 从 ACS 可达；OSS 配置安全下发且上传、读取验证；单体 API 的前后台登录、门店查询和维护验收；然后才扩到 1 并接入 `4l-api.svision100.com`。公网 NAT 由独立任务处理，本次不擅自创建。生产写入、回滚及 24 小时观察证据：待验证。

## 每项完成时补录

| 字段 | AI | 工单 | 积分 | 零售 | 经销商 |
|---|---|---|---|---|---|
| `release` SHA / 评审记录 | 待验证 | 待验证 | 待验证 | 待验证 | 待验证 |
| 镜像 digest / ACR 构建 run | 待验证 | 待验证 | 待验证 | 待验证 | 待验证 |
| 配置 Secret 版本 / 结构版本 | 待验证 | 待验证 | 待验证 | 待验证 | 待验证 |
| 旧服务与 Worker 停机核对 | 待验证 | 待验证 | 待验证 | 待验证 | 不适用 Worker |
| API 业务/回调验收 | 待验证 | 待验证 | 待验证 | 待验证 | 待验证 |
| DNS 前后/切换时间 | 待验证 | 待验证 | 待验证 | 待验证 | 待验证 |
| 24 小时观察/关键任务 | 待验证 | 待验证 | 待验证 | 待验证 | 无 Worker |

# 五项目发布记录

状态：预填的部署记录，所有「待验证」均为切换阻断项。只填资源 ID、版本和证据位置，不填配置值、密钥、手机号或客户数据。每项目分别记录实际授权、维护窗口、切换时间、24 小时观察起止和回滚决定。

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

- 目标：`new-retail` Namespace；`new-retail-front` 1 CPU/2 GiB、`new-retail-back` 0.5 CPU/1 GiB、`new-retail-worker` 0.5 CPU/1 GiB；旧 ECS `i-2ze68mprzc2jzea57xfz`。
- Host：`rs-store-api-front.svision100.com`、`rs-store-api-back.svision100.com`。旧 DNS 为 `39.105.188.147`；新 ALB 证书握手已验证，Host 规则尚无。
- 源码：`/Volumes/SSD/work/mall/新零售/newsale-api`；ACS 适配分支 `deploy/dotnet-acs-new-retail` 已推送 `1914b60`，业务基线为 `product/new-retail`，不可误用同远端积分商城的 `release`。三个 Release 编译、相关单测 10/10 通过；Docker 镜像构建未取得完整结果，容器运行未验收。最终生产 SHA、三个 digest、Secret/结构版本：待验证。
- 切换关键点：登录、下单、支付与回调、优惠券、订单状态推进、短信事件；支付超时状态不明时先查单再补偿：待验证。API/Admin 为容器内 HTTP 8080，具 `/health/live` 与 `/health/ready`；Worker 无 HTTP，Quartz 作业单实例内防重叠，退出最长等待 120 秒。**尚无新 Worker 禁用调度的交付参数**，不得在旧 Worker 退出前以一副本预启动。目标生产库的兼容结构仍需就绪探针实测，第三方 SDK 经代理的行为仍需逐项验证。
- 生产授权、外呼白名单、旧 Worker 交接、24 小时观察及回滚证据：待验证。

## 经销商查询（第五项）

- 目标：`agent-query` Namespace；`agent-query-front`、`agent-query-back` 各 0.5 CPU/1 GiB；**无 Worker**；旧 ECS `i-2ze6v19gpeg6t864exra` 上的以旧换新不受影响。
- Host：`rsqapi-ft.svision100.com`、`rsqapi-bk.svision100.com`。旧 DNS 为 `39.105.188.147`；新 ALB 证书握手已验证，Host 规则尚无。
- 源码：Apollo `/Volumes/SSD/work/mall/apollo/prod/api.netcore-net10`，当前功能分支基础 `6d93ae3`；最终 release SHA、两个 digest、独立库/Redis 前缀、Secret/结构版本：待验证。
- 切换关键点：旧门店接口和 Apollo 当前 `MiniappStore` 使用的表及业务字段不同，必须由代码会话完成独立宿主、契约/权限适配、迁移映射与测试；独立演练库数量/状态/坐标/图片/标签/权限一致，旧后台写入冻结及最终导入计划：待验证。
- 生产数据写入授权、增量数据回滚方案、24 小时观察及回滚证据：待验证。

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

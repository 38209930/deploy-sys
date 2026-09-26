# 资源与项目发布清单

状态：2026-09-26 只读盘点。`待验证` 不是默认值；填满并复核后才能进行该项目切换。域名为旧 ALB 上已发现的 Host，尚未验证业务所有回调地址和证书覆盖。

| 项目 / Namespace 建议名 | 旧 ECS | FrontApi 域名 / 规格 | BackApi 域名 / 规格 | Worker 规格 | 当前代码基线 |
|---|---|---|---|---|---|
| 新零售 / `new-retail` | `i-2ze68mprzc2jzea57xfz` | `rs-store-api-front.svision100.com` / 1 CPU 2 GiB | `rs-store-api-back.svision100.com` / 0.5 CPU 1 GiB | 0.5 CPU 1 GiB | `product/new-retail` `07f06c0`；最终 SHA 待冻结 |
| 积分商城 / `points-mall` | `i-2ze3w6i78cobsmmfo2y9` | `rsjf-front-api.svision100.com` / 1 CPU 2 GiB | `rsjf-back-api.svision100.com` / 0.5 CPU 1 GiB | 0.5 CPU 1 GiB | `origin/release` `43afaf4`；最终 SHA 待冻结 |
| 售后工单 / `service-order` | `i-2ze710cj1qpe7s7zv5sq` | `rsod-front-api.svision100.com` / 1 CPU 2 GiB | `rsod-back-api.svision100.com` / 0.5 CPU 1 GiB | 1 CPU 2 GiB | 本地 `master` `5cd022d`；领先远端 28 提交，最终 SHA 待冻结 |
| AI 自习室 / `ai-study` | `i-2ze2s8pzq0kvqu28iml8` | **不迁移**，FrontApi 保留 ECS | `rsst-back-api.svision100.com` / 1 CPU 2 GiB | 0.5 CPU 1 GiB | `master` `97ff88e` 加待评审本机业务改动；最终 SHA 待冻结 |
| 经销商查询 / `agent-query` | `i-2ze6v19gpeg6t864exra` | `rsqapi-ft.svision100.com` / 0.5 CPU 1 GiB | `rsqapi-bk.svision100.com` / 0.5 CPU 1 GiB | **无** | Apollo 功能分支 `6d93ae3`；接口/数据适配后冻结 |

合计 13 个 Deployment，9 CPU / 18 GiB。Namespace、仓库名是本轮建议命名，**尚未创建**；如与现有组织约定冲突，必须在资源创建前一次性修订本表。AI 的旧 FrontApi、经销商同 ECS 上的以旧换新不能因为本轮操作被停止。

2026-09-26 DNS 只读查询：新零售、AI、经销商的目标 Host 当前解析到旧 ALB IP `39.105.188.147`；积分商城、售后工单解析到旧 ALB IP `101.201.60.62`。各项目的前后端同 IP。正式变更前仍要核对权威 DNS、TTL 与是否存在并行解析记录。

统一在拟建 ACR 命名空间 `ruishi-dotnet-prod` 下使用以下仓库名。Kubernetes Deployment、API Service 采用同名；ServiceAccount 采用项目 Namespace 名。完整镜像地址和 digest 以 ACR 实际创建与构建结果为准。

| 项目 | FrontApi | BackApi | Worker |
|---|---|---|---|
| 新零售 | `new-retail-front` | `new-retail-back` | `new-retail-worker` |
| 积分商城 | `points-mall-front` | `points-mall-back` | `points-mall-worker` |
| 售后工单 | `service-order-front` | `service-order-back` | `service-order-worker` |
| AI 自习室 | — | `ai-study-back` | `ai-study-worker` |
| 经销商查询 | `agent-query-front` | `agent-query-back` | — |

## 每项目必须填满的发布记录

在本文件或独立的项目发布记录中逐项填写非秘密值，证据位置记录为工单/受控路径，不复制配置内容：

| 项目字段 | 当前状态 / 完成条件 |
|---|---|
| 源码与评审 | 仓库 URL、最终 `release` SHA、纳入的开发分支/本机业务修改、评审和测试结果：待验证 |
| 构建 | 三或两个独立 ACR 仓库、构建规则、构建 run、Linux x64 镜像 digest、镜像签名/扫描状态：待验证 |
| 运行配置 | 配置加载顺序、生产 Secret 名/版本、非秘密参数版本、数据库标识、Redis 前缀、OSS 目录、Cookie/Data Protection 持久化方式：待验证 |
| 外部依赖 | 目的域名/端口、调用 SDK、代理适配、超时/重试/幂等、回调地址、旧新出口 IP 双白名单及核对证据：待验证 |
| 旧服务 | systemd/容器实例及自启方式、Worker 停机命令、在途任务与锁、API 保留时间、回滚启动命令：待验证 |
| 网络 | 私网数据库/Redis/Mongo/SmsCore 连通性、出口代理允许/拒绝测试、ALB 证书与 Host 路由、DNS TTL：待验证 |
| 数据 | 旧新版本并行兼容、生产结构版本、连接池总数；经销商独立库迁移记录：待验证 |
| 上线 | 维护窗口、授权记录、API 业务验收、Worker 首次任务、24 小时观察起止、切换及回滚决策：待验证 |

## 资源隔离与默认规格

- 每项目单独 Namespace、ServiceAccount、Secret、三或两个镜像仓库、日志标签、业务任务锁、精确 Host Ingress。API Service 仅 `ClusterIP`，Worker 无 Service/Ingress。
- `requests = limits`，初始值如上；均为 `default` 算力、单副本、`Recreate`、无 HPA。Worker 停止自动拉起旧实例并确认在途任务后才能在 ACS 扩到 1。
- 资源配额建议上限：新零售和积分商城各 3 CPU / 6 GiB；售后工单 3.5 CPU / 7 GiB；AI 2 CPU / 4 GiB；经销商 1.5 CPU / 3 GiB。上线前用 ACS 支持的 ResourceQuota 字段及诊断 Pod 需求复核；配额不代替单副本与幂等保证。
- 后台 API 沿用现有身份与权限体系。登录/短信接口限流与 ALB 前置鉴权的具体配置应由代码会话测试证实；不要把未验证阈值直接施加到全部后台路由。
- ALB 的 443 监听与既有 Java Host 共用，新增规则必须精确匹配上表 Host。不要调整已有 Java Namespace、Ingress、证书、规则或共享监听器 ACL。

## 共享资源的变更前后核对

每次修改 ACR 凭据助手、ALB 规则或证书，保存只读快照：变更前/后资源 ID、Namespace 列表、`watchNamespace`、`serviceAccount`、Ingress Host、证书 ID 和时间。只允许追加本轮项目所需条目，禁止通配所有 Namespace 或 ServiceAccount。修改后复核七个 Java Namespace 的 Deployment Ready 数与精确 Host 转发结果。

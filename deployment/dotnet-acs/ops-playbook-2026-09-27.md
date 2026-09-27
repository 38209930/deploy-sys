# 北京 ACS 生产运维值班手册

状态：本手册供实际值班人员按需执行，**不代表已建立自动巡检、后台常驻 AI 值班或 24×7 告警**。先阅读[2026-09-27 只读复盘](production-review-2026-09-27.md)的证据边界；下列工作负载表是 00:30 的历史基线，本次 08:32 未能读回 ACS 实时状态。基础规则见[运维备忘录](operations.md)、[发布手册](runbook.md)、[出口手册](egress-nat.md)。所有内容不含凭据、配置值和客户数据。

## 1. 环境基线（速查）

每次变更前以 API 重新读回，不凭本表断言现状。

| 对象 | 值 |
|---|---|
| 生产账号 / Profile / 地域 | `1442361567788059` / `ruishi-prod-acr` / `cn-beijing`（默认 Profile 是别的账号，禁止省略） |
| ACS 集群 | `ruishi-prod-acs` / `cebc88343a44b4d759aa983a47b787835` |
| ACR | `cri-73ffxebpi6ruw6sn`；命名空间 `ruishi-java-prod`、`ruishi-dotnet-prod`（≠ K8s Namespace） |
| 入口 ALB | `alb-olyb9enxszy3f42nnn`，各项目精确 Host Ingress |
| 公共出口 | NAT `ngw-2zetnd6golba2sju2q7jo`；EIP `eip-2zeapte07xmvayr4852h5`（`39.96.67.239`，10 Mbps）；SNAT 表 `stb-2zewws9r3mpb7ne3b6to8` **有且只有两条**（`172.31.240.0/24`、`172.28.64.0/24`） |
| 路由表 | 旧业务 `vtb-2ze9057j04btdfr3bofhy`（**无默认路由**）；NAT 系统表 `vtb-2zebvv47akvfr0cq15njq`；新出口表 `vtb-2zedknif7nxu7z397b4o6`（有 `0.0.0.0/0`） |
| 新出口 Pod vSwitch | 北京 k `vsw-2zevd832gq3313j6gv5sj`（`172.31.240.0/24`）；北京 i `vsw-2zesy6off4gy39tqripzp`（`172.28.64.0/24`）；选址注解 `network.alibabacloud.com/vswitch-ids` |
| 旧 Pod vSwitch | `vsw-2zeagdbk8hizkkdw0ns42`（k）、`vsw-2zec5qkbaiafqu3pyuamo`（i）；**无公网出口** |
| 短信 | 设计路径为 Pod → 私网 SmsCore `172.27.182.18:3090`（ECS `i-2ze38hdx1sufodad2kz0`）；该 ECS 公网 IP 为 `39.107.141.33`，供应商实际看到的出口 IP 待核对；项目生效短信路由仍需逐项取证 |

### 工作负载基线（2026-09-27 00:30 起的期望状态）

| 位置 | 工作负载 | 期望 |
|---|---|---|
| 新网段 `172.31.240.x` | ai-study back/worker；service-order front/back/**worker**；points-mall back/worker；yangu-api；m1x-api；m1x-worker | 各 1/1、Running、重启 0 |
| 旧网段 `172.31.239.x` 等 | stopmp-api；etbst-api；ddmp-api；new-retail front/back/worker；agent-query-api | 各 1/1；**当前无公网出口**（见 §5 待办 4） |
| 零副本 | dgye-api、vet-api | 保持 0，Ingress 存在不代表可服务 |
| 旧 ECS | 2026-09-27 08:32 OpenAPI 读回：AI、售后 ECS `Stopped`，积分 ECS 和 SmsCore ECS `Running`；积分 FrontApi 及 Redis 消费者的进程状态、website/以旧换新 ECS 均未在本次复核中验证 | 不擅自开机/停机；运行中的 ECS 不等于应用服务已启动 |

2026-09-27 08:32 入口基线：`.NET` 九个 Host（`rsst-back-api`、`rsod-front-api`、`rsod-back-api`、`rsjf-back-api`、`ns-front-api`、`ns-back-api`、`4l-api`、`rsqapi-ft`、`rsqapi-bk`，均加 `.svision100.com`）的 `/health/ready` = **200**。Java 的 `stop-mp-api`、`et-bst-api`、`ddmpapi`、`rsapi`、`m1x-api` 曾以 **401** 作为需认证的健康端点基线，巡检时重新核对。探测须使用真实域名和正确 SNI；仅给 ALB 域名加 Host 头的 TLS 失败不足以判断业务故障。

## 2. 每日巡检（约 5–10 分钟，只读）

依次执行，任何一步偏离基线即进入 §6 故障流程，先定位再动手：

1. **身份**：`sts GetCallerIdentity`，确认账号 `1442361567788059`（命令见[API 说明](aliyun-api-operations.md)）。
2. **工作负载**：短时 kubeconfig（60 分钟、0600 权限、用完即删）读 `kubectl get pods -A -o wide`：对照 §1 基线核对副本、Running、重启数、Pod 网段。重启 > 0、非预期网段、Pod 年龄异常缩短都要查原因（先看事件，别只看状态）。
3. **入口**：按 §1 域名清单逐个 `curl https://<真实域名>/health/ready`，核对 200/401 基线。
4. **各项目 Worker**：先读回副本与 Pod，再按项目查看有界、脱敏日志及任务结果。售后 Worker 可用 `kubectl logs deploy/service-order-worker -n service-order --since=24h` 检查工单发货、退款、短信补偿、ERP 同步四类任务；AI、积分、新零售 Worker 也有运行历史，须分别核对，不能只巡检售后。
5. **ECS 与短信路径**：`DescribeInstances` 确认 SmsCore、积分商城旧 ECS 等 Running；SmsCore 私网 3090 可由任一新网段 Pod `kubectl exec` TCP 探测（每周至少一次，见 §4）。

巡检结果一句话记录到值班日志（日期 + 结论 + 异常项），连续无异常不展开。

## 3. 每周任务

| 任务 | 内容 | 判据 |
|---|---|---|
| 网络漂移核对 | 读回 NAT/EIP/SNAT/三张路由表 | NAT `Available`；EIP `InUse`@10Mbps；SNAT 仍只有两条；旧业务表仍无默认路由；无新增 DNAT |
| 费用 | 账单中心核对 NAT/EIP/ACS/ACR 费用 | NAT 约 ¥0.1955/小时；首月累计 400 元预警、600 元升级复核（只报管理员，不自动断网） |
| EIP 带宽 | CloudMonitor 出带宽峰值 | 持续 5 分钟 > 7 Mbps 预警；> 8.5 Mbps 且有业务失败时处置 |
| ACR | 实例存储、构建队列、镜像 digest 与现网一致性 | 经济版 1 并发构建、命名空间 5 个上限；构建必须串行 |
| 资源用量采样 | 用 [resource-snapshot.sh](resource-snapshot.sh)（两次 cgroup 采样，只读）采一轮全部 Pod 的内存/RSS/CPU | 内存（含缓存）超过 limit 的 **80%** 即评估扩规格；重点盯 `ddmp-api`（1Gi 档中最高，2026-09-27 采样 53%/RSS 44%）。ACS 无 metrics-server，`kubectl top` 不可用 |
| ECS 盘点 | 实例清单与状态对照 §1 | 出现非预期 Stopped/新增实例立即报管理员 |

## 4. 每月任务

1. **证书**：核对 ALB 上两组域名的证书有效期（控制台或 API），到期前 30 天提交续期计划；续期先在新 ALB 指定 Host/SNI 验证再改正式入口。
2. **配置与镜像版本对账**：读回各 Deployment 的镜像 digest，与[发布记录](release-records.md)比对，出现"文档外的镜像"即查明来源。
3. **SmsCore 私网路径复测**：从新、旧网段各选一个 Pod，TCP 探测 `172.27.182.18:3090`；短信始终走私网，公网出口变更不影响它。
4. **数据库/Redis/Mongo 回程抽测**：参照[网段记录](network-constraints-2026-09-26.md)的目标清单做 TCP 连通抽测（只建连，不读数据）。
5. **遗留项评审**：过一遍 §5 待办清单，推进或向管理员汇报。

## 5. 当前遗留项（按优先级）

1. **售后 Worker 24 小时观察**（2026-09-27 启动）：观察期内每日巡检第 4 步必做；重点看首个真实到期任务的业务结果（发货/退款/短信补偿），由业务侧确认结果，运维只确认任务调度与无错误。
2. **告警渠道未落实**：NAT/EIP/ALB/工作负载的告警接收渠道、通知人尚未核验——这是当前最大的盲区。优先与管理员确定接收方式（短信/钉钉/邮件），配置后做一次实测。
3. **Yangu、M1X 出口补验**：两项目有迁入新网段的历史记录，但微信/支付/供应商白名单和真实 SDK 调用尚无验收证据；按[出口手册](egress-nat.md)第 3 节逐项补验，尤其核对供应商侧是否要求把 `39.96.67.239` 加白。项目当前是否有用户，应由流量和业务记录确认。
4. **旧网段项目无公网出口**：stopmp、etbst、ddmp、new-retail、agent-query 的 Pod 在旧网段，旧路由表无默认路由，**这些 Pod 现在出不了公网**。new-retail 此前已记录微信支付超时。若业务需要其公网能力，按项目门槛（短信通道、白名单、任务幂等）迁入新网段；不需要则维持现状。禁止用"加路由/SNAT"代替项目迁移。
5. **积分商城 Front 迁移**：旧 Front 在 ECS 且启动了 Redis 消费者；迁移前必须单独评审重复消费与幂等（见[发布记录](release-records.md)积分商城节），不能套通用流程。
6. **DGYE、VET 零副本**：与管理员确认是长期停用（考虑清理 Ingress 与镜像，省 ACR 存储）还是待部署。
7. **配置版本与源码 SHA 对账**：各项目 `release` SHA、Secret 版本仍未完整入册（[发布记录](release-records.md)汇总表大量"待验证"），每月任务第 2 步逐步补齐。

## 6. 变更 SOP（所有生产写操作）

1. **授权**：向管理员确认对象、范围、窗口；资金/短信/共享网络相关必须逐次确认。
2. **快照**：变更前保存 resourceVersion、UID、镜像 digest、注解、Secret 名称（不读值）、Pod IP、相关云资源的 RequestId。
3. **最小范围**：只动目标 Deployment/Ingress/Secret 版本；共享 NAT、SNAT、路由、EIP、acs-profile、ALB 共享监听器**永不作为单项目变更对象**。
4. **验证**：按对象类型验证——API 看 Ready + 真实域名基线码 + 有界日志；Worker 看 Ready + 任务 start/completed + 心跳；迁移类另验新 Pod 网段和出口 IP。
5. **记录**：在 `deployment/dotnet-acs/` 新增带日期的变更记录（时间、对象、前后状态、证据、回滚入口），更新[交接快照](HANDOVER-2026-09-26.md)对应行，中文 commit 并 push。
6. **观察**：变更后 24 小时内每日巡检加看该项；资金类覆盖一个关键任务周期。
7. **回滚**：单项目只回滚该项目（缩副本/恢复注解/回滚镜像与配套 Secret 版本）；Worker 回滚先停新、确认 Pod 退出、查在途任务，再启旧；资金/短信结果不明先按业务单号查询，**永不盲目重试**。

## 7. 故障响应（速查树，细则见[运维备忘录](operations.md)）

- **单一 Pod 异常**（重启/CrashLoop/Ready 失败）：describe 看 events → 有界日志 → 判断镜像/配置/依赖 → 修不了先回滚该项目，不反复重启掩盖问题。
- **某域名异常**：先确认解析与证书，再查 Ingress → Service → Pod；401/403 要结合认证基线解释（Java 健康端点 401 是正常）。
- **公网外呼失败（新网段项目）**：按序查 NAT 状态 → SNAT 命中 → EIP 绑定与带宽 → DNS/TLS → 供应商白名单；单项目问题只回滚该项目选址，不动共享出口。
- **旧网段项目本就无公网出口**：这不是新故障；如业务突然需要公网能力，走 §5-4 的迁移门槛，不当场改网络。
- **Worker 疑似重复执行**：立即停新调度，核对旧服务状态、锁拥有者与租期、幂等记录，已产生的外部副作用先查询后处理，不盲删锁、不批量补跑。
- **支付/退款/短信超时**：先按业务单号向平台/供应商查结果，再决定重试；重试必须带原幂等标识。
- **ECS 意外 Stopped**：不擅自开机，先报管理员确认（历史上有主动停机的先例，以 ActionTrail 和管理员确认为准）。

## 8. 安全红线（每次操作前默念）

1. 临时 kubeconfig 只存 0600 临时文件、不打印、不提交、用完即删；过期重新生成。
2. 不读取、不打印、不落盘任何 Secret 值、连接串、令牌、手机号、支付报文；日志过滤后再展示。
3. 共享网络对象（NAT/EIP/SNAT/路由表/acs-profile/ALB 共享监听）变更必须管理员逐次授权并留前后快照。
4. 旧 vSwitch 永不解绑回系统表；SmsCore 的出口路径永不改动；不把新 EIP 当 SmsCore 白名单地址。
5. 生产镜像只用 digest；不在镜像里放生产配置；配置只经 Secret 受控下发。
6. 本仓库只提交文档与不含秘密的记录；`deploy.local.env` 等本地/密钥文件永不入库。

## 9. 值班协作方式

- **值班执行人**：按本手册实际触发只读巡检；生产变更按 §6 留痕。本文档本身不会自动安排巡检或告警。
- **服务器管理员（您）**：授权与复核、业务验收结论、告警接收渠道、供应商/第三方账号侧动作（白名单、DNS 权限——当前 CLI 对 svision100.com 是 `IncorrectDomainUser`，DNS 切流必须由您或授权账号操作）。
- **升级路径**：巡检异常 → 我定位并给出结论与建议 → 需要写操作时报管理员批准 → 执行并记录。资金类异常无论大小，处置后立即同步管理员。

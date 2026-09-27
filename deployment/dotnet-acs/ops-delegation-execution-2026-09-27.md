# 委托任务执行报告：ALB 5XX 归因、售后 Worker、旧网段出口、告警

执行时间：2026-09-27 09:00–11:30 CST。依据[任务书](ops-delegation-alb-worker-egress-alerts-2026-09-27.md)（提交 776f948）。全程显式 Profile `ruishi-prod-acr`、账号 `1442361567788059`（STS RequestId `01A0E0BD-3C8F-52A7-AB7D-801F302656B4`）、地域 cn-beijing；ACS 经短时 kubeconfig，未读 Secret 值，未执行任何生产写操作（唯一例外见 §D，已于同日获管理员授权并记录）。**本报告最重要发现：§B-4 的 SmsCore 白名单拒绝新网段来源，属现行生产缺陷。**

## A. ALB 09-26 5XX 归因

方法：CMS `acs_alb` 60 秒粒度，窗口 09-26 00:00–24:00 CST，监听 `lsn-3hl3j4qtjt8b1z7jkl`（ALB `alb-olyb9enxszy3f42nnn`），指标 `DualStack_ListenerQPS` 与 `DualStack_ListenerHTTPCode500/502/503/504`（每秒速率积分换算分钟计数）。与任务书 09:15 基线（总请求≈30,322、5XX≈683）同口径复核一致。

### 逐峰值表

| CST 时段 | 总请求 | 500/502/503/504 | Host 或无法归因 | ALB 与后端状态 | 对应变更时间（ActionTrail） | 根因可信度 | 现存? | 建议 |
|---|---|---|---|---|---|---|---|---|
| 00–07 时 | 合计≈255 | 0/0/23/0 | 无法归因（量级为个位数/时，与 dgye、vet 两个零副本 Host 被探测的特征一致） | 两 Host 服务器组为空 → ALB 无健康后端 503 | 无变更 | 推测（特征吻合） | **是（设计态）** | 与 DGYE/VET 去留一并决策 |
| **11:34–11:52** | 该小时 3,386 | **211**/3/1/1 | 无法归因到 Host | 后端应用 500（ALB 转发正常，上游连接错误全天为 0） | 11:33:10 CreateInstance（Pod 重建）；11:34:07 ReplaceServersInServerGroup；11:45:23 / 11:46:39 操作者对 RDS、Redis 调整白名单 IP（自用 IP 114.86.9.82）；11:58–11:59 二次 Pod 替换 | 低-中：时间强相关于 Pod 重建窗口，机制不可证 | 否（11:52 后恢复） | 无需修复；详见下方"归因上限" |
| **15:52–15:54** | 该小时 2,739 | 8/0/**181**/0（15:53 峰值 130/分钟） | 无法归因到 Host | 无健康后端型 503 特征 | **该窗口无任何 ALB/K8s 变更记录**；15:55:56 起连续 CreateInstance（新零售 Deployment 于 15:55 前后创建，见发布记录） | 推测：发布窗口内后端未就绪的探测/请求 | 否 | 无需修复 |
| **19–23 时** | 合计≈4,936 | 0/0/**155**/0 | 发布记录指向 rsod-front/back（撤下窗口），无 Host 级日志实证 | 规则与服务器组增删期间的无健康后端 503 | **21:47:15–21:58:55 DeleteRules ×6**；21:49:21/21:51:53 本监听 CreateRules；21:59:45 DeleteServerGroup ×5；22:27–22:33 另一 ALB（明眸 alb-ay59r13w826vczc55d）的规则操作，与本入口无关；**23:39:48 本监听 CreateRules（售后 Ingress 恢复）** | 中-高：与[发布记录](release-records.md)记载的"售后 Ingress 因短信旧通道撤下、后恢复"时间吻合 | 否 | 无需修复 |
| 全天底噪 | — | 0/0/每小时 1–17/0 | 无法归因（量小） | 同 dgye/vet 空后端特征 | 无 | 推测 | **是（设计态）** | 同上 |

### 归因上限（证据边界）

- **ALB 访问日志未启用**：`ListLoadBalancers`/`GetLoadBalancerAttribute`（RequestId `01A0E0C8-CA96-53DB-8B92-E1A0F6E423CE4`）均无访问日志启用字段；账号下 SLS 仅有 CMS Prometheus 托管项目（`workspace-default-cms-…`），无 ALB 日志库。**结论：09-26 的 Host 级、URL 级归因不可追溯**；现在启用日志不能补回当天数据。启用属付费变更，需授权后另报范围/保存期/预算。
- CMS 监听级指标无 Host 维度；UpstreamConnectionError 全天为 0，支持"503 以 ALB 无健康后端为主、500 为后端应用返回"的区分，但不指向具体 Host。
- 当前读回：443 监听 16 条转发规则与 14 个 Host 对应关系完整；12 个服务器组后端 `Available`，`sgp-7hdzcemxfhtt00j5yu`（vet-api）与 `sgp-m8mrsq403rxskekauo`（dgye-api）为空——与零副本一致，是底噪 503 的确定性来源，不是故障。
- 结论：**无现存的非设计态 5XX 问题，无需修复单**。

## B. 售后工单 Worker 验收（中间态报告，观察期至 09-28 00:21 CST）

### 镜像链（已闭合）

Deployment 镜像 `sha256:a80e8b0e…187474`（ruishi-dotnet-prod/service-order-worker）← 构建记录 `01A0DD19-A828-565F-BF04-1A9EA71BCC30`（SUCCESS，仓库 cri-73ffxebpi6ruw6sn，构建日志首行 `commit info: release c9487d7 [origin/release] 配置售后工单三端 ACR 独立构建`）← 源码 `release c9487d7`，与[验收整改记录](acceptance-remediation-2026-09-27.md)的本机源码基线一致。Pod imageID `sha256:e7416cb0…` 为 ECI 运行时表示（解包 digest），与仓库 manifest digest 不同属正常表示差异，不影响链路成立。任务书 09:15 提出的"本机 SHA 不可当现网镜像"疑虑就此解除。

### 任务矩阵（2026-09-27 00:21 启动至 11:30 CST，16,421 行日志，start/completed 全配对，仅 1 条业务错误）

| Job | 观察节拍/生效 Cron | 最近与下次触发 | 执行证据 | 实际业务事件 | 对端结果 | 幂等/重复 | 结论 |
|---|---|---|---|---|---|---|---|
| Task4JuShuiTanToken | 默认 00:05（源码值，生产配置未核对） | 未观察到；下一计划点 **09-28 00:05** | — | — | — | — | **待观察**（24h 窗口覆盖该点后回填） |
| Task4ServiceOrderRefund | 每 30 秒（:00/:30；日志实证） | 最近 11:2x；持续 | 1,279 start / 1,279 completed | 10:18 有真实售后同步事件（as_id 910***） | 聚水潭拉取正常（"全量同步完成"） | 无重复执行迹象（单副本+fireInstanceId 连续） | 调度通过；业务待验收 |
| Task4ServiceOrderFactoryShipper | 每 30 秒（:15/:45） | 持续 | 1,280/1,280 | 每次扫描返回"发货单-扫描成功"（近期 0 条待办） | — | 同上 | 调度通过；业务待真实事件 |
| Task4ErpSyncCompensation | 每 30 秒（:10/:40） | 持续 | 1,279/1,279 | **10:30:10 "处理数量: 1"**（首个真实补偿事件） | 待业务确认 | 同上 | 调度通过；对端结果待业务回填 |
| Task4SmsRetryCompensation | 每 60 秒（:00） | 持续 | 640/640 | **10:18:30 真实短信发送失败 1 条**（traceId `cd6692ec…`）；待重试 2 条于 10:29 归零（终态） | **SmsCore 返回 401 `auth.ip_not_allowed`，识别来源 IP 172.31.240.149** | 重试由固定队列接管，未重复发送 | **调度通过；业务阻断（见下）** |

### 现行生产缺陷：SmsCore 白名单未含新 Pod 网段（阻断）

10:18:30 一条真实售后通知短信（业务事件 `102734:Pass:910***…:BUYER_RECEIVED:WAIT_BUYER_RETURN_GOODS`，模板 `102734-ChangeGoods-Pass-2`，手机号应用侧已自脱敏）发送失败：**SmsCore 以 401 `auth.ip_not_allowed` 拒绝来源 `172.31.240.149`**。此前网络层 TCP 验证通过，但 SmsCore 应用层白名单只含旧网段，未含 `172.31.240.0/24`、`172.28.64.0/24`。影响范围：**所有已迁新网段项目的短信发送**（售后、AI、积分）；AI/积分近期无发送行为故未在日志显现，缺陷是确定性的。重试 2 条已于 10:29 进入终态（该 2 条通知未送达，需业务侧评估是否人工补发——补发属业务动作，运维不触发）。

**后续处置（11:26 更新）**：管理员已授权并完成两条新 Pod 网段白名单写入，详情见文末“授权变更补记”。这只解除 `auth.ip_not_allowed` 的已知阻断；仍须等待下一条自然业务短信，或由业务所有人发起测试短信，核对 SmsCore 受理和供应商结果。终态的历史通知不得由运维自动补发。

**正向证据**：错误报文显示该应用启用的短信通道集合为**仅 `ruishi:SmsCore`**（"全部通道发送失败"仅列出该通道）——售后项目旧直连通道（创蓝/云瓣）未生效，这是 C 项门槛所需的非秘密证据之一（其余项目仍需逐一取证）。

### 旧 Worker 唯一性

旧 ECS `i-2ze710cj1qpe7s7zv5sq` Stopped（管理员 09-26 23:51 主动停机确认）；systemd 自启状态无法自停止实例读取，以"该实例不开机"为唯一性边界；新 Worker 单副本，restart 0。

## C. 旧网段五项目公网依赖矩阵与迁移判定

Pod 位置 11:0x 读回（副本/重启全部正常）：STOPMP `172.31.239.13`、ETBST `.239.12`、DDMP `.239.10`、新零售 Front `172.28.53.146`/Back `.239.26`/Worker `.239.29`、经销商 `172.31.239.39`（**今日重建过一次，IP 由 .38 变 .39**，原因无变更记录，已列入观察）。私网依赖（MongoDB `dds-2ze1a633d27d8ee41/42…:3717` 等）日志可见，均走私网；两新网段的历史 TCP 验证不等于认证级验证，逐项目仍按门槛核对。

| 项目/角色 | 现网镜像 digest（前 12 位） | 生效公网依赖证据 | 旧短信直连停用证据 | 判定 |
|---|---|---|---|---|
| STOPMP `stopmp-api` | `1c255611be89` | 近 3000 行日志仅见私网 MongoDB；无已证实公网调用 | 待证据 | **待证据**——维持旧网段 |
| ETBST `etbst-api` | `efc2382dce05` | 同上 | 待证据 | **待证据** |
| DDMP `ddmp-api` | `04986d9805e0` | 日志无外呼线索 | 待证据 | **待证据** |
| 新零售 Front/Back/Worker | `552035b32f76`/`a3d4eff38a1e`/`b78eb8691895` | [发布记录](release-records.md)：无 NAT 时 `api.mch.weixin.qq.com:443` 超时（历史实证）；在用业务，支付/退款为核心链路 | 待证据 | **需要迁移（P1）**——先补门槛证据，见变更单（待授权） |
| 经销商 `agent-query-api` | `064dc0aa4614` | 地图/图片公网调用属待验收功能（发布记录）；OSS 走私网端点 | 不适用（无短信发送场景证据） | **待证据**（业务确认地图功能是否启用及供应商） |

### 变更单（草稿，逐 Deployment 独立提交，**均待授权后执行**）

- **对象**：`new-retail/new-retail-front` → `new-retail-back` → `new-retail-worker`（一次只迁一个，前一结论形成后再下一个）。
- **当前注解**：三个 Deployment 的 `network.alibabacloud.com/vswitch-ids` 均为**无**（运行时由 acs-profile 兜底落旧 k）；**回滚值=移除该注解**。
- **目标注解**：`vsw-2zevd832gq3313j6gv5sj,vsw-2zesy6off4gy39tqripzp`。镜像/配置/副本/Ingress/Service 不变。
- **执行前置门槛（未满足不执行）**：① 新网段 SmsCore 白名单已写入，但实际短信成功证据仍待取得；② 微信支付侧确认无需商户 IP 白名单或已完成配置；③ Worker（new-retail-worker）确认旧 ECS Worker 无自启、任务幂等；④ D 项告警触达测试通过（任务书要求）。
- **验证清单**：新 Pod IP ∈ 两新 /24；出站来源=39.96.67.239；MySQL/Redis/Mongo/SmsCore 私网可用；真实 SDK 低风险调用（如登录、查单）或业务脱敏结果；`ns-front/ns-back` Host 基线 200；24 小时观察。
- STOPMP/ETBST/DDMP/经销商：无变更单——判定为待证据，取得实际启用公网调用清单（经授权的配置只读导出或业务确认）后再定。

## D. 告警接收与规则

### 现状盘点（只读）

- 指标告警规则：**0 条**（`DescribeMetricRuleList` 为空）。
- 联系组：1 个（`ack_Default Contact Group`，ACK 告警中心同步）；联系人：1 个（`ack_svision100`），其 **Mail/SMS 通道均为 PENDING（未验证）**（RequestId `01A0E0D5-2767-5154-A7E7-0BD20AEB897E`）。
- 结论：告警覆盖为零、接收通道未验证——D 项当前**阻断**，C 项生产迁移按任务书暂缓至触达测试通过。

### 可实施规则表（阈值均为待确认初值；平台能力已核实）

| # | 资源/指标 | 条件（CMS 可实现形式） | 级别 | 备注 |
|---|---|---|---|---|
| 1 | ALB `DualStack_ListenerHTTPCode5XX`（acs_alb，实例 alb-olyb9…） | 目标为 5 分钟 5XX 请求数 > 20；API 阈值待换算 | P1 | 该指标官方单位为 Count/s，不能直接把 5 分钟 `Sum > 20` 当作请求总数。先用历史窗口验证 CMS 聚合值与真实计数的换算，再写规则；低流量抑制也须用实际可配置能力核对。 |
| 2 | NAT `BWRateOutToOutside`（acs_nat_gateway，ngw-2zet…） | 5 分钟 Average > 7 Mbps（7,000,000 bps） | P2 | 对应 10 Mbps 上限 70% 预警；原文 8,750,000 bps 为算术错误，已修正。 |
| 3 | NAT 同指标 | 5 分钟 Average > 8.5 Mbps 且有业务失败 | P1 | CMS 无复合条件，升级路径为人工（收到 P2 后查业务失败率） |
| 4 | NAT `ErrorPortAllocationRate` | > 0 持续 1 周期 | P1 | 端口分配失败即异常 |
| 5 | NAT `DropTotalPps` | > 0 持续 3 周期 | P2 | 丢包趋势 |
| 6 | Pod 非 Ready / 重启增加、内存 >80% limit | **CMS 不支持 K8s 指标**；metrics-server 已就绪但无告警链路 | — | 两条实现路径：a) 值班每日巡检 + 扩展 resource-snapshot.sh 输出超限清单（零成本，已可用）；b) 接入 ARMS Promethues 告警（集群已存在 CMS Prometheus workspace，接入状态待证据，可能产生费用）。建议先 a 后评估 b |
| 7 | 售后 Worker 到期任务无完成、失败队列增长 | 需应用日志进 SLS（付费）或业务系统侧告警 | P1 | 待授权与业务侧方案 |
| 8 | EIP 带宽（等同 #2，同源指标） | 同 #2 | — | 与 #2 合并实施 |

指标单位按[阿里云 ALB 监控说明](https://help.aliyun.com/en/slb/application-load-balancer/alb-monitoring-and-alerting)与[公网 NAT 监控说明](https://help.aliyun.com/en/nat-gateway/user-guide/view-monitoring-data)复核。规则表是实施草案，尚无联系人验证或写入授权。

### 待授权清单（D 项）

1. 主/副接收人、工作时间外路径、升级链（联系人信息不写入仓库）。
2. 联系人通道验证（PENDING→已验证）与一条无业务副作用的通知测试。
3. 规则写入授权（#1–#5 为免费指标规则；#7 需 SLS 付费日志，另行报价）。

## 统一结论汇总

| 项 | 结论 | 下一步责任人 |
|---|---|---|
| A ALB 5XX | **通过（含证据上限说明）**：三个峰值窗口全部定位时间线；因访问日志未启用，Host 级归因不可追溯；无现存问题 | 运维（已交付）；日志启用待管理员决策 |
| B 售后 Worker | **部分通过，业务层待验收**：调度层通过、镜像链闭合；SmsCore 两条新网段白名单已补，实际新短信受理及历史失败通知的业务处理仍待确认 | 业务所有人核对历史终态通知与 10:30 ERP 补偿结果；运维 09-28 00:21 后回填 24h 与 JuShuiTanToken |
| C 旧网段出口 | **待证据/待授权**：新零售需迁移（P1）但门槛未满足；其余四项目待证据 | 业务所有人对 STOPMP/ETBST/DDMP/经销商做公网调用清单确认；新网段短信实际成功、告警触达等门槛通过后逐单执行 |
| D 告警 | **阻断（无接收人、通道未验证、规则 0 条）**；可实施规则表已提交 | 管理员提供接收人与写入授权 |

停手条件遵守情况：未改共享网络、未扩大 SNAT、未读 Secret、未触发短信/资金、未为测试制造错误。本轮唯一生产写操作为已授权的 managed-metrics-server 安装（前序记录）。

## 授权变更补记：SmsCore 新网段白名单（2026-09-27 11:26 CST）

管理员在本次会话中明确授权：仅在 SmsCore 生产库 `sms_ip_whitelists` 新增并启用 `172.31.240.0/24`、`172.28.64.0/24`，保留旧规则，不主动补发短信。经私网 SSH 到 SmsCore ECS `i-2ze38hdx1sufodad2kz0`，一次性程序在服务器内存中使用现有运行配置建立数据库连接；连接串和密钥未输出或复制。写前全量规则快照保存于该 ECS 的 `/root/ops-snapshots/smscore-whitelist-20260927.json`（权限 600）。

- 写前：19 条规则，两条目标 CIDR 均不存在。
- 事务写入后独立读回：21 条规则；两条目标规则 `app_id=''`、`ip_type='internal'`、`enabled=1`，各一条；旧 19 条逐字段不变。
- SmsCore PublicApi `127.0.0.1:3090/health/ready` 返回 200。未发送短信、未重启服务、未修改 NAT 或项目配置。
- 该白名单为**全局来源规则**：两个网段内的请求可通过 IP 门槛，但仍须通过 SmsCore 应用 API Key、HMAC、时间戳和 nonce 校验。尚无变更后的真实短信受理或供应商投递证据；对已进入终态的两条历史通知不作自动重试。
- 原报告有一条可定位的 `auth.ip_not_allowed` 请求和两条重试队列终态记录；两条队列项是否对应两个独立短信事件、是否需要补发，须由业务记录按事件 ID 核对，不能仅凭队列数量断言“两名用户均未收到短信”。

本补记为原委托任务收尾后的独立授权变更；上文 10:18 的故障及原任务“只读取证”口径均作为历史事实保留。

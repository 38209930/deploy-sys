# ACS 交接验收整改记录（2026-09-27 09:07 CST）

范围按[验收清单](acceptance-review-2026-09-27.md)第 4 节。账号 `1442361567788059`，集群 `cebc88343a44b4d759aa983a47b787835`。本轮仅只读云/ACS 查询和本地脚本修改；未读 Secret、未写生产库、未发送短信或资金请求、未启停副本或修改网络。云端状态是查询时点的快照。

| 项目 | 本轮证据、边界与结论 |
|---|---|
| 资源脚本 | 修复 v1 纳秒与 v2 微秒、v1 `rss` 与 v2 `anon` 显式字段、每次独占临时目录及退出清理。模拟 v1/v2 与命令失败均通过，临时目录无残留。09:07 ACS 17 容器只读采样成功，最大 CPU/limit 约 1.7%，DDMP 550.2 MiB/1 GiB，Yangu 559.6 MiB/2 GiB；仅 1 秒窗口。`kubectl top` 的售后 Worker 160Mi 与 cgroup usage 157.9 MiB 同量级但定义、采样时间不同。 |
| 售后 Worker | `service-order-worker` Pod `service-order-worker-5fd6788b99-t972c` 为 Running；近 6 小时末 150 行日志只出现四类任务：`Task4ServiceOrderFactoryShipper`、`Task4SmsRetryCompensation`、`Task4ServiceOrderRefund`、`Task4ErpSyncCompensation`。这是观察到的日志类别数，不是完整 Quartz 注册数；无注册清单、首个到期任务的脱敏业务 ID 和外部结果，业务结果待验收。不能把 `_Trigger` 算作独立任务。 |
| 短信 | 管理员的统一 SmsCore 目标见[变更记录](worker-start-and-java-egress-2026-09-27.md)。未读取生产生效通道、启用标志、优先级、fallback、模板映射或 SmsCore 受理回执，因此所有项目均待验收，旧创蓝/云瓣是否停用不能断言。需业务配置所有人在不暴露凭据的前提下提供逐项目只读导出：`项目 / 生效通道 / 启用状态 / 优先级 / fallback / 模板引用 / SmsCore 脱敏受理 ID及时间`。 |
| ALB/NAT 与容量 | 约 2.9 万请求、09-26 5XX 2.1%、QPS 1.77 及 NAT 峰值 <0.01 Mbps 出自[值班日志](duty-log.md)先前统计，起止时间与原始序列均待核实；原记录的 09-27 10:30 CST 晚于本次 09:07 复验时点，不能当作已完成的统计窗口。本轮未取得 ALB 5XX 分时原始序列，不能将 503 全部归因于 Ingress 撤下。NAT 从 09-26 21:29 才有指标。ACS 本轮仅 09:07 短窗口，不覆盖发布峰值、24 小时 Worker 任务周期或内存趋势。结论限于“当前无即时扩容证据”。待按小时导出 ALB 5XX/总请求/后端状态，与发布变更时间对齐；同步保存 NAT 出入流量/端口失败和 ACS 连续采样起止时间。 |
| 告警 | 候选规则：ALB 5XX 率 5 分钟 > 2% 且请求数 > 100，或 5XX 数 > 20；NAT 端口分配失败 > 0；Pod 非 Ready 持续 5 分钟或重启增加；内存/limit > 80% 持续 15 分钟；Worker 到期任务无完成事件或业务失败队列增加。候选接收渠道为现有运维钉钉群、值班短信、邮件，需管理员明确接收人、升级链和无副作用触达测试；目前未启用、未验证。 |
| AI Front | 旧 ECS `i-2ze2s8pzq0kvqu28iml8` 在 08:32 复盘中为 Stopped；FrontApi 曾规划保留 ECS。未取得真实域名、DNS/ALB 后端及用户访问证据，影响待验收。迁移门槛：确认域名流量与用户方、目标 FrontApi、认证/回调兼容、回滚窗口；未经授权不启动或切流。 |
| 旧网段五项目 | STOPMP、ETBST、DDMP、新零售、经销商 Pod 在旧网段，现有 SNAT 不覆盖；新零售历史微信支付超时为已记录线索，其他项目的实际启用公网 SDK/目的地未证实。优先级：新零售支付/退款 P1；其余四项目按实际业务调用取证后定级。迁移门槛为逐角色生效配置、供应商白名单、幂等/重试、私网依赖、业务窗口与回滚。不得直接扩大 SNAT。 |

待验收所需动作：生产业务配置只读导出及日志脱敏关联需配置/业务所有人协助；真实短信、资金与数据库操作，以及 AI ECS 启动、切流或 SNAT 变更，须另按明确对象、环境、动作和范围授权。证据不足不等同于故障或已通过。

## 09:15 CST 追加只读核验（以 `59b2573` 为基线）

本节是新增证据；上节 09:07 状态保留为历史快照。当前账号仍为 `1442361567788059`；ACS 查询使用临时 kubeconfig，查询结束后删除。未读取 Secret、生产配置值或包含客户数据的日志原文。

### 1. 售后 Worker：注册来源已定位，业务结果仍待证据

- **注册来源：部分通过。** 本机售后后端仓库 `/Volumes/SSD/work/mall/售后工单系统/service-order-api` 的 `c9487d7` 中，`ServiceOrder.Service.app/AdminTask/_TaskManager.cs` 明确注册 **5 个 Job、各 1 个 Trigger**：`Task4JuShuiTanToken`、`Task4ServiceOrderRefund`、`Task4ServiceOrderFactoryShipper`、`Task4ErpSyncCompensation`、`Task4SmsRetryCompensation`。`ServiceOrder.Worker/Program.cs` 的 Release 路径调用 `AddQuartzTasks`。前四类业务扫描/补偿在 Pod 日志出现；令牌刷新未出现。`Task4JuShuiTanToken` 默认 Cron 为 00:05，Worker 于 00:21 才启动，近期日志不出现它有时间上的合理解释；生产运行时 Cron 可被配置覆盖，尚未读回调度器元数据。当前 Pod `service-order-worker-5fd6788b99-t972c` 的运行时 imageID 为 `sha256:e7416cb0...`，与发布记录中的仓库 digest 不是同一展示值；未取得构建 SHA 对照，不将本机源码直接等同于当前镜像。下一步需由发布负责人提供 imageID/仓库 digest/构建 SHA 对照或只读 Quartz job metadata。`_Trigger` 不另计 Job。
- **最近执行：任务层通过，业务层待证据。** 09:15 CST 查询 `service-order` Worker 近 30 分钟、末 2500 行（返回 750 行），工单扫描最近 09:15:30、发货单扫描最近 09:15:45 记录“扫描成功”；短信补偿最近 09:15:00 记录处理 0、成功 0、失败 0、待重试 0。近 24 小时末 5000 行未见令牌刷新或 exception。扫描成功只证明任务方法返回成功；0 条短信补偿没有 SmsCore 受理事件。没有脱敏工单事件 ID、聚水潭/ERP 结果及退款平台结果，**业务结果未通过验收**。需业务侧提供首次真实到期任务的脱敏事件 ID、时间与外部回执只读关联；不触发新任务。

### 2. 生效短信路由：动态配置来源已定位，生产状态待证据

售后源码 `ServiceOrder.Service.app/Message/SmsRouterService.cs` 在发送时从 `ConfigService.GetAsync()` 取得 `DevelopmentConfig.Sms.Providers`，按 `Enabled=true` 且 `Priority` 升序选通道；前一通道发送失败后会继续尝试下一通道，模板映射来自运行时数据。源码仍包含 `Ruishi`（SmsCore）、`Chuanglan`、`Yunban`、`Aliyun` 实现；这证明旧直连**具备代码路径**，不证明生产已启用。由于有效字段存于业务配置/模板数据，ACS Pod 元数据和部署文档均不能给出实际启用顺序。未读取 Secret、数据库配置或凭据，也未调用发送接口。

| 项目/角色 | 当前非敏感证据 | 启用状态 / 优先级 / fallback / 模板 / SmsCore 回执 | 判定 |
|---|---|---|---|
| 售后工单 Front/Back/Worker | 上述运行时路由源码；Worker 09:15 补偿 0 条 | 生产生效字段和回执均缺 | **待证据**；旧创蓝/云瓣仍可能被运行时配置选中 |
| 积分商城 Back/Worker、保留 Front | [项目依赖表](external-dependencies.md)列为待核对 | 均缺 | **待证据** |
| AI 自习室 Back/Worker、保留 Front | 部署记录为 SmsCore 目标 | 均缺 | **待证据** |
| 新零售 Front/Back/Worker | 旧网段，依赖表待核对 | 均缺 | **待证据** |
| 经销商查询单体 | 旧网段，依赖表待核对 | 均缺 | **待证据** |
| STOPMP | 旧网段 | 均缺 | **待证据** |
| ETBST | 旧网段 | 均缺 | **待证据** |
| DDMP | 旧网段 | 均缺 | **待证据** |
| Yangu API | 新 SNAT 网段，依赖表待核对 | 均缺 | **待证据** |
| M1X API/Worker | 新 SNAT 网段，依赖表待核对 | 均缺 | **待证据** |
| DGYE、VET | 09:02 验收快照为 0 副本 | 均缺；停用副本不证明旧配置已清除 | **待证据** |

精确缺口：由各项目业务配置所有人以只读查询导出通道类型、启用布尔值、优先级、fallback 顺序、模板引用与脱敏 SmsCore 受理 ID/时间，**查询投影必须排除** Key、Secret、手机号及请求体。若该投影只能通过生产数据库或敏感配置读取，需先获得对应对象和字段的明确授权；本轮不越界。不能据“ruishi 优先级最高”断言旧通道停用。

### 3. ALB 09-26 分时原始指标：通过；归因仍待证据

09:15 CST 前以 CMS `acs_alb` 的 `ListenerQPS`、`ListenerHTTPCode{2XX,4XX,5XX,500,502,503,504}` 查询 ALB `alb-olyb9enxszy3f42nnn`、监听 `https:443`。窗口为 **2026-09-26 00:00 至 09-27 00:00 CST**（API `StartTime=1790352000000`、`EndTime=1790438400000` 毫秒；左开右闭），周期 60 秒、各 1440 点。指标定义是每秒值，按每分钟 `Value × 60` 积分；指标值有四舍五入，以下均为近似请求数。请求 ID：QPS `01A0E06C-683C-5A5F-BB6E-AB24B066F8E6`，2XX `01A0E06C-6A41-5C14-A89D-5F52F5268AB1`，4XX `01A0E06C-6C40-52CD-BB89-F1124D022912`，5XX `01A0E06C-6E5D-501D-8320-A0B527E0A190`，503 `01A0E06C-705B-55B3-83B2-ADB05E1443CF`，500 `01A0E06E-07E7-586B-88C9-5D62C927D255`。

| CST 小时 | 请求约数 | 5XX 约数 | 其中 503 约数 | 说明 |
|---|---:|---:|---:|---|
| 09-26 11 | 3387 | 217 | 2 | 以 500（约 211）为主，不能归因于 Ingress 撤下 |
| 09-26 15 | 2739 | 190 | 182 | 503 峰值，与发布记录的撤下事件可能相关，缺事件精确时间与请求日志 |
| 09-26 21 | 1392 | 49 | 49 | 仍有 503，不能全部归于 15 时段事件 |
| 09-26 22 | 763 | 46 | 46 | 同上 |
| 09-26 全日 | 30322 | 683 | 434 | 5XX / QPS 约 **2.25%**，503 / QPS 约 1.43% |

同窗 2XX 约 28596、4XX 约 1046、500 约 245、502 约 3、504 约 1。此前“09-26 5XX 2.1%”在此**明确窗口与口径下未复现**；需提供原统计的起止、维度、汇总方式才能解释差异。发布记录只称售后两条 Ingress 曾撤下，缺带时间的变更事件、ALB 访问日志及 Rule/Host 维度，不能将 15 时段 503 直接定因，也不能把 11 时段 500 混入该事件。

### 4. AI Front 与旧网段依赖：位置/入口部分通过，用户与真实外呼待证据

- **AI Front：入口状态未通过；用户影响待证据。** 源码及部署记录把 `rsst-front-api.svision100.com` 用作 AI Front 与支付通知入口；09:14 CST 公共 DNS 查询返回 `NXDOMAIN`，HTTPS 无法完成连接。ECS `i-2ze2s8pzq0kvqu28iml8` 的 `DescribeInstances` 返回 `Stopped`，RequestId `01A0E06D-5B10-55A8-9DB3-757B311F54BA`。ACS `ai-study` 只有 `rsst-back-api.svision100.com` Ingress，没有 Front Host。该 DNS 状态与 ECS 停机使该规划入口不可用；是否仍有用户或支付回调依赖，不能从配置字符串推断。当前账号 Alidns `DescribeSubDomainRecords` 返回 `IncorrectDomainUser`，RequestId `01A0E06D-A6BF-5A81-9BF0-68DD48D458C6`。需域名所有者的 DNS 只读权限，以及前台访问/回调日志的脱敏统计和业务负责人确认。未经授权不启动 ECS 或切流。
- **旧网段位置：通过。** 09:13 CST ACS Pod 读回：STOPMP `172.31.239.13`，ETBST `172.31.239.12`，DDMP `172.31.239.10`，新零售 Front/Back/Worker 分别 `172.28.53.146`、`172.31.239.26`、`172.31.239.29`，经销商 `172.31.239.39`；均不在已记录 SNAT 的 `172.31.240.0/24`、`172.28.64.0/24`。Pod IP 是位置证据，不是应用调用或供应商出口证据。
- **真实公网依赖：待证据。** 新零售历史微信支付超时是线索；当前五项目没有脱敏业务调用事件与对应供应商结果。本轮未读取有效配置值，也未触发支付、短信、地图等外呼。需逐项目由配置所有人提供不含凭据的生效目标域名、SDK/角色开关与任务状态，并用现有调用日志的脱敏事件 ID 对应目标、时间、响应及供应商来源 IP。按 P1 先核新零售支付/退款，再核 STOPMP、ETBST、DDMP、经销商的实际启用调用；未核实前不扩大 SNAT。

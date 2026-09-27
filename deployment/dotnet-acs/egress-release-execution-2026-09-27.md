# ACS 统一公网出口与安全发布执行记录

时间：2026-09-27，北京生产账号 `1442361567788059`，集群 `ruishi-prod-acs`。本记录是当前执行状态；[早期只读核查](egress-release-audit-2026-09-27.md)只保留当时的发现，不再代表现网准入状态。

## 已执行并读回

1. 显式使用 `ruishi-prod-acr` Profile 确认账号。公网 NAT `ngw-2zetnd6golba2sju2q7jo` 为 `Available/Normal`，EIP `39.96.67.239` 绑定该 NAT，带宽上限 10 Mbps。两个新 vSwitch 的 SNAT 均 `Available`，新路由表 `vtb-2zedknif7nxu7z397b4o6` 的默认路由指向该 NAT；未修改 NAT、EIP、路由、SNAT、旧 ECS 或 ALB。
2. 在新 k `172.31.240.0/24` 和新 i `172.28.64.0/24` 各运行一个短期、无业务配置的诊断 Pod。实测两区 HTTPS 公网源 IP 均为 `39.96.67.239`；MySQL `172.27.182.156/54:3306`、Redis `172.27.182.157/57:6379`、MongoDB `10.0.0.113/114:3717`、SmsCore `172.27.182.18:3090` TCP 可达。诊断 Pod 均已删除。这里仅证明网络可达，不证明数据库认证、短信受理或外部平台白名单。OpenVPN 只用于本机管理 ACS 私有 API，本轮未修改其路由。
3. 安装 [Deployment/Pod 两条原生准入规则](egress-release-guard.yaml)，先仅在隔离诊断 Namespace 绑定并验证：Deployment 缺选址、旧选址被拒；两个新 vSwitch 调换顺序通过；Pod 显式旧选址被拒。诊断 Binding 和 Namespace 已删除。
4. 在 `kube-system/acs-profile` 第一条 selector 增加对 `ai-study`、`service-order`、`points-mall`、`yangu-api`、`m1x-api` 的按 Namespace 匹配，新 Pod 默认选择两个 NAT vSwitch；保留原 `legacy-vswitch-default` 作为后续兜底。先用诊断 Namespace 的真实无注解 Pod 验证注入，再以资源版本校验更新现网。**服务端干跑不会展示 ACS 创建后的注入结果，不能以干跑输出缺注解误判失败。**
5. 对上述五个 Namespace 分别安装 Deployment 与 Pod 两条 Binding，合计十条，无通配 Binding。生产干跑核对：旧模板被拒、两个新 vSwitch 调换顺序通过、Pod 显式旧选址被拒。实际短期无注解 Pod 经 ACS 注入新选址，已删除。五个 Namespace 的现有业务 Deployment 均在变更前核实显式使用两个新 vSwitch，故此阶段未重启业务 Pod。
6. 新增[统一网络清单](egress-network-inventory.yaml)和[只读发布检查脚本](egress-release-check.py)。脚本从云 OpenAPI、临时 ACS 凭据和 Kubernetes API 实时核对账号、NAT/EIP、SNAT、vSwitch、路由、kubectl 版本、模板、默认 selector、Binding、运行 Pod IP。它不读取 Secret 值，不修改生产对象。对五个已迁 Namespace 的抽样检查通过；对 `new-retail` 传入镜像发布参数时按“未迁移”阻断。
7. 获授权后，先核对新零售生产短信路由：SmsCore 已启用且使用 `172.27.182.18`，创蓝、云瓣、阿里云旧通道均禁用；此次只读核对未写数据库。按 Front → Back → Worker，逐个仅修改 Pod 模板 vSwitch 注解并保留镜像、Secret 引用和副本数。Front 首次新 Pod 已在 `172.31.240.162` Ready，但正式入口短暂返回 503；原因未从 ALB 访问日志证实，时间上与后端同步窗口相符。早期脚本随即回退原选址，入口恢复 200。改进为等待 120 秒并要求连续三次正式入口成功后，重新迁移成功：Front `172.31.240.166`、Back `172.31.240.167`、Worker `172.31.240.168`，均 1/1 Ready；Worker 为 Recreate、旧 Pod 已退出、当前重启 0 次。Front/Back 的 `/health/ready` 返回 200，Worker 近 15 分钟日志无错误特征，但**真实任务结果和 24 小时观察尚未完成**。首次迁移的短暂 503 应纳入后续维护窗口安排。
8. 经销商 `agent-query-api` 迁至 `172.31.240.169`，1/1 Ready；`rsqapi-bk.svision100.com/health/ready` 返回 200。新零售、经销商均已加入 `acs-profile` 新网段默认 selector，各建 Deployment/Pod 两条按 Namespace 限定的准入 Binding；服务端干跑实测旧 vSwitch 被拒、两个新 vSwitch 调换顺序通过。相应[迁移脚本](egress-migrate-one.py)、[保护脚本](egress-protect-namespace.py)及网络清单已同步。两项目的只读发布检查通过。真实外呼业务记录与 24 小时观察仍待完成，不能据此宣称业务全量验收。
9. 20:11–20:21 完成旧网段 Java 的后续迁移，详情见下表。只读查询三个生产短信配置库证实：STOPMP、ETBST、DDMP 的创蓝、云瓣、阿里云直连均为 `enabled=0`，仅 SmsCore 为 `enabled=1`、地址 `http://172.27.182.18:3090`；未写短信库。运行配置中 ETBST/DDMP 的每日扣费开关为关闭；STOPMP 的扣费调度无该开关。三项目均先将副本降到 0，确认旧 Pod 完全退出，再改双 vSwitch 选址和 `Recreate`，最后恢复单副本；保持镜像及 Secret 引用，Pod 重启数均为 0。正式域名 `/actuator/health` 在前后均返回未登录 `401`。单副本切换有短暂入口不可用，不能把这次检查等同于认证业务或次日调度验收。

| 项目 | 迁移后 Pod IP | Pod / 入口 | 发布保护 |
|---|---|---|---|
| STOPMP | `172.31.240.172` | 1/1 Ready、正式 Host 401 | Namespace 默认新选址、Deployment/Pod 准入 |
| ETBST | `172.31.240.173` | 1/1 Ready、正式 Host 401 | 同上 |
| DDMP | `172.31.240.176` | 1/1 Ready、正式 Host 401 | 同上 |

10. Yangu 原 Pod `172.31.240.165` 已在新网段，本次仅将 Deployment 策略改为 `Recreate`，原 Pod UID 不变，未重启。DGYE、VET 的 Deployment 仍为 **0 副本**，只将模板改为两个新 vSwitch、策略改为 `Recreate`，并纳入默认选址和准入保护；未启动业务。DGYE Namespace 里的两个旧网段 Pod 分别为历史 `Failed`、`Succeeded` 的无主诊断对象，不是运行中的 API。M1X API/Worker 原 Pod 仍为 `172.31.240.152/.153`，分别带 `APP_ROLE=api/worker`；积分商城 Back/Worker 原 Pod 仍为 `172.31.240.138/.144`，均未重启。
11. 为六个带进程内调度的 Java Namespace 安装[单副本 Recreate 准入](java-scheduler-singleton-guard.yaml)，每个 Binding 仅匹配本项目；服务端干跑逐项证实正常更新允许、改回 `RollingUpdate` 被拒。M1X Worker 已独立 `Recreate`，API 角色不绑定此规则。使用[发布检查](egress-release-check.py)逐项核对 STOPMP、ETBST、DDMP、Yangu、M1X API/Worker、积分商城 Back/Worker 及零副本 DGYE/VET，十项均通过：NAT/EIP、SNAT、路由、模板、默认选址、准入及运行 Pod IP 与清单一致。
12. 在 STOPMP、ETBST、DDMP、Yangu、M1X API 和 M1X Worker 六个实际业务 Pod 内分别用 `curl -4 --noproxy '*'` 请求 `https://checkip.amazonaws.com`，均读回固定 EIP `39.96.67.239`。`api.ipify.org` 在本轮环境内连接超时/拒绝，故改用另一独立回显站验证；单个回显站失败不能据此判定 NAT 故障。此测试仅验证这些 Pod 的 HTTPS 网络出口，未代替项目真实 SDK 与供应商白名单验收。
13. 再次通过 ACS API 全量读取本轮 12 个业务 Namespace：19 个 Deployment 期望 17 副本、Ready 17，另外 DGYE/VET 各为零副本；17 个 Pod 为 `Running`、0 个 `Pending`，运行 Pod 在新 `172.31.240.0/24` 或 `172.28.64.0/24` 的有 17 个，落旧网段的有 0 个。积分商城 Back/Worker 分别为 `172.31.240.138/.144`，M1X API/Worker 分别为 `172.31.240.152/.153`，Yangu 为 `172.31.240.165`。积分商城的 .NET 运行镜像没有 `curl` 可执行文件，因此未在其业务容器内做回显站测试；选址、SNAT、路由及双区诊断证据已通过，真实 .NET 客户端外呼仍按业务证据验收。

迁移后 Deployment 读回标识（resourceVersion 是采样值，后续发布须实时重读）：

| Namespace / Deployment | UID | generation | resourceVersion |
|---|---|---:|---:|
| `new-retail/new-retail-front` | `013ea972-c04a-47e9-9297-5a9334d406c1` | 8 | 1927113 |
| `new-retail/new-retail-back` | `6ba0bd81-8f93-4780-9f5f-19d7df2a2b1c` | 7 | 1927603 |
| `new-retail/new-retail-worker` | `74e472c4-88ef-4c42-a811-1a75377a22cf` | 5 | 1928874 |
| `agent-query/agent-query-api` | `4b44c023-f11e-43a3-a461-2dc566127f5d` | 12 | 1929451 |

## 当前网络分组和下一步

| 组 | Deployment | 本轮处理 |
|---|---|---|
| 已在 NAT，新默认及准入已启用 | AI Back/Worker；售后 Front/Back/Worker；积分 Back/Worker；Yangu API；M1X API/Worker；新零售 Front/Back/Worker；经销商 API；STOPMP、ETBST、DDMP | STOPMP、ETBST、DDMP 本次有序重建；Yangu 仅改发布策略；M1X 和积分商城未重启 |
| 零副本，模板已预备新 NAT 网段 | DGYE、VET | 保持零副本，未来恢复业务需单独验收生产配置及业务结果 |

固定迁移顺序 **新零售 Front → Back → Worker → 经销商 → STOPMP → ETBST → DDMP** 已完成网络迁移。真实短信受理、外呼平台白名单和业务结果仍需自然业务或经单独授权的测试记录。诊断 Pod 成功只证明网络路径。

只读检查三仓 `origin/release` 的 `SchedulingConfig`：STOPMP 的每日零点扣费任务无配置开关；ETBST 仅在 `etbst.scheduling.card-deduction-enabled=true` 时启用；DDMP 的 `ddmp.scheduling.card-deduction-enabled` 缺省为启用。本轮运行配置只读核对显示 ETBST/DDMP 的开关值均为 `false`；STOPMP 使用停旧再启新的方式避免迁移期间双 Pod。`Recreate` 降低发布重叠风险，但失联或强制删除场景仍需业务幂等保障，不能宣称绝对不会重复扣费。

现有运维记录曾把“告警触达已验证”列为新零售前置项，但生产告警渠道尚未确定。迁移窗口可由明确值班人员连续观察替代自动告警门槛；当前尚未指定人员，不宣称已有无人值守保障。24 小时观察和关键任务周期未完成的项目不得标记迁移关闭。

## 发布与回退操作口径

发布前、人工确认后且**实际更新镜像前**，在部署仓库运行：

```bash
python3 deployment/dotnet-acs/egress-release-check.py <namespace> <deployment> --image '<ACR仓库@sha256:完整摘要>'
```

要求本机 `aliyun` 显式使用生产 Profile、`kubectl` 与服务器版本相差不超过一个次版本，并有 PyYAML。脚本验证镜像 digest 格式与现网仓库一致；**源码 SHA 到 ACR 构建记录的对应关系仍须从发布记录核对**。检查通过后才按现有镜像字段更新路径执行；更新后重新运行无 `--image` 的检查并核对 Ready、实际 Pod IP、正式 Host 和对应业务结果。检查输出的 `resourceVersion` 只用于识别检查时的对象版本；在写入前仍须重新读回并处理并发变化。业务回退使用已记录旧镜像 digest，只更换镜像，保留当前网络字段，禁止直接 `rollout undo` 跨过网络迁移版本。网络回退单独执行，并先处理本 Namespace 的 Binding，再用资源版本保护更新模板与默认选址；不撤销共享 NAT。

ETBST 云效部署流水线当前 `kubectlVersion: 1.27.9`，集群 API Server 为 `1.36.1`，超出 [Kubernetes 官方次版本偏差](https://kubernetes.io/releases/version-skew-policy/)；此前一次镜像发布成功不等于该组合受支持。云效组件是否提供 1.35/1.36 尚未证实，**不得凭猜测把一个版本号写入在线流水线**。在云效版本能力查明前，后续 ETBST 发布使用本机已验证的 `kubectl 1.36.1` 与临时 ACS 访问材料，先执行上述检查，再仅更新镜像 digest；云效流程需要兼容版本及发布前后检查接入后才能恢复作为标准入口。现有云效流水线只更新镜像，不会覆盖 Pod 网络注解。

当前部署仓库没有新零售、经销商、STOPMP、ETBST、DDMP 的完整 Deployment YAML；ETBST 的 `etbst-api-acs.yaml` 仅包含 ServiceAccount。因而不能声称完整 YAML 已与现网同步。后续若创建完整发布模板，必须引用本清单中的两个 vSwitch；已纳管 Namespace 的准入会拒绝缺失或旧选址模板。六个 Java 调度项目还会拒绝非 `Recreate` 或超过单副本的模板。镜像日常发布不使用历史 ReplicaSet 的 `rollout undo`。

## 尚未达到的完成条件

**网络选址已完成**：本轮清单内的运行 Pod 均在两个新网段；DGYE、VET 为零副本、模板及默认值已预备。双区无业务诊断 Pod 的 MySQL/Redis/MongoDB/SmsCore TCP 探测已通过，但本轮从新 STOPMP/ETBST/DDMP Pod 使用 `curl telnet://` 逐项探测时首项未在有界时间内返回，因此终止该轮探测；未取得这三个业务 Pod 的逐地址读回证据，不能把探测未返回直接解释成数据库网络不通。Ready 和无重启也不能替代逐地址认证验收。尚缺各项目真实第三方 SDK 外呼/短信受理、资金或定时任务结果及 24 小时观察证据，不能标注“业务全量验收”。下一次零点后需只读核对 STOPMP 的扣费结果与其他项目实际启用状态；结果不明时不得人工补跑。DGYE、VET 未来恢复运行前另做业务验收。

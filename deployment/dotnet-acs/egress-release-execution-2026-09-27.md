# ACS 统一公网出口与安全发布执行记录

时间：2026-09-27，北京生产账号 `1442361567788059`，集群 `ruishi-prod-acs`。本记录是当前执行状态；[早期只读核查](egress-release-audit-2026-09-27.md)只保留当时的发现，不再代表现网准入状态。

## 已执行并读回

1. 显式使用 `ruishi-prod-acr` Profile 确认账号。公网 NAT `ngw-2zetnd6golba2sju2q7jo` 为 `Available/Normal`，EIP `39.96.67.239` 绑定该 NAT，带宽上限 10 Mbps。两个新 vSwitch 的 SNAT 均 `Available`，新路由表 `vtb-2zedknif7nxu7z397b4o6` 的默认路由指向该 NAT；未修改 NAT、EIP、路由、SNAT、旧 ECS 或 ALB。
2. 在新 k `172.31.240.0/24` 和新 i `172.28.64.0/24` 各运行一个短期、无业务配置的诊断 Pod。实测两区 HTTPS 公网源 IP 均为 `39.96.67.239`；MySQL `172.27.182.156/54:3306`、Redis `172.27.182.157/57:6379`、MongoDB `10.0.0.113/114:3717`、SmsCore `172.27.182.18:3090` TCP 可达。诊断 Pod 均已删除。这里仅证明网络可达，不证明数据库认证、短信受理或外部平台白名单。OpenVPN 只用于本机管理 ACS 私有 API，本轮未修改其路由。
3. 安装 [Deployment/Pod 两条原生准入规则](egress-release-guard.yaml)，先仅在隔离诊断 Namespace 绑定并验证：Deployment 缺选址、旧选址被拒；两个新 vSwitch 调换顺序通过；Pod 显式旧选址被拒。诊断 Binding 和 Namespace 已删除。
4. 在 `kube-system/acs-profile` 第一条 selector 增加对 `ai-study`、`service-order`、`points-mall`、`yangu-api`、`m1x-api` 的按 Namespace 匹配，新 Pod 默认选择两个 NAT vSwitch；保留原 `legacy-vswitch-default` 作为后续兜底。先用诊断 Namespace 的真实无注解 Pod 验证注入，再以资源版本校验更新现网。**服务端干跑不会展示 ACS 创建后的注入结果，不能以干跑输出缺注解误判失败。**
5. 对上述五个 Namespace 分别安装 Deployment 与 Pod 两条 Binding，合计十条，无通配 Binding。生产干跑核对：旧模板被拒、两个新 vSwitch 调换顺序通过、Pod 显式旧选址被拒。实际短期无注解 Pod 经 ACS 注入新选址，已删除。五个 Namespace 的现有业务 Deployment 均在变更前核实显式使用两个新 vSwitch，故此阶段未重启业务 Pod。
6. 新增[统一网络清单](egress-network-inventory.yaml)和[只读发布检查脚本](egress-release-check.py)。脚本从云 OpenAPI、临时 ACS 凭据和 Kubernetes API 实时核对账号、NAT/EIP、SNAT、vSwitch、路由、kubectl 版本、模板、默认 selector、Binding、运行 Pod IP。它不读取 Secret 值，不修改生产对象。对五个已迁 Namespace 的抽样检查通过；对 `new-retail` 传入镜像发布参数时按“未迁移”阻断。

## 当前网络分组和下一步

| 组 | Deployment | 本轮处理 |
|---|---|---|
| 已在 NAT，新默认及准入已启用 | AI Back/Worker；售后 Front/Back/Worker；积分 Back/Worker；Yangu API；M1X API/Worker | 无业务 Pod 重建；以后发布用实时检查 |
| 旧网段待迁 | 新零售 Front、Back、Worker；经销商 `agent-query-api`；STOPMP、ETBST、DDMP | 保持旧选址、现有副本和现有入口；未加会阻断紧急发布的 Binding |
| 零副本 | DGYE、VET | 保持零副本；恢复前另做业务及网络核对 |

迁移顺序仍为 **新零售 Front → Back → Worker → 经销商 → STOPMP → ETBST → DDMP**，一次只改一个 Deployment。当前停止在迁移门槛：新零售缺生产生效短信路由与旧供应商禁用证据、微信/支付平台来源 IP 要求和 Worker 唯一执行证据；经销商缺地图等实际公网调用确认；STOPMP/ETBST/DDMP 缺逐项目启用外呼及短信路由核对。没有这些证据，不能把诊断 Pod 的成功当作生产应用验收。已迁项目的真实短信受理和供应商结果也仍需自然业务或经单独授权的测试记录。

现有运维记录曾把“告警触达已验证”列为新零售前置项，但生产告警渠道尚未确定。迁移窗口可由明确值班人员连续观察替代自动告警门槛；当前尚未指定人员，不宣称已有无人值守保障。24 小时观察和关键任务周期未完成的项目不得标记迁移关闭。

## 发布与回退操作口径

发布前、人工确认后且**实际更新镜像前**，在部署仓库运行：

```bash
python3 deployment/dotnet-acs/egress-release-check.py <namespace> <deployment> --image '<ACR仓库@sha256:完整摘要>'
```

要求本机 `aliyun` 显式使用生产 Profile、`kubectl` 与服务器版本相差不超过一个次版本，并有 PyYAML。脚本验证镜像 digest 格式与现网仓库一致；**源码 SHA 到 ACR 构建记录的对应关系仍须从发布记录核对**。检查通过后才按现有镜像字段更新路径执行；更新后重新运行无 `--image` 的检查并核对 Ready、实际 Pod IP、正式 Host 和对应业务结果。检查输出的 `resourceVersion` 只用于识别检查时的对象版本；在写入前仍须重新读回并处理并发变化。业务回退使用已记录旧镜像 digest，只更换镜像，保留当前网络字段，禁止直接 `rollout undo` 跨过网络迁移版本。网络回退单独执行，并先处理本 Namespace 的 Binding，再用资源版本保护更新模板与默认选址；不撤销共享 NAT。

ETBST 云效部署流水线当前 `kubectlVersion: 1.27.9`，集群 API Server 为 `1.36.1`，超出 [Kubernetes 官方次版本偏差](https://kubernetes.io/releases/version-skew-policy/)；此前一次镜像发布成功不等于该组合受支持。云效组件是否提供 1.35/1.36 尚未证实，**不得凭猜测把一个版本号写入在线流水线**。在云效版本能力查明前，后续 ETBST 发布使用本机已验证的 `kubectl 1.36.1` 与临时 ACS 访问材料，先执行上述检查，再仅更新镜像 digest；云效流程需要兼容版本及发布前后检查接入后才能恢复作为标准入口。现有云效流水线只更新镜像，不会覆盖 Pod 网络注解。

当前部署仓库没有新零售、经销商、STOPMP、ETBST、DDMP 的完整 Deployment YAML；ETBST 的 `etbst-api-acs.yaml` 仅包含 ServiceAccount。因而不能声称完整 YAML 已与现网同步。后续若创建完整发布模板，必须引用本清单中的两个 vSwitch；已纳管 Namespace 的准入会拒绝缺失或旧选址模板。镜像日常发布不使用历史 ReplicaSet 的 `rollout undo`。

## 尚未达到的完成条件

七个旧网段运行 Pod 还未迁移，逐项目外呼/短信/任务验收和迁移后的 24 小时观察仍未完成。因此本次只完成双区验证与**已在 NAT 的五个 Namespace 防回退保护**，不能标注“所有业务已统一出口”。后续迁移先闭合上述已列门槛，再按单项目变更记录执行；DGYE、VET 不启动。

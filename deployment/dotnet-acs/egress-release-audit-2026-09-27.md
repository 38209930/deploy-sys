# ACS 公网出口与发布选址核查（2026-09-27）

**历史只读快照：本页中的“准入未安装”和默认选址状态仅代表执行前。当前状态以[同日执行记录](egress-release-execution-2026-09-27.md)和实时 API 读回为准。**

核查对象：生产账号 `1442361567788059`、北京 `ruishi-prod-acs`、VPC `vpc-2zervez1jgscsglpenrzo`。使用显式 `ruishi-prod-acr` Profile，通过阿里云 OpenAPI 和临时 ACS Kubernetes API 凭据**只读**核查；临时凭据未写入仓库。本文中的“可出网”指网络路由与 SNAT 条件具备，不等于微信、支付等真实业务验收通过。

## 结论

**NAT 网络资源已经建成；发布选址尚未收口。**现有 19 个业务 Deployment 中，17 个运行中：10 个 Pod 在两个有 NAT 的新网段，7 个在无公网默认路由的旧网段；DGYE、VET 为零副本，模板均固定旧网段。当前 `acs-profile` 对无显式选址的 Pod 仍注入旧 k/i vSwitch，因此更新镜像、重建或新增无选址的 Deployment 仍会落入无公网出口的旧网段。

### 网络资源读回

| 对象 | 实际状态 |
|---|---|
| 公网 NAT | `ngw-2zetnd6golba2sju2q7jo`，跨可用区增强型，`Available`、`Normal` |
| 固定 EIP | `39.96.67.239`，`InUse`，已绑定该 NAT，10 Mbps 上限 |
| 新网段 | `172.31.240.0/24` 对应 `vsw-2zevd832gq3313j6gv5sj`；`172.28.64.0/24` 对应 `vsw-2zesy6off4gy39tqripzp` |
| SNAT | 两条规则均 `Available`，分别覆盖上述两个 vSwitch，均转换为 `39.96.67.239`；无 DNAT |
| 路由 | 新网段关联表 `vtb-2zedknif7nxu7z397b4o6` 有 `0.0.0.0/0 → NAT`；七个旧 vSwitch 关联 `vtb-2ze9057j04btdfr3bofhy`，无公网默认路由；两张表均保留 `10.0.0.0/24 → Mongo VPC Peering` |
| 默认选址 | `kube-system/acs-profile` 的 `legacy-vswitch-default` selector 对未显式指定 vSwitch 的新 Pod 注入旧 k/i：`vsw-2zeagdbk8hizkkdw0ns42,vsw-2zec5qkbaiafqu3pyuamo` |

阿里云 OpenAPI 本次读回 RequestId：NAT `01A0E273-A6D8-5CF5-9029-11B1D21EDB48`、EIP `01A0E273-A6D6-5399-A473-21BC40FC0233`、SNAT `01A0E273-A6DB-509C-8791-9AF53D9FD878`、vSwitch `01A0E273-A6D1-5980-B5AB-2C518BAE9FAF`。路由表按分页读回，详见会话操作记录。

### 运行工作负载

| 位置 | Deployment | Pod 选址模板 |
|---|---|---|
| 新网段，10 个运行中 | `ai-study` Back/Worker；`service-order` Front/Back/Worker；`points-mall` Back/Worker；`yangu-api`；`m1x-api` API/Worker | 均显式指定两个新 vSwitch |
| 旧网段，无公网出口，4 个运行中 | `new-retail` Front/Back/Worker；`agent-query-api` | **无显式选址**，依赖旧网段默认 selector |
| 旧网段，无公网出口，3 个运行中 | `stopmp-api`、`etbst-api`、`ddmp-api` | 显式固定旧 k vSwitch |
| 旧网段，零副本 | `dgye-api`、`vet-api` | 显式固定旧 k vSwitch；启动前仍须先处理选址和业务门槛 |

新零售旧网段记录过到微信支付 `api.mch.weixin.qq.com:443` 超时；不能因 NAT 已建就认定该业务已恢复。经销商现有门店查询主要走私网，尚未证明存在实际公网依赖，但其下一次无选址发布仍会落旧网段。

## 生产发布防线

准备了[待授权的准入规则](egress-release-guard.yaml)：只匹配上述 12 个已知业务 Namespace 中 Deployment 的 `CREATE/UPDATE`，要求 Pod 模板显式指定两个有 NAT/SNAT 的新 vSwitch，否则 Kubernetes API 拒绝发布。规则不改写 Pod、不改变现有副本或路由，也不匹配 ReplicaSet/Pod；因此**不会修复已在旧网段的服务，也无法阻止既有旧模板因非发布原因重建到旧网段**。新增项目 Namespace 须同步纳入规则范围。它是一道发布闸门，不能替代供应商白名单、短信、私网连通和业务验收。

**未安装该规则，尚无强制发布闸门。**安装前须按生产权限范围取得明确授权，并用服务端校验与拒绝/放行样例确认 CEL 行为。启用后，当前旧网段的七个运行 Deployment 及 DGYE/VET 的模板更新会被拒绝，直至逐项目完成迁移门槛并设置新选址。这包括紧急镜像发布；值班人员须预先知晓。它不拦截 `deployments/scale` 子资源或直接操作 Pod/ReplicaSet，发布流程仍须只通过受控 Deployment 路径。

只读检查显示集群提供 `admissionregistration.k8s.io/v1` 的 Policy/Binding API，当前均为零个对象；当前身份有创建权限。权限可用不代表已获生产变更授权。

规则文件已通过本地 YAML 结构检查和 ACS API 的 `kubectl create --dry-run=server` 校验；服务端干跑返回两个对象名称，未持久化对象。实际拒绝/放行行为须在安装获准后，用不持久化的 Deployment 更新样例验证。

### 逐项目迁移门槛

1. 新零售按 Front → Back → Worker 分别核对微信/支付出站、三方固定 IP 白名单、SmsCore 私网白名单、MySQL/Redis/MongoDB/OpenVPN 私网可达、在途订单和 Worker 唯一执行；逐角色独立变更、验收、观察与回滚。现有用户操作及资金任务不能仅以 TCP 探测验收。
2. 经销商先判定是否确有公网调用。若需要，按同样的私网与业务检查迁移；若不需要，不能仅为满足通用闸门在无依据时改变生产选址，需调整准入范围并记录例外。
3. STOPMP、ETBST、DDMP 及零副本 DGYE/VET 分别核对外呼及旧短信直连是否关闭、私网数据库与 OpenVPN 路径、第三方白名单；未通过者维持当前副本与选址，发布受阻是预期保护。
4. 每次迁移只修改该 Deployment 的 `spec.template.metadata.annotations["network.alibabacloud.com/vswitch-ids"]`；记录旧模板、Pod IP、镜像/配置摘要和资源版本。新 Pod 必须落在两个新 `/24` 之一，从应用真实客户端/供应商记录核验出口 `39.96.67.239`，并核对私网、正式 Host、错误率和 Worker 任务结果；结果不明时先查业务状态。

### 禁止的快捷改法

- 不能直接给旧七个 vSwitch 所在路由表加公网默认路由，或给旧 `/20` 整段补 SNAT：这会扩大到范围外 ECS/Pod。
- 不能直接把 `acs-profile` 默认 selector 改到新网段：这会让当前无注解的生产 Deployment 在未来重建时无门槛迁移。
- 不能把“新 NAT 存在”“健康接口 200”当作某个 Pod/业务有公网出口的证据。

## 回退与后续验证

准入规则如在授权后安装，回退仅删除 `ValidatingAdmissionPolicyBinding/ruishi-business-egress-vswitch`，再核对规则已不再阻断；保留 Policy 对象供审计。回退闸门不迁移 Pod、不修改 NAT/SNAT/路由，也不解决旧网段无公网的问题。单项目选址回退按原 Pod 模板恢复，并核对已发出的支付、短信、订单等外部写请求结果，不撤销共享 NAT。

本次未做生产写入、未读取 Secret 值、未主动发送短信/支付请求。业务验收、准入规则安装和旧网段迁移仍未执行。

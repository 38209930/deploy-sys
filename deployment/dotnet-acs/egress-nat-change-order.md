# 北京 ACS 公共公网出口：生产网络变更单

状态：**已创建两张自定义路由表和三个隔离新 vSwitch，配置 ACS 默认选址护栏；NAT、EIP、SNAT 未创建，旧七个 vSwitch 未迁路由，业务 Pod 未迁移。新网段 MongoDB 私网连接仍为阻断项。** 核对日期：2026-09-26。生产变更继续受[MongoDB 新网段连通门槛](network-constraints-2026-09-26.md)约束；项目业务配置和真实资金/短信测试另按项目门槛执行。

## 1. 已核实的现网事实

- VPC `vpc-2zervez1jgscsglpenrzo`，北京，IPv4 `172.16.0.0/12`，未发现启用 IPv6。ACS `ruishi-prod-acs`：`cebc88343a44b4d759aa983a47b787835`。
- 系统路由表 `vtb-2zebvv47akvfr0cq15njq` **关联下面全部七个旧 vSwitch**；仅有七条 VPC local、`100.64.0.0/10` 服务路由和 `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen`，没有默认路由。未发现本 VPC 的公网 NAT。
- 本次已创建 `acs-legacy-private-route`（`vtb-2ze9057j04btdfr3bofhy`）和 `acs-egress-route`（`vtb-2zedknif7nxu7z397b4o6`），各有相同的 local、服务与 `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen` 路由，均无默认路由；出口表已关联两个新 Pod vSwitch，旧业务表仍无关联；旧七个 vSwitch 仍在系统表。
- `kube-system/acs-profile` 的 `vSwitchIds` 保留旧 k/i 并追加新 k/i；兜底 selector 已实测无显式选址 Pod 落旧网段。现有 10 个运行中业务 Pod 仍在旧网段（含 M1X API/Worker、新零售三个角色、经销商 API），未迁移；两区临时诊断 Pod 已清理。
- 旧 k 网段还有独立网站 ECS `172.31.238.203`，自带公网 IP；按阿里云出口优先级，它继续使用自身公网地址，不是新建 Pod 网段的必要条件，也不纳入项目迁移。旧 f 网段含 SmsCore ECS `172.27.182.18`，其短信供应商出口保持独立；供应商侧实际出口与白名单仍需单独核实。

| 旧 vSwitch | 可用区 / CIDR | 已知来源 | 目标路由表 |
|---|---|---|---|
| `vsw-2zeagdbk8hizkkdw0ns42` | k / `172.31.224.0/20` | Java Pod、网站 ECS、ACS 系统、ALB | 保留原路径的自定义表 |
| `vsw-2zec5qkbaiafqu3pyuamo` | i / `172.28.48.0/20` | ACS 系统、ALB | 同上 |
| `vsw-2zegylmoqcrsi3qa1q084` | j / `172.16.16.0/20` | 当前无 ENI | 同上 |
| `vsw-2zebfrgp41h4ni1x6maeo` | g / `172.17.176.0/20` | 当前无 ENI | 同上 |
| `vsw-2ze7tvymfb4v5gotha8oo` | l / `172.26.144.0/20` | 当前无 ENI | 同上 |
| `vsw-2zenwmnl95fsvbz43bzqb` | h / `172.22.192.0/20` | ALB | 同上 |
| `vsw-2zextannxrk3zfsy07t9j` | f / `172.27.176.0/20` | SmsCore 等 ECS、ALB | 同上 |

| 已创建 vSwitch | 可用区 / CIDR | 用途 | 当前路由表 |
|---|---|---|---|
| `acs-egress-pods-k` `vsw-2zevd832gq3313j6gv5sj` | k / `172.31.240.0/24` | 经批准迁入的 ACS 业务 Pod | `acs-egress-route` |
| `acs-egress-pods-i` `vsw-2zesy6off4gy39tqripzp` | i / `172.28.64.0/24` | 经批准迁入的 ACS 业务 Pod | `acs-egress-route` |
| `acs-nat-k` `vsw-2zemuu9wf9pz0w83c7kpv` | k / `172.31.241.0/28` | NAT 专用；不加入 ACS `vSwitchIds` | 系统表 |

三个网段已创建且与本 VPC 旧 vSwitch 不重叠。MySQL、Redis、SmsCore 已从新 Pod 双区实测私网 TCP；MongoDB 双区 TCP 失败，对端缺少两个回程路由和白名单。见[实测记录](network-constraints-2026-09-26.md)。本机 OpenVPN 到新 Pod 网段的路由不是云侧 Pod 私网访问的前提；未来如需本机直连再单独配置。新 Pod 网段的使用主体严格限于审批清单中的工作负载；Namespace 本身不构成网络隔离。

## 2. 固定拓扑与不变量

```text
旧七个 vSwitch ── legacy-route（local + 服务 + 10.0.0.0/24 对等连接；无 0/0）
新 Pod k/i     ── egress-route（同上 + 0.0.0.0/0 → 新 NAT）
NAT 专用 k     ── VPC 系统表（创建 NAT 后自动出现的 0.0.0.0/0）
新 Pod k/i     ── 各自 vSwitch 级 SNAT → 同一个固定 EIP
```

按本版隔离方案，不能先在旧 k 网段给现有 Pod 加 `/32` SNAT：旧 vSwitch 的保留原路径路由表没有指向 NAT 的默认路由，SNAT 条目单独存在也不能出网。灰度应先将**目标 Pod 移入新专用 vSwitch**，再使用新 vSwitch 的 NAT 路由和 SNAT 验证。旧 k/i、网站 ECS、SmsCore 继续使用原路由；本版不对旧 `/20` 或整个 VPC 建通配 SNAT。网站 ECS 本身不阻止复用旧 k；若改用旧 k，须另订覆盖范围和路由变更单，不直接套用本版步骤。

创建 NAT 会自动修改系统表，故必须先使七个旧 vSwitch 全部脱离系统表。自定义路由表会自动包含本地和服务路由，但**不会自动继承对等连接自定义路由**；必须手工复制 `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen` 并只读对比。关联 API 是异步的，每个 vSwitch 完成后查询状态及真实私网/入站业务，再处理下一个。创建 NAT 后不得把旧 vSwitch 直接解绑回系统表，否则会落入带 NAT 默认路由的系统表。

## 3. 分阶段 API 操作及每步门槛

### A. 执行前冻结

1. 重读系统表的路由、七个关联、所有 vSwitch 与 ENI、ACS `acs-profile`、10 个现有业务 Pod 选址、ALB/网站/SmsCore 状态；保存不含秘密值的时间戳快照。任何新增路由、其他 NAT、来源或共享网络改动都使本变更单失效，先重评。
2. 从账号下单/API 报价核实增强型跨可用区 NAT、普通 BGP 按流量 EIP（初始 10 Mbps）、可用区容量、配额与余额。按月估算见[出口手册](egress-nat.md)，采购前记录真实报价。
3. 项目来源接入前完成[外部依赖清单](external-dependencies.md)：旧直连短信通道禁用、付款写请求重试与任务补跑风险、第三方白名单及告警接收人。该门槛**不阻止仅创建隔离的空网络资源**，但阻止该项目 Pod 迁入新网段。

### B. 隔离旧路由（任何 NAT 创建之前）

1. `acs-legacy-private-route` 已创建并为 `Available`；对等连接路由已复制，local、服务及 peer 路由与系统表相同，且无 `0.0.0.0/0`。**继续执行前须重读三张表，并完成 MongoDB 新网段连通验证；OpenVPN 仅在本机需要直连新 Pod 时另行处理。**
2. 对七个旧 vSwitch 按**j → g → l → h → i → k → f**逐个 `AssociateRouteTable`；每次等待 `DescribeVSwitchAttributes` 为 `Available`，检查关联、私网和涉及业务。k 检查全部 Java 入口、网站；f 检查 SmsCore 私网及其原公网；i/h 检查 ALB。任一步异常时停止，NAT 尚未创建，可将已迁移交换机从自定义表解绑回**仍无默认路由**的系统表，逐个核验。
3. 七个旧 vSwitch 都不再关联系统表，且系统表仍无默认路由，才允许进入下一段。

### C. 创建隔离出口资源

1. `acs-egress-route` 已关联两个新 Pod vSwitch；NAT 专用 vSwitch 已创建并留在系统表。重读三个 CIDR、路由关联和系统表；创建 NAT 前仍须先将七个旧 vSwitch 逐项迁入无默认路由的旧业务表。
2. `CreateNatGateway` 指定 VPC、NAT 专用 vSwitch、`NetworkType=internet`、`NatType=Enhanced`、**`EipBindMode=NAT`**，核对跨可用区模式及按量计费参数，使用固定任务 `ClientToken`。等待 NAT `Available`，核验自动新增的系统表 `0.0.0.0/0` 仅作用于 NAT 专用 vSwitch；此时仍无生产 SNAT。
3. 申请一个普通 BGP 按流量 EIP，带宽上限 10 Mbps；绑定新 NAT，核对唯一公网 IP、资源状态、无 DNAT。`acs-egress-route` 再添加 `0.0.0.0/0 → 新 NAT`，核查旧 `acs-legacy-private-route` 始终没有默认路由。

### D. ACS 选址护栏与诊断（选址护栏已完成）

1. 先在 `acs-profile.selectors` 设置一个匹配全部 ACS Pod 的兜底规则，注入旧 k/i vSwitch 注解；Pod 原有注解优先于 selector。已仅修改 `selectors`，验证不带显式选址的短期诊断 Pod 仍落在旧 k/i；现有业务 Pod 未重建。

   已写入的 `selectors` 值（作为 ConfigMap 字符串，并使用 `resourceVersion` 条件更新）：

   ```json
   [{"name":"legacy-vswitch-default","effect":{"annotations":{"network.alibabacloud.com/vswitch-ids":"vsw-2zeagdbk8hizkkdw0ns42,vsw-2zec5qkbaiafqu3pyuamo"}}}]
   ```

   官方说明未指定 selector 条件时对全部 ACS Pod 生效，且已有 Pod 注解优先。本集群已在追加新 vSwitch 前使用短期诊断 Pod 验证默认选址。
2. 已在 `acs-profile.vSwitchIds` **追加**两个新 Pod vSwitch，保留旧 k/i；未加入 NAT 专用 vSwitch。已核对 selector 未被覆盖，现有业务 Pod 仍在旧网段。若默认选址不受护栏控制，移除新增 `vSwitchIds` 并停止，尚无业务 Pod 迁移。
3. 已在新 k/i 各建并清理一个带明确选址注解的短期诊断 Pod：DNS、MySQL、Redis、SmsCore 通过，MongoDB 未通过。完成 MongoDB 回程与白名单并复测后，才可为各自精确 `/32` 建临时 SNAT，再验固定 EIP、TLS 与外部**只读**调用。检查从外部不能连入 Pod。销毁并重建诊断 Pod，验证新 IP 不会意外通过已失效的 `/32` 出网。
4. 在新 k/i 分别创建指向**同一 EIP**的 vSwitch 级 SNAT，确认新诊断 Pod 重建后两区均固定出口；删除诊断 `/32`，检查两区无意外来源及旧网段仍未出网。诊断 Pod 清理后保持两条稳定 vSwitch SNAT。

### E. 业务逐项迁入

1. 按 DGYE → VET → STOPMP → ETBST → DDMP → Yangu → M1X 的顺序，只对已通过业务门槛的 Deployment 修改 `spec.template.metadata.annotations["network.alibabacloud.com/vswitch-ids"]` 为新 k/i 两个 ID，滚动重建。每项目记录原镜像/配置版本、旧 Pod IP、修改前注解和新 Pod IP；单副本可能短暂中断，按业务窗口执行。
2. 每项核对 Pod 运行、ALB 精确 Host、私网依赖、SmsCore 通道、实际 SDK 外呼、供应商观察到的 EIP、业务副作用与任务状态。M1X API 和 Worker 分开核对，Worker 唯一执行；资金和真实短信测试仍按具体范围授权。
3. 任一项目不合格，恢复该 Deployment 原选址注解并核实新 Pod 实际退出、旧网段恢复；先查清已发生的外部写操作，不用网络回滚代替业务对账。其他项目及共享 NAT 保持运行。
4. Java 全部通过并覆盖至少 24 小时和关键任务周期后，才按 AI → 售后工单 → 积分商城 → 新零售 → 经销商的既定顺序发布 .NET；此变更单不授权业务代码或生产数据改动。

## 4. 回滚边界和停机条件

- **NAT 前**：逐个解除旧 vSwitch 与 `acs-legacy-private-route` 的关联即可回原系统表；每步确认系统表仍无 `0.0.0.0/0`。不删除已有业务路由。
- **NAT 后、业务迁入前**：先删除新 Pod vSwitch 的 SNAT、`acs-egress-route` 默认路由，撤销 `acs-profile` 新 vSwitch 与 selector，清理诊断 Pod；保留旧 vSwitch 在 `acs-legacy-private-route`。确认没有新 Pod 后再考虑删除 NAT 及系统表自动路由，**绝不直接把旧 vSwitch 解绑回系统表**。
- **业务迁入后**：优先逐项目恢复原选址注解并确认 Pod 退出、业务结果；共享出口只有在所有业务来源撤出后才清理。若系统默认路由无法按官方流程安全移除，则保持 NAT/EIP 并升级处理，不强拆。
- 系统表自动默认路由出现在七个旧 vSwitch 的有效路径、旧网站/SmsCore/Java 私网或 ALB 异常、未纳入的 Pod 进入新网段、EIP 与第三方白名单不一致、告警缺失、资金/短信重复，均为立即停止后续步骤的条件。
- 保留 EIP 作为已公布的固定地址；EIP 释放、第三方白名单移除、真实支付/退款/短信发送不属于本变更单的自动回滚动作。

## 5. 执行记录

记录 `授权范围、时间窗口、操作者、每步 API RequestId/ClientToken、资源 ID、前后路由表与交换机状态、Pod 选址、固定 EIP、供应商白名单、私网/ALB/业务验证、异常与回滚结果`。只记录配置版本与摘要，不写入 kubeconfig、Secret、签名、手机号或完整支付报文。创建类 API 返回成功只表示受理；必须等待资源状态和数据面验证。

依据：[VPC 路由表](https://help.aliyun.com/zh/vpc/vpc-route-table)、[VPC 对等连接与自定义路由表](https://help.aliyun.com/en/vpc/vpc-peer-to-peer-connection)、[路由表关联 API](https://help.aliyun.com/zh/vpc/developer-reference/api-vpc-2016-04-28-associateroutetable)、[NAT 创建 API](https://help.aliyun.com/zh/nat-gateway/developer-reference/api-vpc-2016-04-28-createnatgateway-natgws)、[ACS acs-profile](https://help.aliyun.com/zh/cs/user-guide/configure-eci-profile)、[ACS 扩展 vSwitch](https://help.aliyun.com/zh/cs/user-guide/use-additional-vpc-segments-to-expand-the-virtual-switches-of)。

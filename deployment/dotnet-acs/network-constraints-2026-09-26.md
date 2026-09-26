# ACS 共享 NAT：数据库与 OpenVPN 网段核对及执行记录

时间：2026-09-26；账号 `1442361567788059`，北京 VPC `vpc-2zervez1jgscsglpenrzo`。本页只记录网络地址、规则和资源标识，不记录凭据或数据库内容。所有结论只适用于查询时点；生产关联或采购前须重读。

## 1. 已执行的无业务关联准备

使用显式 CLI Profile `ruishi-prod-acr`，核验账号后通过 VPC OpenAPI：

| 对象 | 结果 | 创建 RequestId |
|---|---|---|
| `acs-legacy-private-route` | `vtb-2ze9057j04btdfr3bofhy`，Available，关联 vSwitch 0 | `01A0DDBA-9E64-5681-9872-659C3C205851` |
| 旧业务表 Mongo 对等路由 | `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen`，`rte-2ze1d1w6r0omjrsgssywu` | `01A0DDBA-DF90-54A5-915E-D99B152ACCBE` |
| `acs-egress-route` | `vtb-2zedknif7nxu7z397b4o6`，Available，关联 vSwitch 0 | `01A0DDBB-650B-5529-8272-8933FA670F11` |
| 新 Pod 表 Mongo 对等路由 | `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen`，`rte-2zeqfsysx46bq1p4st0sh` | `01A0DDBB-86A1-5CEA-8610-208DB842DCE2` |

两张新表只包含七条 VPC local、一条 `100.64.0.0/10` 服务路由和上述对等连接路由，均没有 `0.0.0.0/0`。系统表 `vtb-2zebvv47akvfr0cq15njq` 仍关联原七个 vSwitch；没有 NAT、EIP、新 vSwitch 或 SNAT。此准备没有改变现有 Pod、ALB、SmsCore、数据库的生效路由。

## 2. 候选来源 CIDR 与私网目的地

| 用途 | 候选来源或目的 | 当前证据与条件 |
|---|---|---|
| ACS 新 Pod k/i | `172.31.240.0/24`、`172.28.64.0/24` | 与本 VPC 七个旧 vSwitch 不重叠；**还未通过远端 IPAM/VPN/白名单核实，不得创建** |
| NAT 专用 vSwitch k | `172.31.241.0/28` | 与本 VPC 已知 vSwitch 不重叠；仅 NAT 使用，不纳入 ACS 选址 |
| 本 VPC MySQL、Redis、SmsCore | `172.27.176.0/20` 内的私网地址；SmsCore 为 `172.27.182.18:3090` | 本地 VPC local 路由比 NAT 默认路由具体；SmsCore ECS 安全组 `sg-2ze9w6ueqcnfc9wuov8k` 的 TCP 3090 入站已允许 `172.16.0.0/12`，但 SmsCore 应用白名单仍须单独核对 |
| 跨 VPC MongoDB | `10.0.0.0/24` 经 `pcc-i6zwr0k50cr119ezen` | 两张新表已复制去程；**对端返回新 /24 的路由及 Mongo 白名单尚未查证** |
| 本地 OpenVPN | 客户端 `10.8.0.6`，隧道下一跳 `10.8.0.5` | 当前推送了 `172.31.224.0/20`、`172.27.0.0/16` 及两个 Mongo 主机 /32 等；**没有候选新 Pod 网段** |

OpenVPN 本机 `route -n get 172.31.240.10` 与 `172.28.64.10` 均走家庭网络默认网关 `192.168.31.1`，不走 `utun6`。客户端配置不含手工 `route`，现有私网路由由服务端下发。若本地管理机需要直达新 Pod，须由 VPN 管理端推送两个新 /24 或以受控方式配置客户端路由，并核对 VPN 服务端转发、VPC 返回路径及目标安全组；只改本机路由不足以证明双向连通。不能把 OpenVPN 的 `10.8.0.4/30` 当成 Mongo 对等 VPC 的 `10.0.0.0/24`。

## 3. 数据库白名单只读核对

| 实例 | 当前范围 | 新 /24 是否已覆盖 | 发布前动作 |
|---|---|---|---|
| RDS `rm-2ze804wodhf86ei4p` | `default` 为 `172.16.0.0/12` | 是，两候选 /24 均在内 | 保持现有规则；实际私网 TCP/认证按项目验收 |
| RDS `rm-2ze49m8497xo6jf4a` | ACS 相关为旧 `172.31.224.0/20`、`172.28.48.0/20`；其余为旧 ECS/特定来源 | 否 | 保存原规则快照，按最小范围新建独立白名单分组加入两个新 /24；不覆盖旧组 |
| Redis `r-2zecyuog2a547nzk18` | 生产组仅 `172.27.182.155` | 否 | 确认实际使用项目；如需新 Pod 访问，独立追加两个新 /24，保留 ECS 来源 |
| Redis `r-2zewv5mmhvbrdmrxc4` | 旧 ACS `172.31.224.0/20`、`172.28.48.0/20` 及旧 ECS 来源 | 否 | 新来源使用前独立追加两个新 /24，保留旧组 |
| MongoDB 跨账号实例 | 当前账号 MongoDB API 不可核对实例白名单 | 未知 | 从实例管理账号只读核对 Mongo 实例、对端 VPC 路由、白名单/安全组和新来源回程；未拿到证据不得迁 Pod |

本轮未修改任何数据库白名单。以上覆盖关系只说明网络访问控制，不证明应用配置正确或认证成功。不同 .NET 项目实际使用哪个实例须按其授权运行配置逐项确认，不能仅凭实例名称推断。

## 4. 后续硬门槛和顺序

1. 冻结候选网段：核对完整 VPC/对等 VPC/OpenVPN/IPAM 地址池，确认三个网段不重叠、对端可为新来源配置回程，ACS、ALB 与现有安全组允许所需私网流量。
2. 对每个将迁入新网段的项目建立目的实例矩阵；先确认 MySQL/Redis/Mongo/SmsCore/OSS 私网地址与来源白名单，按最小 /24 修改并读回，保留旧来源。OpenVPN 服务端先下发新路由并实测客户端走隧道。
3. 重新核对 Yangu、M1X、现有 .NET 服务、ALB 和 SmsCore 的健康基线。七个旧 vSwitch **尚未关联新表**；在数据库/VPN门槛完成前，不迁关联，不创建 NAT。每个关联动作后检查私网与入口，并在 NAT 创建前保留可逆的系统表回退路径。
4. 新 Pod 网段诊断 Pod 分别验证 DNS、MySQL、Redis、Mongo、SmsCore 和 OpenVPN 双向路径，然后才开放该 vSwitch 的 SNAT；外网 EIP 正确不能代替私网验收。
5. 已在 ACS 运行的新零售与经销商查询必须纳入变更前基线；不能沿用旧文档中“所有 .NET 为零副本”的假设。Yangu、M1X 放在最后且逐角色验收。

**当前停点：**仅完成无业务关联的路由表准备。等待 Mongo 对端与 OpenVPN 服务端的真实路由/白名单证据和逐项目数据库实例映射后，才能确定候选 CIDR 并进入有生效影响的网络阶段。

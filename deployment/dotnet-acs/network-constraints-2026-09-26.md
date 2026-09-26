# ACS 共享 NAT：数据库与 OpenVPN 网段执行记录

时间：2026-09-26。北京生产账号 `1442361567788059`，VPC `vpc-2zervez1jgscsglpenrzo`；MongoDB 所属账号 `1427133103874458`，对等 VPC `vpc-2zeiz7b6j78n4xvevr0lt`。阿里云配置通过显式 Profile 的 OpenAPI 完成；仅记录地址、资源 ID 和 RequestId，不记录访问凭据或数据库内容。

## 已完成：不改变旧业务路由的准备

| 对象 | 当前状态 | 创建 RequestId |
|---|---|---|
| `acs-legacy-private-route` | `vtb-2ze9057j04btdfr3bofhy`；复制 `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen`；当前不关联旧 vSwitch | `01A0DDBA-9E64-5681-9872-659C3C205851`；路由 `01A0DDBA-DF90-54A5-915E-D99B152ACCBE` |
| `acs-egress-route` | `vtb-2zedknif7nxu7z397b4o6`；复制相同的 MongoDB 对等路由；关联下面两个新 Pod vSwitch | `01A0DDBB-650B-5529-8272-8933FA670F11`；路由 `01A0DDBB-86A1-5CEA-8610-208DB842DCE2` |
| `acs-egress-pods-k` | `vsw-2zevd832gq3313j6gv5sj`，北京 k，`172.31.240.0/24`；关联出口表 | `01A0DDC3-D396-5E60-934A-AC257D4BCF05`；关联 `01A0DDC4-06D2-5C6B-AF99-A72FF5C4D11A` |
| `acs-egress-pods-i` | `vsw-2zesy6off4gy39tqripzp`，北京 i，`172.28.64.0/24`；关联出口表 | `01A0DDC3-D6BA-5EDC-8A9E-08B61672C94E`；关联 `01A0DDC4-0901-55E0-8210-B14A9F9F2F8B` |
| `acs-nat-k` | `vsw-2zemuu9wf9pz0w83c7kpv`，北京 k，`172.31.241.0/28`；留在 VPC 系统表，不加入 ACS Pod 选址 | `01A0DDC3-D9E0-5F46-89CA-5168A91AFFD6` |

`kube-system/acs-profile` 已设置无显式选址 Pod 仍落旧 k/i 的兜底 selector；用短期 Pod 验证过注解注入，然后保留旧 k/i 并将两个新 Pod vSwitch 追加到 `vSwitchIds`。旧七个 vSwitch 仍关联原系统表 `vtb-2zebvv47akvfr0cq15njq`；旧表和新出口表都没有默认路由。**NAT、EIP、SNAT、旧 vSwitch 路由改动均未执行。** 10 个现有业务 Pod 均继续运行，未迁移。

## 新 Pod 网段数据面验证

在两个新 vSwitch 各创建并已删除一个短期诊断 Pod，分别取得来源 IP `172.31.240.110`、`172.28.64.181`。仅用 DNS 和 TCP 检查，不读取数据库记录或发送短信：

| 目的 | k / i 结果 | 依据 |
|---|---|---|
| MySQL `172.27.182.156:3306`、`172.27.182.54:3306` | 均成功 | RDS `rm-2ze804wodhf86ei4p` 原组已覆盖；`rm-2ze49m8497xo6jf4a` 新增独立白名单组 `acs_egress_pods`，仅两个新 `/24`；RequestId `01A0DDCB-DDE5-5043-A95C-15DF54638471` |
| Redis `172.27.182.157:6379`、`172.27.182.57:6379` | 均成功 | 两个实例分别新增同名独立白名单组，保留旧组；`r-2zecyuog2a547nzk18` RequestId `01A0DDCB-8158-5C2C-AD18-03684196463D`，`r-2zewv5mmhvbrdmrxc4` RequestId `01A0DDCB-CD8E-5422-90BE-CE3DC1DFC268` |
| SmsCore `172.27.182.18:3090` | 均成功 | 私网 TCP；应用级鉴权和发送结果仍须逐项目验收 |
| MongoDB 私网域名 `dds-2ze1a633d27d8ee41/42.mongodb.rds.aliyuncs.com:3717` | DNS 分别到 `10.0.0.113/114`，TCP **失败** | 旧 STOPMP Pod 在原 `172.31.224.0/20` 中连接成功，说明原链路稳定；不能把旧网段结果套用到新网段 |

MongoDB 所在 VPC 的系统路由表 `vtb-2zeg7935ye0r0izfi4lar` 当前仅有 `172.31.224.0/20 → pcc-i6zwr0k50cr119ezen` 和旧 VPN 单 IP `172.27.182.62/32` 的回程路由，缺少两个新 `/24`。MongoDB 实例 `dds-2ze1a633d27d8ee4` 的 `dgye_acs_private` 白名单也仅含旧 k `/20`。因此新 Pod 私网连接失败有两处明确阻断。现有本机 `mongo-vpn-check` Profile 已验证属于 MongoDB 所属账号，无需重新登录；但对端生产路由与数据库白名单的追加必须按明确对象和范围授权后执行。写后先读回，再重建短期诊断 Pod 验证两个区，成功前**不迁移业务 Pod**。

## OpenVPN 边界与后续顺序

本机 OpenVPN 已提供访问**现有** `172.31.224.0/20`、`172.27.0.0/16` 和 MongoDB 私网节点的路由。目前本机到新 `172.31.240.0/24`、`172.28.64.0/24` 不经 VPN。此次云侧 Pod 出网和 Pod 到数据库不依赖本机直达新 Pod IP；因此 OpenVPN 服务端加路由不是创建隔离 vSwitch 或诊断 NAT 的前置条件。若未来确需本机直接连接新 Pod IP，届时另行核对 VPN 服务端推送、转发、VPC 回程和安全组；不能只改本机路由。

后续按顺序：① 获准后补 MongoDB 对端两个精确回程路由及独立白名单并重测；② 重读旧七个 vSwitch、三张路由表、ACS 选址与业务健康；③ 逐个将旧 vSwitch 关联到不含默认路由的 `acs-legacy-private-route`，每次检查私网和入口；④ 确认系统表仅留下 NAT 专用 vSwitch 后，再创建 NAT/EIP 并验证自动路由、两新网段 SNAT；⑤ 逐项目按发布门槛迁移。任一步失败暂停，不用公网出口成功替代 MySQL、Redis、MongoDB、SmsCore 私网验收。

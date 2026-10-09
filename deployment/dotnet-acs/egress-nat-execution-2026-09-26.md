# 北京 ACS 公共出口：2026-09-26 网络实施记录

状态：**网络基础设施与新 Pod 网段的固定公网出口已完成并验证；网络变更当时只验证了诊断 Pod，后续部分 .NET 工作负载已经位于新网段。项目 SDK、供应商白名单和资金/短信业务验收仍未全部完成。** 操作均显式使用阿里云 CLI Profile `ruishi-prod-acr`、地域 `cn-beijing`、生产账号 `1442361567788059`，ACS 对象通过短时凭据访问 Kubernetes API。临时访问配置未保存到仓库。

## 最终拓扑

| 对象 | 实际值与状态 |
|---|---|
| VPC / 集群 | `vpc-2zervez1jgscsglpenrzo` / `ruishi-prod-acs` |
| 旧业务路由表 | `vtb-2ze9057j04btdfr3bofhy`；关联原七个 vSwitch；保留 local、服务和 `10.0.0.0/24 → pcc-i6zwr0k50cr119ezen`，**无默认路由** |
| NAT 专用系统表 | `vtb-2zebvv47akvfr0cq15njq`；仅关联 `vsw-2zemuu9wf9pz0w83c7kpv`；自动默认路由指向下述 NAT |
| 新 Pod 出口表 | `vtb-2zedknif7nxu7z397b4o6`；仅关联新 k/i 两个 Pod vSwitch；默认路由 `rte-2zeuknsfy00h33ly2j2bd → ngw-2zetnd6golba2sju2q7jo` |
| 公网 NAT | `ngw-2zetnd6golba2sju2q7jo`；`Enhanced`、`CrossAZ`、`internet`、`EipBindMode=NAT`、`PostPaid/PayByLcu`，`Available` |
| 固定 EIP | `eip-2zeapte07xmvayr4852h5` / `39.96.67.239`；普通 BGP、`PayByTraffic`、10 Mbps 上限，绑定该 NAT |
| 稳定 SNAT | `172.31.240.0/24` / `vsw-2zevd832gq3313j6gv5sj`：`snat-2zep79glnrcsp3t1lo7gh`；`172.28.64.0/24` / `vsw-2zesy6off4gy39tqripzp`：`snat-2zembio6rw2zqoo9ybid9`；均指向同一 EIP，`Available` |
| DNAT | 转发表 `ftb-2zektw6a15v6mwwpxhmt3`，条目数 0 |

新网段的完整 MySQL、Redis、MongoDB 回程和白名单准备见[网段记录](network-constraints-2026-09-26.md)。`acs-profile` 的无显式选址兜底仍指向旧 k/i；仅为诊断 Pod 设置了新 vSwitch 注解，现有业务 Deployment 未修改。

## 写操作与读回

| 操作 | RequestId / ClientToken 摘要 | 读回结果 |
|---|---|---|
| 旧 vSwitch `j → g → l → h → i → k → f` 逐个关联旧业务表 | j `01A0DDE5-FA7E-5573-BEEF-E54088F8AB63`；g `01A0DDE6-C6F2-536E-8CAE-DBF52853D166`；l `01A0DDE6-E301-5D05-93CE-41C013176E64`；h `01A0DDE6-FDA0-5949-A16E-3A953B603CC9`；i `01A0DDE7-1939-5F79-8A5D-48B6314D9AD8`；k `01A0DDE7-33AA-548C-8523-FA1B5FB120EF`；f `01A0DDE7-4F9D-56D0-82C5-CA703E3320D7`；token 前缀 `ruishi-egress-20260926-assoc-` | 每步 `DescribeVSwitchAttributes=Available` 且关联正确，三表 12 条路由在 NAT 创建前相同且无默认路由；Yangu/M1X HTTPS 401、网站 ECS 80/443、SmsCore 3090 每步保持基线 |
| 创建 NAT | `01A0DDE8-265C-57F1-8C49-66A65BB2EB3F` / `ruishi-egress-20260926-nat-create` | 等待至 `Available`；系统表自动默认路由仅影响 NAT 专用 vSwitch；旧业务表始终无默认路由 |
| 分配并绑定 EIP | 创建 `01A0DDE8-9CC0-53D9-945E-E320835E8BC9`；绑定 `01A0DDE8-CF9A-5DC7-87DC-D5AADF50B45B`；token 后缀 `eip-create`、`eip-bind` | `InUse`，绑定对象是该 NAT，公网地址与 10 Mbps/按流量参数正确 |
| 出口表默认路由 | `01A0DDE9-04C9-51D2-AC21-CC29AE09E562` / token 后缀 `route-egress-default` | `Available`，仅出口表与 NAT 专用系统表有 `0.0.0.0/0` |
| 诊断 `/32` SNAT | k `01A0DDEB-AE66-5D52-AC2A-06D0AB8B2F24`、i `01A0DDEB-C55E-55AD-B976-6E1AD379A7AB`；原条目 `snat-2zewi1z793vndbatphq67`、`snat-2zervkl30aorjzplqso4l` | 初始诊断 Pod `172.31.240.112`、`172.28.64.183` 均从固定 EIP 出网；重建取得 `.113`、`.184`，旧 `/32` 不匹配时两区均无法出网 |
| 两条新 vSwitch 稳定 SNAT | k `01A0DDEE-31E9-5077-9C2A-FCCBF11FEB66`、i `01A0DDEE-49E8-5C64-A556-CA2E281492A0`；token 后缀 `snat-vsw-k/i` | 重建诊断 Pod 两区经 `ipinfo.io` 和 `checkip.amazonaws.com` 均读到 `39.96.67.239` |
| 删除临时 `/32` SNAT | k `01A0DDEE-A8A2-5116-B3D4-A4C19C8BAF3F`、i `01A0DDEE-B8EF-5596-B731-FE2C92854A2F` | SNAT 表仅剩两条新 vSwitch 规则；删除后公网回显仍一致；诊断 Pod 已清理 |

诊断期间，新 k/i 两区各自到两组 MySQL、两组 Redis、SmsCore 以及 MongoDB 双节点的 TCP 连接均成功；稳定 SNAT 后再次检查主要私网端口和双 MongoDB 节点均成功。两区到微信 API HTTPS 可达。公网回显的两个独立目标一致；`api.ipify.org` 拒绝连接、`ifconfig.me` 超时是该单个目标的失败，不作为整体 NAT 验收依据。

网络变更完成当时，10 个原有业务 Pod 均仍在旧网段，重启数为 0；Yangu、M1X 原 HTTPS 入口保持 401，网站 ECS 80/443 与 SmsCore 私网 3090 继续可达。此后部分 .NET 工作负载被安排到新 Pod vSwitch，当前位置以[现场交接快照](HANDOVER-2026-09-26.md)重新读回为准。未创建 DNAT、未修改 ALB、DNS、SmsCore ECS 或旧七网段的 SNAT；后续项目部署和调度不应被倒推为本次网络变更的一部分。

账号询价 API 对北京增强型跨可用区 NAT 实例费返回标价 `0.23 元/小时`、当前优惠后 `0.1955 元/小时`（RequestId `01A0DDE7-7871-55BF-BD1E-85CFD70C49A8`）。EIP 保有和 NAT 双向处理、公网出流量另按实账计；优惠和账单以实际周期为准。

## 后续发布门槛与回滚

当前仅完成**空的新业务网段出口**。任何 Java 或 .NET Deployment 迁入新 vSwitch 前，按[出口手册](egress-nat.md)完成该项目实际外呼、旧短信通道、任务副作用、供应商新 EIP 白名单、SDK 调用和告警验收。用户正在使用的 Yangu、M1X 仍在旧网段，迁移需项目级窗口与回滚准备。现有新零售、经销商等应用也未因本次网络步骤重新调度。

如单项目后续出现异常，先恢复该 Deployment 原选址并核对外部业务结果，不撤销共享出口。若在业务迁入前需要撤销网络出口，先删除两条新 vSwitch SNAT 和出口表默认路由，确认无新网段业务 Pod；旧七个 vSwitch **保持在无默认路由的旧业务表**，不得直接解绑回已经有 NAT 默认路由的系统表。固定 EIP 不作为常规回滚对象释放。

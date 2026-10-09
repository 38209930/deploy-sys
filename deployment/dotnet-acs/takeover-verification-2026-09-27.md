# 接手核验记录：2026-09-27 00:01 CST

接手人按[交接快照](HANDOVER-2026-09-26.md)第一步完成只读核验。本次未做任何写操作、未读取 Secret 值、未启动 Worker。所有 CLI 调用显式使用 Profile `ruishi-prod-acr`、地域 `cn-beijing`；ACS 通过短时 kubeconfig 访问，临时文件 0600 权限、脚本退出即删除。

## 身份

`sts GetCallerIdentity`：账号 `1442361567788059`，RAM 用户 `power-application-user`，RequestId `01A0DE6D-B6C7-5F62-8455-7B6434442ADF`。

## 网络出口读回

| 对象 | 读回结果 | RequestId |
|---|---|---|
| NAT `ngw-2zetnd6golba2sju2q7jo` | `Available`、Enhanced、CrossAZ、`EipBindMode=NAT`、PostPaid/PayByLcu | `01A0DE6D-F1F0-5F67-A68A-9BB5F12404E7` |
| EIP `eip-2zeapte07xmvayr4852h5` | `InUse`、`39.96.67.239`、10 Mbps、绑定该 NAT、PayByTraffic | `01A0DE6D-F3AF-551B-BF1B-6114B2D1202C` |
| SNAT 表 `stb-2zewws9r3mpb7ne3b6to8` | 仅两条：`172.31.240.0/24`（snat-2zep79glnrcsp3t1lo7gh）、`172.28.64.0/24`（snat-2zembio6rw2zqoo9ybid9），均 `Available` 指向该 EIP | `01A0DE6D-F547-5168-B4C7-4BF702105C06` |
| 路由表 `vtb-2ze9057j04btdfr3bofhy`（旧业务） | 无默认路由；保留 local、服务网段与 `10.0.0.0/24` 自定义路由 | — |
| 路由表 `vtb-2zebvv47akvfr0cq15njq`（NAT 系统表） | 有 `0.0.0.0/0` | — |
| 路由表 `vtb-2zedknif7nxu7z397b4o6`（新出口表） | 有 `0.0.0.0/0` | — |

与[网络实施记录](egress-nat-execution-2026-09-26.md)一致，无漂移。

## ACS 工作负载读回

副本数与交接快照一致：DGYE、VET 为 0；售后 Worker 为 0；其余 1/1，全部 Running、重启 0。dgye 两个历史诊断 Pod（ErrImagePull / Completed）仍在。

实测 Pod IP 与所属网段：

| Pod | IP | 网段判断 |
|---|---|---|
| ai-study-back | `172.28.64.186` | 新 SNAT 网段（北京 i） |
| ai-study-worker | `172.31.240.135` | 新 SNAT 网段（北京 k） |
| service-order-front / back | `172.31.240.123` / `172.31.240.122` | 新 SNAT 网段 |
| points-mall-back / worker | `172.31.240.138` / `172.31.240.144` | 新 SNAT 网段 |
| agent-query-api | `172.31.239.38` | 旧网段（`172.31.224.0/20`），出口不经新 NAT EIP |
| new-retail-front / back / worker | `172.28.53.146` / `172.31.239.26` / `172.31.239.29` | 旧网段 |
| Java 全部（stopmp/etbst/ddmp/yangu/m1x） | `172.31.239.x` | 旧网段 |

注意：部分 .NET Pod 为快照后新调度（ai-study-back 约 9 分钟、points-mall 约 1 小时、service-order 约 80 分钟、agent-query 约 3 分钟），副本与网段未变，符合当日迁移后的正常重调度；Yangu（12h）、M1X（13h/22h）Pod 未动。经销商 Pod 这次重创建原因交接文档未记录，需留意。

## 入口健康探测（只读 HTTPS）

- 200：`rsst-back-api`、`rsod-front-api`、`rsod-back-api`、`rsjf-back-api`、`ns-front-api`、`ns-back-api`、`4l-api`（共 7 个 .NET 域名）。
- 401：`stop-mp-api`、`et-bst-api`、`ddmpapi`、`rsapi`、`m1x-api`（Java 域名；401 与交接记录的 Java 基线一致，健康端点需认证，不是故障）。

**探测方法教训**：不要用 ALB 域名 + `Host` 头做 HTTPS 探测——TLS SNI 是 ALB 域名时握手被 ALB 重置，`curl` 返回 000，极易误判为入口故障。必须用真实业务域名直连（SNI 与 Host 一致）。已补录到[运维备忘录](operations.md)。

## 旧 ECS 只读盘点（与交接快照的差异）

`ecs DescribeInstances` 共 11 台。与交接快照"AI、售后、积分、经销商四个旧 .NET ECS 为 Running"的差异：

| 实例 | 名称 | 快照时 | 本次读回 |
|---|---|---|---|
| `i-2ze2s8pzq0kvqu28iml8` | api-自习室 | Running | **Stopped** |
| `i-2ze710cj1qpe7s7zv5sq` | 售后工单 | Running | **Stopped** |
| `i-2ze3w6i78cobsmmfo2y9` | 积分商城 | Running | Running |

其余：SmsCore `i-2ze38hdx1sufodad2kz0`（172.27.182.18）Running；website、明眸、明眸 v2、openclaw、vpn-server、开发服务器、zhuda-kuaiqu Running。未发现名称为"经销商"的实例，经销商旧 ECS 对应关系待确认。

差异原因**已由服务器管理员确认为主动停机**：ActionTrail 记录 2026-09-26 23:51:41 / 23:51:53 CST 两次 `StopInstances`（RequestId `01A0DE6A-71B5-58D5-9218-D1A481585699`，来源 IP `114.86.9.82`，与前一位运维的操作 IP 一致），即交接快照写完约 12 分钟后管理员主动停机。ActionTrail 核查过程：23:00–23:26 CST 有同一 IP 的 RunCommand、镜像缓存清理、ACR 构建等写操作，`api-自习室`、`售后工单` 两台为被停对象；`积分商城` 一台保持 Running。

管理员已确认为主动停机，含义据此更新：

1. AI 旧 FrontApi 所在 ECS 已停机。若 AI 前台仍有流量指向该实例，入口会失败；管理员停机即视为已确认无影响，后续发现 AI 前台异常时先联想到这里，再查入口和 DNS。
2. 售后旧 ECS 停机意味着旧 Worker 不会自动拉起，重复消费风险进一步降低；但交接清单第 6 条仍然有效——启动新 Worker 前需确认在途任务与任务锁，停机时间点（23:51 CST）之后的在途任务状态由业务侧确认。

## 后续

- 生产写操作（启动售后 Worker、迁移 FrontApi、网络调整）仍需按交接规则单独安排窗口和授权，本次未执行。

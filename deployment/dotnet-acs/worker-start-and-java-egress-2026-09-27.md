# 变更记录：售后 Worker 启动与 Yangu/M1X 出口迁移（2026-09-27 00:30 CST）

授权：服务器管理员于 2026-09-27 指示——启动售后工单 Worker；Yangu、M1X 当前已无在用用户，尽快迁入新公网出口 EIP；如失败可撤回本次操作。执行人按[阿里云 API 使用说明](aliyun-api-operations.md)全程使用 Profile `ruishi-prod-acr`、短时 kubeconfig（用后已删除），未读取 Secret 值，未触碰共享路由/SNAT/EIP/SmsCore。

## 任务一：售后工单 Worker 启动

前置：旧 Worker ECS `i-2ze710cj1qpe7s7zv5sq` 已由管理员于 2026-09-26 23:51 CST 主动停机（见[接手核验记录](takeover-verification-2026-09-27.md)），自启不可能；Redis 任务锁为固定 TTL，已过期。Deployment 预部署时 Pod 模板已带新出口注解，无需额外选址修改。

| 字段 | 值 |
|---|---|
| 对象 | `service-order/service-order-worker`，UID `7f96adec-0576-44d2-85a3-f0acc04e0b9a` |
| 变更前 | replicas=0，resourceVersion `1357658` |
| 镜像（digest 未变） | `sha256:a80e8b0eab68dc478db3ad417013379034e1eb9c2d10d9340687a88e13187474` |
| 操作 | `kubectl scale --replicas=1`（00:21 CST） |
| 变更后 | Pod `service-order-worker-5fd6788b99-t972c`，IP `172.31.240.149`（新 SNAT 网段），1/1 Running、重启 0 |

启动日志证据：`ServiceOrder.Worker starting up...` 后，5 个 Quartz 任务按周期正常 start/completed 且无错误——`Task4ServiceOrderFactoryShipper`、`Task4SmsRetryCompensation`、`Task4ServiceOrderRefund`、`Task4ErpSyncCompensation`（单次耗时 18ms–2.7s）。回滚入口：`kubectl scale deploy service-order-worker -n service-order --replicas=0`。

## 任务二：Yangu、M1X 迁入新公网出口

方法：按[网络变更单](egress-nat-change-order.md)第 E 节，逐个把 Pod 模板注解 `network.alibabacloud.com/vswitch-ids` 由旧 k 单 vSwitch（`vsw-2zeagdbk8hizkkdw0ns42`）替换为新 k/i 两个 vSwitch，滚动重建。镜像、Secret、env、探针均未改动。三个对象迁移前 strategy：yangu-api 与 m1x-api 为 RollingUpdate（API 角色短暂新旧并行无害），m1x-worker 为 Recreate（无双跑），均未修改。

| 对象 | 变更前 resourceVersion | 旧 Pod IP | 新 Pod IP | 入口核验 |
|---|---|---|---|---|
| `yangu-api/yangu-api` | `1071859` | `172.31.239.9` | `172.31.240.150` | `rsapi.svision100.com/health/ready` 401（基线） |
| `m1x-api/m1x-api` | `1027325` | `172.31.239.7` | `172.31.240.152` | `m1x-api.svision100.com/health/ready` 401（基线） |
| `m1x-api/m1x-worker` | `799240` | `172.31.239.1` | `172.31.240.153` | 无 HTTP 入口；`Started WorkerApplication in 31.985s` |

镜像 digest（前后一致）：yangu-api `sha256:2cced795...85d231b51f`；m1x-api `sha256:138e66a3...89df2170b`；m1x-worker `sha256:ab724fbc...97737ac2c86`。M1X 保持 `APP_ROLE=api/worker` 各一 Pod。

**出口实测**：从已迁移的 m1x-api Pod 内部请求 `checkip.amazonaws.com`，返回 `39.96.67.239`，即固定 EIP——SNAT 生效。私网依赖：yangu 启动日志确认 MongoDB 双节点（`mgset-13123885`）从新网段连接成功；m1x readiness `/actuator/health` 通过。

回滚入口（单项目）：把对应 Deployment 注解恢复为 `vsw-2zeagdbk8hizkkdw0ns42`，Pod 回到旧网段即恢复原路径。共享 NAT/SNAT 不属于回滚对象。

## 残留风险与待办

1. 两项目的旧短信直连通道、微信/支付/供应商白名单无法从本次操作核实；管理员确认已无在用用户，风险由本次授权覆盖。如后续启用，先按[出口手册](egress-nat.md)第 3 节补验收。
2. 售后 Worker 的真实业务结果（工单流转、ERP 同步、退款、短信）与 24 小时观察仍需业务侧确认。
3. 其余 Java 项目（DGYE/VET 零副本，STOPMP/ETBST/DDMP 旧网段 1/1）未在本次授权范围，未改动。

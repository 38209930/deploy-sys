# 值班日志

每日巡检与运行统计的一句话记录；详细证据见同目录带日期的记录文件。

## 2026-09-27

- 00:30 变更完成：售后 Worker 启动 1/1，Yangu/M1X 迁入新出口（详见 [worker-start-and-java-egress-2026-09-27.md](worker-start-and-java-egress-2026-09-27.md)）。
- 上午巡检：ALB/NAT 云端指标正常；**当时本机至 ACS 的路由未走 VPN**，kubectl 私网 API 不可达，Pod 级巡检推迟到隧道恢复。
- 资源采样（17 个运行 Pod）：CPU 全部 < limit 2%；内存最高 ddmp-api 53%（RSS 44%），其余 ≤30%，均低于 80% 预警线；该时点无即时扩容迹象，不代表业务高峰容量结论。脚本 [resource-snapshot.sh](resource-snapshot.sh)。
- 前次云端统计（起止时间待原始指标核实；原记录的 09-27 10:30 CST 晚于本文 09:07 的复验时点，不能视为已核实的统计终点）：
  - ALB 443 总请求据前次记录约 29k，其中 09-26 约 28.4k（2XX 94.7%、4XX 3.2%、5XX 2.1%）；09-25 约 45、09-27 约 686。QPS 峰值 1.77，最大并发连接 10.5，前次记录称无 TLS 握手失败、上游连接错误及连接拒绝；以上均待按原始指标复算。5XX 的时间分布及其与发布窗口的关系尚未核实。
  - NAT 出口（即固定 EIP）：前次记录称峰值 < 0.01 Mbps（上限 10），无会话限制丢弃、无端口分配错误；原始指标待复核。NAT 自 09-26 21:29 CST 创建，之前无此数据。
  - 结论：**目前没有足以支持扩容决定的证据；也未覆盖业务峰值及任务周期**；继续按周采样观察 ddmp-api 内存趋势。
- 遗留：Pod 级三日重启计数因 VPN 断开未取（注：云监控无 ECI 指标、当时未核实 metrics-server，三日逐时 CPU/内存历史本身不可回溯，只能从现在起按周采样积累）。

### 2026-09-27 上午（VPN 恢复后补记）

- OpenVPN 已恢复，补做 Pod 级巡检：19 个 Pod 中 17 个业务 Pod 全部 Running、重启 0；dgye 两个历史诊断 Pod 维持原状（ErrImagePull/Completed，非运行负载）。
- 经管理员同意安装集群组件 `managed-metrics-server` v0.3.9.5（安装任务 `T-6ab8681c441e6701030032b3`，RequestId `01A0E056-ADF9-51CD-98A8-02668115CCDC`，08:50 完成）；`kubectl top pods -A` 验证可用，读数与 cgroup 采样吻合（ddmp 483Mi、yangu 486Mi）。该组件为托管形态，集群内不落业务 Pod。
- 云监控 ECI 指标评估结论：**不启用**——该账号 CMS 无 ECI 命名空间指标，开启需逐实例注入，且 metrics-server 已覆盖需求，属重复建设。
- 按管理员要求，`yangu-api` 与 `ddmp-api` 同列为内存趋势重点观察对象（2Gi 档，当前 24%，RSS 20%）。

### 2026-09-27 09:07 CST 交接复验

- 账号 `1442361567788059`、ACS `cebc88343a44b4d759aa983a47b787835`：STS 与 VPN 路由 `utun6` 读回；临时 kubeconfig 仅用于只读 Kubernetes API，已清理。
- `resource-snapshot.sh` 修复后对 17 个运行容器各采两次、间隔 1 秒：CPU/limit 约 0.1%–1.7%；DDMP memory.current 550.2 MiB/1 GiB、v1 RSS 458.3 MiB；Yangu memory.current 559.6 MiB/2 GiB、RSS 464.6 MiB。`kubectl top` 同时读得售后 Worker 1m/160Mi，而脚本为约 157.9 MiB、0.3% CPU limit。两者采样时点、工作集与 cgroup usage 口径不同，不能要求数值完全相等。1 秒 CPU 窗口仅供脚本核验，不覆盖峰值。
- 售后 Worker 近 6 小时日志末 150 行只出现四类 `Task4*`，不能据此确定注册总数；未取得注册清单、脱敏业务事件及外部结果，退款、短信、ERP 均待验收。
- 三日 ALB 5XX 分时原始序列、NAT 同窗口原始数据、短信生效配置及 AI Front 用户影响本轮尚未取得；旧网段五项目的真实公网依赖仍待逐项取证。详见[验收整改记录](acceptance-remediation-2026-09-27.md)。

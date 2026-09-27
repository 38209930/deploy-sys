# 积分商城 FrontApi 迁移执行记录（2026-09-27）

状态：ACS 已启动并通过新 ALB 定向健康检查；域名持有人已切换 DNS，权威及公共解析器已返回新 ALB。递归缓存过期后的普通域名请求及业务验收待记录。本文只记录已读回的事实，不含密钥或运行配置值。

## 对象与交接边界

- 账号 `1442361567788059`，北京 ACS `ruishi-prod-acs`，Namespace `points-mall`。
- 旧 ECS `i-2ze3w6i78cobsmmfo2y9` 的 `jifen90.api.service` 是 FrontApi；其进程注册 Redis MQ 消费者，因此采用先停旧、确认退出、再启动新实例的顺序。现有 ACS BackApi、Worker 未变更。
- 正式 Host `rsjf-front-api.svision100.com`。旧 DNS 指向 `alb-ay59r13w826vczc55d.cn-beijing.alb.aliyuncsslb.com`；新 ALB 为 `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`。DNS 由另一账号管理，生产 Profile 的 DNS API 返回 `IncorrectDomainUser`，域名持有人负责切换。
- 用户已授权本次积分商城生产运行配置读取与下发，且已确认 DNS 管理入口可操作。

## 成功步骤与读回证据

| 顺序 | 操作 | 结果与证据 |
|---|---|---|
| 1 | 核对源码、旧服务和现有 ACS 工作负载 | `release` 与远端同为 `60686dbb4795f089456040c5d9be7937f75f6e5b`；旧 Front 活跃；ACS 原仅有 Back、Worker 各 1/1。 |
| 2 | ACR 构建规则指向 `release` 后触发 Front 构建 | 仓库 `ruishi-dotnet-prod/points-mall-front` (`crr-vdgtaw2phsb1n76h`)，规则 `crbr-w6ybjtcvg2blshrm`；构建 `01A0E30B-89BE-5510-832C-8B52A97BB015` 成功，构建日志确认 SHA `60686db`。镜像 digest `sha256:4b1142ec50e6764a31ae4b3609517810129bfc6535dc5485511a01a2cb885780`。 |
| 3 | 核对并创建 Front 专用运行 Secret | 从旧 ECS 当前运行目录的三个配置文件生成 `points-mall-front-runtime-20260927-v1`，仅将已启用的 SmsCore endpoint 切为已验证私网地址；UID `99102c60-9380-4698-b350-2d9ca9476fd8`，创建后按键名及数据一致性读回。未打印或提交配置值。 |
| 4 | 创建零副本 Deployment 与 ClusterIP Service | `points-mall-front` Deployment UID `ea4ef89e-cfa0-44a7-8a11-3230f7d1672f`，镜像按 digest 固定，1 CPU/2 GiB，`Recreate`，Pod 模板显式包含两个 NAT 网段 vSwitch；Service UID `e788989c-b640-4aa1-82e8-c5037737289d`。服务端校验及读回通过。 |
| 5 | 创建精确 Host Ingress | `points-mall-front-alb` UID `5fcf4477-11c1-4389-9260-d7e33b7b97e9`，443 → `points-mall-front:8080`；控制器报告 `SuccessfullyReconciled`。零副本时新 ALB 返回 503，符合预期。 |
| 6 | 停止旧 ECS Front 并关闭自动拉起 | ECS Cloud Assistant CommandId `c-bj06yc23yudcjcw`、InvokeId `t-bj06yc23yuku8e8`，执行成功且退出码 0；读回 `active=inactive enabled=disabled pid=0`。 |
| 7 | 启动 ACS Front 一个副本 | 使用 Deployment `resourceVersion=1977669` 前置校验修改 `replicas: 0 → 1`；新版本 `1978993`。Rollout 成功，Pod `points-mall-front-5d5f9c68db-9dfh2` 为 1/1 Ready，IP `172.31.240.179`，位于新出口网段。 |
| 8 | 新 ALB 定向验收 | 保持原 Host/SNI 并定向连接新 ALB，`/health/live`、`/health/ready` 均为 HTTP 200，TLS 校验结果 0。就绪检查含数据库与 Redis 依赖。 |
| 9 | 域名持有人切换 CNAME | 用户确认已切换；`223.5.5.5` 与 `1.1.1.1` 查询均返回 `alb-olyb9enxszy3f42nnn.cn-beijing.alb.aliyuncsslb.com`，TTL 600 秒。本机递归缓存当时仍指向旧 ALB，普通请求暂为 502，待缓存过期复验。 |
| 10 | FrontApi 只读业务接口核对 | 保持正式 Host/SNI 定向新 ALB，`GET /public/info` 返回 HTTP 200，TLS 校验通过；未触发订单、短信或支付动作。 |

## 后续完成条件

1. 等待旧 DNS 缓存过期后核对普通公网 HTTPS 请求。旧 Front 已停机，仍缓存旧 ALB 的客户端在过渡期间可能收到 502。
2. 核对正式域名的前端业务请求、Redis 消费者单实例及自然消息处理结果；不以健康接口 200 代替业务验收。真实短信、支付或资金操作不在本次诊断中主动触发。
3. 核对 Front Pod 的真实公网调用出口和 SmsCore 受理记录；仅网络端口可达不代表短信送达。
4. 观察至少一个关键消费周期，记录错误、重启及重复消费情况。

## 已识别的发布问题与回滚

- 本次 ACR 手工构建把原标签模板 `acs-${GIT_COMMIT_ID:6}` 展开成 `acs-`，随后创建 `acs-60686db` 同 digest 别名；部署使用 digest，不受标签名影响。后续发布前应修正或替换标签模板，并再次核验构建 SHA 与 digest。
- DNS 尚由旧 ALB 管理时，旧 Front 停机至域名切换期间存在入口空窗。若新服务验收失败，先将 ACS Front 缩至 0 并确认 Pod 退出，再在 ECS `systemctl enable --now jifen90.api.service`，核对原域名健康；若 DNS 已切换，还需由域名持有人切回旧 ALB。
- 回退业务镜像时保留当前 Pod 网络选址，避免历史 ReplicaSet 带回旧网段。

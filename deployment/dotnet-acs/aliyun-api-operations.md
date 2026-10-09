# 阿里云 API 与 ACS 操作说明

适用环境：北京生产账号 `1442361567788059`、ACS `ruishi-prod-acs`。本页是给接手同事的**操作入口**；生产写操作还需对应项目的变更单、对象和范围授权。所有示例为只读命令，不读取或显示 Secret 内容。

## 1. 登录与身份校验

本机安装阿里云 CLI 后，每次调用显式带 `--profile ruishi-prod-acr --region cn-beijing`，涉及资源的接口再带 `--RegionId cn-beijing`。当前机器默认 Profile 指向其他账号，不能依赖默认值。

```bash
aliyun sts GetCallerIdentity --profile ruishi-prod-acr --region cn-beijing
```

只有返回的 `AccountId` **精确等于** `1442361567788059` 才继续。2026-09-26 23:39 此命令成功；凭据会过期，交接后要重新运行。鉴权失败时先区分：CLI 凭据过期、RAM 没有对应 OpenAPI 权限、Kubernetes RBAC 不足。只有凭据失效才重新登录；不要把权限不足解释成需要更换账号。登录由本人在官方 CLI/OAuth 页面完成，不在聊天或工单传输密钥。

## 2. 查询云资源

```bash
aliyun vpc DescribeNatGateways --profile ruishi-prod-acr --region cn-beijing --RegionId cn-beijing --NatGatewayId ngw-2zetnd6golba2sju2q7jo
aliyun vpc DescribeEipAddresses --profile ruishi-prod-acr --region cn-beijing --RegionId cn-beijing --AllocationId eip-2zeapte07xmvayr4852h5
aliyun vpc DescribeSnatTableEntries --profile ruishi-prod-acr --region cn-beijing --RegionId cn-beijing --SnatTableId stb-2zewws9r3mpb7ne3b6to8
```

核对 VPC、NAT `Available`、EIP `InUse` 且绑定目标 NAT、10 Mbps、两条新 Pod vSwitch 来源和同一出口 IP。路由表及变更前后快照见[网络实施记录](egress-nat-execution-2026-09-26.md)。查询 ECS 实例状态可用 `ecs DescribeInstances`；要确认 **systemd 服务**，必须对具体 ECS 另做服务级只读核对，实例 `Running` 不够。

ACR 的 OpenAPI 用来检查实例、命名空间、仓库、Codeup 绑定、构建规则/记录和 digest；参数及资源 ID以现网读回为准。构建时核对记录中的**源码 SHA、Dockerfile、结果和镜像摘要**，不可只看 tag。过去 Codeup API 曾对单个仓库返回 `SOURCE_ACCOUNT_NOT_AVAILABLE`；同一条件下不重复触发构建，先修复 Codeup 绑定。ACR 构建并发有限，按角色串行。

## 3. 取得短时 ACS API 凭据

ACS 工作负载由 Kubernetes API 管理。通过 `cs DescribeClusterUserKubeconfig` 获取短时私网集群访问配置；不要把 API 返回的 kubeconfig 打到终端、聊天或日志。以下脚本只输出**受保护临时文件路径**，并在当前 shell 结束时删除。环境需有 `python3`、`aliyun`、`kubectl`；若本机到私网 API 不通，先核对 OpenVPN 路由，不改集群权限来绕过网络问题。

```bash
umask 077
export KUBECONFIG="$(python3 - <<'PY'
import json, os, subprocess, tempfile
cmd = ['aliyun', 'cs', 'DescribeClusterUserKubeconfig',
       '--ClusterId', 'cebc88343a44b4d759aa983a47b787835',
       '--PrivateIpAddress', 'true', '--TemporaryDurationMinutes', '30',
       '--profile', 'ruishi-prod-acr', '--region', 'cn-beijing']
data = json.loads(subprocess.check_output(cmd, text=True))
assert data.get('config') and data.get('expiration')
with tempfile.NamedTemporaryFile(prefix='acs-kube-', delete=False) as f:
    os.fchmod(f.fileno(), 0o600)
    f.write(data['config'].encode())
    print(f.name)
PY
)"
trap 'rm -f "$KUBECONFIG"' EXIT
kubectl get deployment -A
```

临时凭据过期后重新生成，不将文件复制进仓库。`kubectl` 是 Kubernetes API 客户端，仍属于 API 方式；不要让接手人手工在控制台粘贴一大段生产 YAML或 Secret。获取访问配置不等于已获得所有 Namespace 的写权限。

## 4. 生产对象只读检查

```bash
kubectl get deployment -A
kubectl get pods -A -o wide
kubectl get ingress -A
kubectl -n points-mall describe deployment points-mall-worker
kubectl -n points-mall logs deployment/points-mall-worker --since=30m --tail=100
```

只查**目标对象和有界日志**，不运行 `kubectl get secret -o yaml`、`kubectl describe secret` 或会打印环境变量值的命令。`get secret` 只列名称时也应只在有必要的 Namespace 使用。Ingress 存在不保证后端有副本；先看 Deployment `READY`、Pod 重启和 Service，再做 HTTPS Host/证书及业务核对。

## 5. 写操作记录规范

- 先核对账号、地域、对象 ID和当前状态，再保存变更前快照。存在同名对象时比较实际差异，不能直接覆盖。所有提交均限定一个项目或变更单范围。
- OpenAPI 创建接口支持 `ClientToken` 时使用本次变更稳定 token。检查命令退出码和响应业务状态，记录 `RequestId`、资源 ID、参数摘要和读回状态；接口超时先查询，不能盲重试。ACR 曾出现业务鉴权失败但 CLI 退出码为 0。
- Kubernetes API 写入记录 UID、`resourceVersion`、变更摘要和读回的期望/就绪副本。共享 ACR 凭据助手、ALB 监听、路由、SNAT 先留前后快照，并复核既有项目。
- 配置下发只针对授权的项目 Secret；文档记录 Secret **名称及版本**，不记录值、完整连接串、证书内容、令牌、手机号和请求体。不要把真实生产配置放进镜像或提交。
- 发布使用固定镜像 digest。Worker 单副本不等于绝对不会重复执行；旧服务退出、任务幂等和结果核查仍是发布门槛。

资源和项目实际状态见[交接快照](HANDOVER-2026-09-26.md)；生产网络回滚顺序见[网络变更单](egress-nat-change-order.md)。

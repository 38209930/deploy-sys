# .NET 零副本预部署执行记录（2026-09-26）

状态：部分完成。已创建 ACR 私有仓库；尚未取得可用镜像，未创建 ACS .NET 工作负载。以下只记录资源和调用结果，不含凭据或生产配置。

## 固定目标与验证

- CLI 每次显式使用 `--profile ruishi-prod-acr`；STS 返回生产账号 `1442361567788059`。当前默认 Profile 指向另一账号，不能用于本轮操作；现有指定 Profile 可用，无需重新登录。
- 地域 `cn-beijing`；ACR 实例 `cri-73ffxebpi6ruw6sn`；ACS 集群 `cebc88343a44b4d759aa983a47b787835`。
- ACR 命名空间 `ruishi-dotnet-prod` 已存在；创建前仓库数 0，创建后只读返回 13。
- ACS 私有 API 连通。使用 15 分钟有效的临时集群配置进行只读和授权核对；配置仅用于受保护的临时文件并已清理。五个目标 ACS Namespace 均不存在；当前身份对 Namespace、Deployment、Service 的 `create` 授权检查返回 `yes`。实际创建前仍需按对象执行服务端校验。

## ACR 仓库创建结果

均通过 `CreateRepository` API 创建为 `PRIVATE`，启用 Tag 不可变。结果业务码 `success`，随后 `ListRepository` 读回总数 13。

| 仓库 | RepoId | RequestId |
|---|---|---|
| `ai-study-back` | `crr-ts4ie274rsl4e5s8` | `01A0DC47-5A6C-549F-9F5E-0C978A2EFF23` |
| `ai-study-worker` | `crr-bdsng7yy7sw22xla` | `01A0DC47-5CAB-5B1B-80ED-6B68B86017B0` |
| `service-order-front` | `crr-g81gg6q5ug03sf67` | `01A0DC47-5EDD-5E48-B5C6-4BF1BDDFDB34` |
| `service-order-back` | `crr-xb24atsy4999plnt` | `01A0DC47-60CE-53B6-B135-4709DB9AF600` |
| `service-order-worker` | `crr-svf8bbfgno27xoxx` | `01A0DC47-62DE-535E-A57E-2F8B300D8CE6` |
| `points-mall-front` | `crr-vdgtaw2phsb1n76h` | `01A0DC47-3467-5A7F-AEE6-7820D82C235D` |
| `points-mall-back` | `crr-wl4s6tkt2g800cb1` | `01A0DC47-6566-5D64-93F0-D40BEBAAD2D2` |
| `points-mall-worker` | `crr-2cjij63p35rdmn30` | `01A0DC47-67BB-5FA9-99C1-095915FEB4E5` |
| `new-retail-front` | `crr-15tsn10lfuopeca3` | `01A0DC47-6A48-5E8B-AA0F-174D106E764E` |
| `new-retail-back` | `crr-jgcdoev5lsv3c13n` | `01A0DC47-6C90-53C0-9365-508C5C9E876F` |
| `new-retail-worker` | `crr-6qbw9xs9j2g89y07` | `01A0DC47-6ED7-552A-8B47-10D74F832381` |
| `agent-query-front` | `crr-btjw2p53qbwchqou` | `01A0DC47-70FB-5654-8731-CBD005699D02` |
| `agent-query-back` | `crr-rf3urokc74m8r8xx` | `01A0DC47-7343-5DEA-883F-4FB3DEC2A241` |

## 当前阻断与下一步

- `CreateRepoSourceCodeRepo` 尝试绑定 `points-mall-front` 至 Codeup `659a5cefd64a2eb2dceb72f3/jifen-mall/jifen-api`，返回 `SOURCE_ACCOUNT_NOT_AVAILABLE`，RequestId `01A0DC47-C06D-564D-881D-D506DA7BB28A`。CLI 退出码为 0，但业务码表示失败，不能视为绑定成功。需在 ACR 实例核对 Codeup 账号绑定，并完成仓库代码源绑定；凭据不进入聊天。
- AI 自习室：本机未提交业务修改尚未纳入冻结版本。售后工单：Dockerfile 依赖本机构建产物及私有 NuGet。积分商城：需冻结发布 SHA 并核对 Dockerfile 构建上下文不带敏感文件。新零售：需独立产品发布引用、镜像配置排除和非 root 适配。经销商查询：独立宿主及接口/数据适配尚未交付。这些由项目会话完成。
- 在代码源、冻结 SHA、可独立云构建的 Dockerfile 和镜像验证齐备后，逐角色通过 API 建规则、串行构建并记录 digest；随后创建对应 ACS Namespace、ServiceAccount、零副本 Deployment 和 API ClusterIP Service。
- 本轮未创建构建规则、镜像、ACS .NET Namespace/Deployment/Service、Secret、Ingress、NAT/EIP；未启动 Pod，未改变 Java 运行资源、DNS 或旧 ECS。

## API 操作约束

每次先用 STS 核对账号；阿里云 CLI 返回成功退出码时仍核对 JSON `IsSuccess`/`Code`。创建前查询同名对象，结果不明先读回。ACS 资源使用私有 Kubernetes API及短时访问配置；保留 TLS 校验，记录 UID/resourceVersion。镜像构建必须与冻结提交及 digest 对应，不使用占位镜像。当前阶段所有新增 Deployment 必须为 `replicas: 0`，不扩大 ACR 拉取权限或下发生产 Secret。

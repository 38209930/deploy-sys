# 实施与交接计划：deploySys 新项目接入 ACR / ACS / OSS

日期：2026-09-27。状态：**方案已整理，功能尚未实施，云端验证尚未执行。**

本文件是实施顺序、边界及验收依据。阅读文档不构成执行其中云端写操作的授权。当前文档任务仅允许文档编写、必要校验及 Git 交付；后续实施从 D00 开始，不自动恢复历史部署任务。

## 1. 目标与执行导航

用户在一级菜单选择“新增项目”，逐步输入仓库、发布分支、运行参数和已准备的配置引用，系统建立新项目专属资源及本地菜单。后端采用“本地发指令 → Flow 构建 → ACR → 人工确认 → 固定 digest 发布 ACS”，后台管理前端使用已有 OSS Bucket。

### 1.1 范围

- 支持 Java API、.NET API、Worker；一个项目可包含多个服务。
- 支持后台管理前端本地构建并发布 OSS。
- Java 镜像进入 `ruishi-java-prod`，.NET 镜像进入 `ruishi-dotnet-prod`。这两个名称是 **ACR 命名空间**，不等同于 Kubernetes Namespace。
- 后端默认新建项目专属 Kubernetes Namespace、ACR 仓库、Flow 流水线；前端使用专属 OSS 前缀。
- 发布分支按服务配置，默认建议 `release`，允许新零售等项目使用已确认的其他分支。
- 推送不自动构建。构建和上线是不同动作；首次上线与日常上线均确认准确对象和版本。
- 第一版向导仅面向 CLI；生成的普通操作菜单兼容现有执行器。保留现有普通命令项目的录入能力。
- 不新增 ECS 部署或重启入口，不提供 PC 部署 API；后台管理系统使用 OSS 发布入口。
- 不自动迁移历史项目、不搭建后台守护或定时任务、不增加自治代理、不引入 SLS 长期日志系统。

### 1.2 三类步骤不得混淆

| 编号 | 用途 | 执行时机 |
|---|---|---|
| D00—D08 | 实现功能、验证能力、交付代码 | 获得功能实施指令后 |
| N00—N12 | 使用向导接入一个具体新项目 | 用户选择项目并确认范围后 |
| T01—T18 | 验证保护规则和功能 | 先离线，再在获授权的隔离对象中 |

每一步必须记录状态、证据及下一步编号。只有前置步骤通过才进入后续步骤；阻塞不等于失败重试许可。

## 2. 已有证据、常量与未决门槛

### 2.1 证据来源与可信边界

本计划核对的实现基线是提交 `1089bf77a20bd964188e84d7f27ff05e7411c4ef`，所在历史工作线为 `deploy/acs-acceptance-evidence`。本文件独立交付到 release/master，**不代表这些分支已经合入该工作线的全部实现**。

| 来源 | 可以支持的结论 | 不能据此推断 |
|---|---|---|
| [ETBST 交接记录](https://github.com/38209930/deploy-sys/blob/1089bf77a20bd964188e84d7f27ff05e7411c4ef/deployment/flow/HANDOVER-flow-release-etbst-2026-09-27.md) | 构建流水线 `5300352` run `4`、发布流水线 `5300396` run `2` 曾成功 | 当前工具版本、权限和新仓库访问仍必然可用 |
| [Flow 操作与验收记录](https://github.com/38209930/deploy-sys/blob/1089bf77a20bd964188e84d7f27ff05e7411c4ef/deployment/flow-release-commands.md) | digest、人工确认、镜像更新曾分别验证 | 新增的一条命令完整编排已经端到端重跑 |
| [后续出口与发布记录](https://github.com/38209930/deploy-sys/blob/1089bf77a20bd964188e84d7f27ff05e7411c4ef/deployment/dotnet-acs/egress-release-execution-2026-09-27.md) | 当时 API Server 为 1.36.1；固定出口及单副本约束已实施 | 可以重新执行迁移、给共享策略扩范围 |
| [现有脚本](https://github.com/38209930/deploy-sys/blob/1089bf77a20bd964188e84d7f27ff05e7411c4ef/scripts/flow-release.sh) | `push/build/deploy/status/apply` 及现有参数语义 | 已能直接安全用于所有新项目 |

历史文档保留了早期“待办”段落；按有日期的后续证据判断，不将旧清单重新执行。ETBST 当时 Ready、TLS 和未登录健康请求 401 已验证；认证业务、短信投递、自然调度周期不能算已验收。

### 2.2 固定候选值：使用前只读回查

| 类型 | 候选值 | 注意事项 |
|---|---|---|
| 阿里云账号 | `svision100` / `1442361567788059` | STS 回读 AccountId |
| RAM 用户 | `power-application-user` | 不等同于账号 UID 或流水线审批人 ID |
| CLI profile | `ruishi-prod-acr` | 本机凭据配置名称，不是另一个账号；不打印配置内容 |
| 云效组织 | `659a5cefd64a2eb2dceb72f3` | 不使用历史错误组织 `658d5b8ae7f9ce3ec8199dc0` |
| DevOps endpoint | `devops.cn-hangzhou.aliyuncs.com` | 显式指定；工作负载地域仍是北京 |
| ACR 实例 | `cri-73ffxebpi6ruw6sn` / `ruishi-prod` | 使用企业版 API |
| Java / .NET ACR namespace | `ruishi-java-prod` / `ruishi-dotnet-prod` | 在其中新建服务仓库，不修改 namespace 属性 |
| ACS 集群 | `cebc88343a44b4d759aa983a47b787835` / `ruishi-prod-acs` | 与下面两类 ID 分开存储 |
| Flow 集群登记 ID | `UIuvaR8vFrIjY4lj` | 大小写敏感，不能替换为 ACS ID |
| Codeup 连接 | `xdghn746erjk8hdo`；数字 API ID `580982` | 新仓库仍需证明可读取 |
| ACR 连接 | `lhjkwns3zhj879ic`；数字 API ID `943301` | 新仓库仍需证明可推送 |
| ACK 连接 | `fmayt57b9ttcjq61`；数字 API ID `943303` | 不是 Flow 集群登记 ID |
| 网络选址来源 | 基线中的 `deployment/dotnet-acs/egress-network-inventory.yaml` | 只读核实实际值，禁止重跑迁移脚本 |

现有 ETBST 仓库、Namespace、Deployment、流水线 ID 均作为保护对象，**不得成为新向导的默认写目标**。

### 2.3 必须在开发前关闭的门槛

| 门槛 | 问题 | 通过证据 | 未通过处理 |
|---|---|---|---|
| G01 | 旧 Flow kubectl 为 1.27.9，集群记录为 1.36.1 | 实际兼容版本、独立验证流水线的成功记录 | 停在 D01；不得猜版本、修改 ETBST 流水线或切换本地生产部署 |
| G02 | 连接可见不等于可访问新资源 | Codeup 读取、ACR 推送、Flow 集群权限分别验证 | 输出对应身份和缺失动作，不自动授权 |
| G03 | 新 Namespace 可能不在免密拉取/准入范围 | 新 Namespace 在现有配置下可用的证据 | 管理员另立变更；不扩大共享配置，不借用旧 Namespace |
| G04 | 首次清单如何进入 Flow | `KubectlApply.yamlPath`、源码实际 SHA、digest 变量替换均验证 | 不开展首次应用部署 |
| G05 | 共享容量与控制器影响 | 明确资源上限、容量余量，入口无冲突 | 无法证明则不启动应用或创建入口 |
| G06 | 新 Worker 可能启动旧业务任务 | 明确队列/任务身份、配置开关、业务授权 | 保持业务未激活，不做真实写入测试 |

G01 必须验证 `KubectlApply` 和 `KubectlSetImage` 两条路径。官方发布步骤存在不等于指定 kubectl 版本可用；本计划不宣称目前已验证兼容版本。

## 3. 生产保护规则与权限边界

### 3.1 必须在代码中执行的规则

1. 每个写动作都有目标清单：账号、地域、组织、集群、Namespace、资源类型、名称、资源 ID/UID、允许动作、有效接入记录。
2. 输入校验失败、对象归属不明、同名冲突、权限不足、模板越界时，默认拒绝写入。
3. 首次遇到已存在的对象不得接管。断点恢复只接受此前本次创建记录中的相同 ID/UID；标签仅作辅助，不能单独证明归属。
4. 保护既有对象，不更新镜像、不重启、不缩扩容、不重新 apply、不删除、不触发其流水线或通过其审批。
5. 禁止 `--force`、`replace`、`prune`、通配清理、级联删除及未限定范围的批量写入。
6. 同一服务同一时刻只允许一条发布链；进程退出后按持久记录核对运行，不能仅根据旧锁文件超时判定云端已停止。
7. 预检与执行之间重查目标和配置摘要；目标、权限范围、源码 SHA、digest 或清单变化使原确认失效。
8. 日常镜像更新以已知资源版本/前置条件保护并发；内置 Flow 步骤若不能满足此要求，G01/G04 不能视为通过，不用“读后写”冒充原子保护。
9. 不自动改 RAM、共享 Role/RoleBinding、组件、ACL、网络、DNS、证书、Bucket 策略；历史授权不推广到新对象。
10. 原有应用及部署命令的兼容性在离线环境验证，不以执行生产命令作为测试。

### 3.2 不能忽视的间接影响

- 在生产 ACS 新增 Pod 会使用共享容量并可能产生计费。启动前明确上限与容量，不做压测；上限未填写就阻断。
- 新建 Ingress、LoadBalancer Service、IngressClass/AlbConfig 可能让控制器修改共享 ALB 或创建付费资源。默认禁止 LoadBalancer Service、IngressClass/AlbConfig；公开入口作为独立子步骤确认其控制器影响范围。若要求完全不改共享 ALB，本次只能完成内部服务验收，公开入口记为阻塞。
- 不给新 Namespace 添加未经验证会命中共享策略的标签；不改变现有 Namespace 标签。
- API 启动也可能执行数据库迁移或定时任务。仅确认 Worker 不足以证明无副作用；所有后端均确认启动行为，自动迁移默认禁用。
- `Recreate` 只能减少发布重叠，不能证明业务绝对不会重复执行；仍需要队列隔离、业务幂等或明确停旧/启新方案。本任务不接管旧消费者。
- OSS 首次前缀必须未被已有站点使用；禁止空前缀、根目录、`..`、越界路径。发现既有对象且无本项目发布记录时停止。
- 源码推送可能触发现有 Webhook。未确认仓库触发配置前不自动推送发布分支；不为方便修改原有 Webhook。

### 3.3 基线与凭据

只对相关保护对象记录元数据、镜像、副本、可用状态及模板摘要；不导出 Secret、明文配置或整个集群。观察到他人并发变更时报告差异，不自动“恢复基线”。

临时 kubeconfig 仅由程序保存在权限 `0600` 的临时文件，操作完成即清理；不回显、入库或写审计日志。秘密引用只记录对象名与键名；存在性优先使用 metadata-only 读取，不能先下载完整 Secret 再丢弃 data。没有合适权限时由管理员提供存在性确认，列为待准备项。

## 4. 向导输入、状态与菜单接口

### 4.1 输入顺序

| 顺序 | 输入 | 自动发现及校验 | 不能采用的默认值 |
|---|---|---|---|
| 1 | 项目标识、显示名 | 标识唯一，符合 Kubernetes/仓库命名限制 | ETBST 的项目 ID |
| 2 | 本地仓库、远端地址、发布分支 | git 工作树/远端、分支存在、Codeup 读取、完整 SHA | 固定所有项目为 release |
| 3 | 服务集合：Java/.NET API、Worker、前端 | 服务 ID 唯一，允许多目录或多仓库 | 一个项目必然只有 API |
| 4 | Dockerfile、context、平台 | 默认 linux/amd64；基础镜像可达；路径不越界 | 固定根目录、固定替换 2 次 |
| 5 | 端口、启动命令、探针 | 使用真实启动配置和健康接口 | 全部 8080；Worker 伪造 HTTP 探针 |
| 6 | CPU/内存、副本、发布策略 | 用户确认总上限；Worker/调度服务单副本 Recreate | 自动增大规格；未确认可并行就 RollingUpdate |
| 7 | Secret/ConfigMap/SA 引用 | 仅名称、键、挂载位置及已有准备状态 | 输入或复制生产密钥内容 |
| 8 | Namespace、仓库名 | 默认新的项目隔离 Namespace、服务仓库 | 复用旧项目资源绕过权限 |
| 9 | 入口与依赖 | 默认内网；公开域名/路径/TLS 引用；数据库/队列等启动行为 | 自动 DNS、TLS、ALB 或数据库修改 |
| 10 | 前端构建与 OSS | 固定 Node/包管理器要求、lockfile、命令、产物、Bucket、专属前缀 | 本地脏工作区直接构建；整桶镜像同步 |
| 11 | 验收方式 | HTTP 预期、Worker 心跳、业务确认项及副作用范围 | 将 401/Ready 作为业务验收通过 |

### 4.2 最小持久数据

复用现有 `ConfigStore` 的锁、revision、备份和原子写入。新增项目使用定点 mutate，禁止拿旧快照 replace 整个项目列表，避免覆盖其他窗口新增的项目。

接入记录独立于普通菜单配置，保存在明确 gitignore 的本机状态目录，至少包含：

- schema_version、onboarding_id、project_id、service_id、目标元组、阶段和更新时间。
- 已确认输入的摘要、清单 hash、需要的授权范围和审批记录；不保存授权令牌。
- 每步请求的脱敏参数摘要、RequestId、返回的资源 ID/UID、核验结果。
- source_commit、release_id、tag、digest、build/bootstrap/deploy pipeline 与 run ID。
- 上一已验收镜像或 OSS 版本、验收结果、阻塞原因、可恢复步骤。

状态顺序：`DRAFT → PREFLIGHT_OK → RESOURCES_READY → CONFIG_READY → PIPELINES_READY → BUILDING → IMAGE_VERIFIED → WAITING_CONFIRM → DEPLOYING → VERIFYING → COMPLETE`。任一步可进入 `BLOCKED` 或 `FAILED`，保留原阶段和证据；不通过修改状态字段跳过检查。前端使用独立发布记录，不虚构镜像状态。

写入前持久化 intent；写后存资源 ID 并回读。若创建超时但无 ID，按精确名称、目标和创建证据查找；归属仍不唯一则阻塞，不自行认领。不得自动采用最后一条运行或第一条等待审批任务。

### 4.3 命令与用户界面

保留既有 `flow-release.sh push/build/deploy/status/apply` 参数语义；新向导调用受保护的新项目路径。仅设置 `FLOW_CONFIRM=yes` 不足以绕过目标、运行及变更摘要检查。

新增向导能力为“录入/预检/预览/执行/恢复”；具体 CLI 参数在 D03 固定后写入使用说明，**本文不提供尚未实现的伪命令要求用户执行**。

后端菜单显示实际分支名，提供推送、构建、状态、确认上线、日志、已验收镜像回滚。前端提供构建发布 OSS、历史记录、版本恢复。注册未完成项目时显示阶段并禁用尚不可执行动作。用户可在首次构建前保存退出。

日志：普通、WARN、ERROR、Kubernetes Warning 事件分开，结构化等级优先；文本匹配说明可能不完整。按 Deployment UID → ReplicaSet → Pod 归属获取所有目标副本并标注来源，支持上一容器实例。默认最近 30 分钟、每容器 200 行、总计 1 MiB，超过提示截断；不装采集器、不修改应用日志配置、不后台持续订阅。

## 5. API 手册与调用纪律

### 5.1 三层验证与统一结果

接口状态区分：A=官方/CLI 有此接口；B=历史有成功记录；C=本次目标已验证。A/B 都不能代替 C。所有写接口在 D01/D04 建立请求与脱敏响应样本后才能进入执行器。

统一检查 transport 成功、业务 success/Code、预期资源 ID、回读结果。只读操作遇限流/瞬时错误最多 3 次有限退避；权限、参数、身份错误不重试。写操作默认不自动重发，先回读消歧。列表必须处理分页。生产权限策略按实际资源 ARN/RBAC 动作核验，不用通配管理员权限代替。

继续用已有 CLI 签名认证；DevOps `2021-06-25`，ACR `2018-12-01`，CS `2015-12-15`。ACR CLI 已有内置命令为 `get-instance`、`create-repository` 等 kebab-case，与文档 API 名区分。不得混用 DevOps `/oapi/v1` Token 接口。

### 5.2 云效、ACR、CS 必需接口

下表关键参数是集成检查点，不是保证可直接执行的完整命令；body/可选项必须按安装的 CLI 帮助和官方 schema 固定，并在 C 级证据中留样。

| 接口组 | 操作 | 关键参数/返回检查 | 范围 |
|---|---|---|---|
| 身份 | STS `GetCallerIdentity` | `--profile`、`--region`；AccountId、调用者 ID | 只读，不打印令牌 |
| 组织 | `ListJoinedOrganizations` | 正确 organizationId 在返回中 | 只读 |
| 仓库/分支 | `GetRepository`、`GetBranchInfo`、`ListRepositories`、`ListRepositoryBranches` | identity/organizationId；repositoryId/branchName；完整 SHA | 只读 |
| 触发配置 | `ListRepositoryWebhook`、`GetPipeline` | 检查发布分支相关触发；权限不足记录未核实 | 只读，不自动禁用他人触发 |
| 连接 | `ListServiceConnections`、`ListResourceMembers` | `sericeConnectionType` 是实际参数拼写；Codeup 用历史成功的小写 `codeup` | 只读 |
| 流水线定义 | `CreatePipeline`、`GetPipeline`、`UpdatePipeline`、`ListPipelines` | org、name/content 或已验证 body；区分返回 `pipelineId`/历史 `pipelinId` | Create/Update 仅本次新资源 |
| 构建/发布启动 | `StartPipelineRun` | org、pipelineId、params；明确 envs/分支；持久化 run ID | 仅已核实目标和获授权动作 |
| 运行与诊断 | `GetPipelineRun`、`ListPipelineRuns`、`LogPipelineJobRun` | pipelineRunId；日志 run/job 参数按帮助验证；有界输出 | 只读 |
| 审批/停止 | `PassPipelineValidate`、`RefusePipelineValidate`、`StopPipelineRun` | 唯一 pipeline/run/审批节点；禁止猜 job | 仅本项目已确认运行 |
| ACR 基础 | `GetInstance`、`GetNamespace`、`ListRepository`、`GetRepository` | instance-id、namespace/repo；RepoId 与预期归属 | 只读 |
| ACR 建仓 | `CreateRepository` | instance-id、repo-namespace-name、repo-name、repo-type=PRIVATE、summary；tag-immutability=true | 仅新仓库；检查 IsSuccess、Code、RepoId |
| ACR 镜像 | `ListRepoTag`、`GetRepoTag` | instance-id、repo-id、tag；NORMAL、完整 sha256；分页 | 只读 |
| ACR 端点 | `GetInstanceEndpoint`、`ListInstanceEndpoint`、`GetInstanceVpcEndpoint` | endpoint-type/module；公网域名、VPC 路径、ACL | 只读 |
| CS 集群 | `DescribeClusterDetail` | ClusterId；集群、版本和网络身份 | 只读 |
| CS 凭据 | `DescribeClusterUserKubeconfig` | ClusterId、PrivateIpAddress=true、TemporaryDurationMinutes=15 | 短期敏感返回，不输出；私网不可达则阻塞 |
| CS 组件 | `DescribeClusterAddonsVersion`、`DescribeClusterAddonInstance`、`DescribeClusterAddonMetadata` | 分别注意 ClusterId、ClusterID/AddonName、cluster_id/component_id 大小写 | 只读，不把不同接口参数混用 |

`StartPipelineRun` 的分支参数不等于固定 commit：请求前记录远端 SHA，运行启动后比较实际完整 SHA；不一致即停止后续发布。历史源码字段出现 `sources[].data.commint`，只在已验证样本对应格式下解析，不静默回退到短 SHA。

### 5.3 Kubernetes 与外围接口

| 对象/服务 | 必需能力 | 约束 |
|---|---|---|
| Kubernetes discovery、SelfSubjectAccessReview | 版本、资源支持、create/get/list/watch/patch 与 pods/log 权限 | 本地身份和 Flow 身份分别检查 |
| Namespace、ServiceAccount | 建立专属命名空间及 SA | 只创建本次清单资源，不改共享 RBAC |
| Deployment | 首次创建、观察代次、镜像 patch | 只操作本次归属对象；后续仅镜像 |
| Service、Ingress | API 连接及可选入口 | ClusterIP 默认；Ingress 单独影响审核 |
| ReplicaSet、Pod、EndpointSlice、Event、logs | Ready、真实镜像、端点、调度与错误证据 | 时间和对象范围有界 |
| VPC `DescribeVSwitches/DescribeNatGateways/DescribeEipAddresses/DescribeSnatTableEntries/DescribeRouteTableList/DescribeRouteEntryList` | 固定选址、出口和依赖路由核对 | 不创建/调整网络 |
| ALB `GetLoadBalancerAttribute/ListListeners/ListRules` | 入口及域名路径冲突 | 不写现有监听与规则 |
| DNS `DescribeDomainRecords/DescribeSubDomainRecords/DescribeDomainRecordInfo` | 有权限时核验；结合公开 DNS 查询 | 无权限不代表域名不存在；不自动 Add/Update |
| OSS `GetBucketInfo/GetBucketLocation/GetBucketWebsite/GetBucketVersioning` | Bucket 和站点条件 | 不启用版本控制、不修改站点/ACL |
| OSS `ListObjectsV2/HeadObject/GetObject/PutObject/CopyObject` | 前缀冲突、上传、备份和恢复 | 写仅项目和备份前缀；无全桶删除 |
| CDN `RefreshObjectCaches/DescribeRefreshTasks` | 已配置 CDN 时更新指定 URL 缓存并等待结果 | 不新建 CDN、不全域刷新 |

OSS 复用现有身份和受支持工具；若选择集成 `aliyun ossutil`，先验证所需操作、版本及 profile 传递，不另建含明文凭据的配置。ETag 不普遍等于文件 MD5，不能据此单独认定内容一致；保存本地产物 SHA-256、长度及上传结果，必要时回读关键对象核验。

### 5.4 只供管理员准备、不自动调用

`AddRepositoryMember`、`CreateServiceConnection`、`CreateServiceAuth`、`CreateResourceMember`、RAM 授权写入、`CreateInstanceEndpointAclPolicy`、`ModifyClusterAddon`、共享 RBAC/策略修改、DNS/ALB/VPC 写入、Bucket 策略变更。

发现需要这些动作时输出：缺失条件、准确对象、需要的权限/字段、预期影响、谁处理、完成后的只读核验方式。权限扩大不属于本次普通接入授权。

组件修改接口为 `ModifyClusterAddon`，不是 `UpdateClusterAddon`。连接字符串 ID 与 `CreateResourceMember` 等使用的数字资源 ID 不混用。ACR Flow 构建路线不额外依赖 ACR 代码源绑定，不调用建代码源/云构建规则作为临时替代方案。

### 5.5 官方来源

- [DevOps API 清单](https://help.aliyun.com/zh/yunxiao/developer-reference/api-devops-2021-06-25-overview)、[StartPipelineRun](https://help.aliyun.com/zh/yunxiao/developer-reference/api-devops-2021-06-25-startpipelinerun)。
- [Flow 步骤清单](https://help.aliyun.com/zh/yunxiao/user-guide/step-steps-list)、[KubectlApply 参数](https://atomgit.com/flow-steps/system_steps/blob/master/docs/%E6%AD%A5%E9%AA%A4%20steps%20%E6%B8%85%E5%8D%95/deploy/Kubectl%20%E5%8F%91%E5%B8%83%20KubectlApply.md)。
- [Kubernetes 版本偏差](https://kubernetes.io/releases/version-skew-policy/)、[Flow 集群管理](https://help.aliyun.com/zh/yunxiao/user-guide/kubernetes-cluster-management)。
- [ACR CreateRepository](https://help.aliyun.com/zh/acr/developer-reference/api-cr-2018-12-01-createrepository)、[ACR GetInstanceEndpoint](https://help.aliyun.com/zh/acr/developer-reference/api-cr-2018-12-01-getinstanceendpoint)。
- [CS ModifyClusterAddon](https://help.aliyun.com/zh/ack/ack-managed-and-ack-dedicated/developer-reference/api-cs-2015-12-15-modifyclusteraddon)、[ACS 免密拉取](https://help.aliyun.com/zh/cs/exempting-the-miracular-acr-image)。
- [OSS 接口分类](https://help.aliyun.com/zh/oss/developer-reference/list-of-operations-by-function)、[ALB API](https://help.aliyun.com/zh/slb/application-load-balancer/developer-reference/api-alb-2020-06-16-overview)、[DNS API](https://help.aliyun.com/zh/dns/api-alidns-2015-01-09-overview)、[CDN API](https://help.aliyun.com/zh/cdn/developer-reference/api-cdn-2018-05-10-overview)。

官方页面可能更新；实施记录必须标注实际查阅日期、CLI 版本和验证结果。尚未发现可靠公开接口查询 Flow 全部可选 kubectl 版本及集群登记详情；允许一次必要的官方控制台核验，不使用未公开接口或编造 API。

## 6. 开发实施步骤 D00—D08

### D00 — 确认工作基线与本次授权

输入：本文件、当前 Git 状态、实施指令。执行：检查分支/未提交改动/CI，列保护对象和获授权的隔离验证目标；选择工作基线。

基线要求：release/master 若缺少第 2 节实现，先核对差异并列出需要复用的依赖；不将整个历史部署分支自动合入。只能在明确批准的功能范围内引入必要依赖。保护用户无关改动，不修改本机生产项目配置。

输出：基线 SHA、任务分支、依赖差异、保护对象清单、隔离对象及资源上限。完成判据：没有来源不明的代码依赖或授权目标。缺少任一项则保持 D00。

### D01 — 先完成 G01—G06 能力核验

执行顺序：① CLI/文档与模板静态核对；② 必要只读查询；③ 单独确认隔离 Namespace、测试镜像仓库、流水线及资源上限；④ 在现有权限内创建隔离对象；⑤ 验证版本、读取源码、构建、digest、apply、镜像更新、审批、并发保护；⑥ 有界验收。

隔离应用无生产凭据、无公开入口、无业务依赖、无调度任务。新增 Namespace 在现有权限或组件范围下不可用就停止，不借用生产 Namespace。未授权的云端写操作不执行。

输出：各 G 项证据、成功 API 样本、模板版本、测试对象 ID。通过后冻结路线。实验资源保留清单；清理另列准确对象，不自动级联删除。

### D02 — 实现只读预检与目标保护

执行：开发输入校验、API 返回归一化、分页、目标白名单、归属判断、权限分层、配置与资源基线摘要。对既有生产 ID 的写操作直接拒绝。

输出：结构化预检报告，每项为 PASS/BLOCKED/NOT_APPLICABLE，含证据时间和原因。完成判据：T01—T05、T09、T15 的离线测试通过。只读预检本身不得隐式运行镜像构建、创建凭据持久配置或更新资源。

### D03 — 实现向导、草稿与恢复

执行：按 4.1 提问；实现 4.2 状态；操作前预览和范围确认；现有 ConfigStore 的定点修改和 revision 冲突处理；固定用户命令及菜单说明。

输出：可离线演练的向导、新项目配置和执行计划。完成判据：保存退出恢复、并行配置编辑、同名项目冲突通过；原项目配置内容保持相同。未实现功能菜单不可伪装为可用。

### D04 — 通用化 Flow 与镜像证据

执行：保留现有命令兼容；修正硬编码 release、`.git` 必须为目录、两次域名替换、首屏镜像列表、短 SHA/时间猜测、state 覆盖及 `pipelinId` 缺键问题；新路径禁止强推。

采用三类新项目模板：构建、首次初始化发布、日常镜像发布。新模板不得带入 ETBST 仓库/Namespace/流水线 ID。初始化与日常运行分开，不通过再次 apply 全量清单做日常镜像发布。

构建以唯一 release_id 生成不可复用 tag；Flow 运行实际 full SHA 必须匹配请求。解析镜像制品、ACR tag 与 digest 的强关联；若平台无法证明关联则停止。首次发布源码实际 SHA 和 manifest hash 也必须匹配，不能从分支最新文件替代。

输出：模板、API 样本、编排实现。完成判据：推送无触发、非 release、重复 SHA 不同构建、错 digest/错审批均有离线和隔离证据。所有生产 ETBST 流水线保持不变。

### D05 — 实现新资源初始化及验收

执行：实现 Namespace/SA 准备、新仓库创建、清单生成、服务器干跑、首次发布及就绪检查；模板只允许批准的资源类型，不接受导入清单夹带 CRD、Webhook、ClusterRole、Job、PVC 或共享资源。

高级导入清单仍需相同检查；第一版不自动执行数据库迁移 Job，不自动创建 PVC/外部基础设施。需要这些资源则输出独立准备事项。

输出：首次初始化流程、目标限定的检查器。完成判据：N03—N11 可在隔离应用跑通，未修改保护对象；任一共享前提不满足能清晰阻塞。

### D06 — 实现 OSS 与通用日志

执行：复用已有前端构建方式，但以独立干净工作目录构建固定提交；实现前缀隔离、产物清单、备份、资源先上传/入口后更新、验收与恢复。日志按资源归属查询并限制输出。

第一版标准站点要求资源有内容 hash；若存在 Service Worker、固定名覆盖或多入口一致性要求，预检列出专项方案要求，不宣称整站原子发布。

输出：OSS 菜单、发布记录、日志菜单。完成判据：T12—T14 通过，上传失败不会提前切入口，恢复不删除其他版本资源。

### D07 — 验证与新项目首次使用

执行：运行直接相关离线测试；对已授权隔离目标完成 Java、.NET/Worker、OSS 三类代表验证。真实业务项目另走 N00—N12，首次上线确认不能沿用隔离验证许可。

输出：T01—T18 证据、相关基线前后差异、未完成业务项。发现旧项目异常时立即停止本任务后续写操作并报告；只诊断，不自行重启或回滚旧项目。

### D08 — 文档与 Git 交付

执行：更新命令说明、API/权限矩阵、模板版本和接入示例；只提交任务相关文件。按任务分支 → release → master 保留历史交付；推送前检查目标差异与实际 CI，不携带无关历史提交、不强推、不修改分支保护绕过拒绝。

输出：提交 SHA、远端核验、实现基线及下一位操作者入口。完成后停止，不自动推广至现有项目。

## 7. 每个新项目的接入步骤 N00—N12

| 步骤 | 输入与准确动作 | 允许写入 | 完成证据 / 失败处理 |
|---|---|---|---|
| N00 录入 | 按 4.1 建草稿；区分项目和服务 | 本机草稿 | 必填项完整；可退出恢复 |
| N01 只读预检 | 身份、代码、连接、容量、网络、Secret 引用准备状态、触发配置 | 无云端资源写入 | 全项 PASS 或明确待准备项；未通过不建流水线 |
| N02 预览确认 | 展示资源名、读写范围、资源上限、入口/业务副作用、下一步 | 本机确认记录 | 确认绑定目标和计划 hash；发生变化重新确认 |
| N03 建基础 | 重查同名；创建新仓库、新 Namespace/SA；每次回读 ID/UID | 仅本次对象 | 冲突不接管；超时先查询，不重建 |
| N04 配置就绪 | 管理员在新 Namespace 准备必要配置；程序仅校验引用 | 本工具不写 Secret/证书 | 缺少时 BLOCKED；不先构建或启应用等待“稍后补” |
| N05 固定清单 | 生成清单；检查允许类型、网络注解、规格、探针、策略；在已存在 Namespace 内 server dry-run | 本地生成文件 | 干跑通过、manifest hash；拒绝集群级对象和其他 Namespace |
| N06 发布源码 | 清单进入项目仓库业务分支，按约定交付至实际发布分支；只提交生成文件及明确改动 | 经确认的项目 Git 范围 | 记录远端完整 SHA；未确认 Webhook 行为不推送 |
| N07 流水线/菜单 | 新建三类所需流水线并回读 triggerEvents；注册本地新项目菜单 | 本次流水线和新菜单条目 | ID 已保存且无 push 触发；既有配置未被重写 |
| N08 构建 | 显式 StartPipelineRun；保存 run；比较实际 SHA；查询精确 tag/digest | 新仓库的新 tag 与本项目运行 | IMAGE_VERIFIED；关联不唯一不得启部署 |
| N09 上线确认 | 展示源码/清单/digest、资源名、规格、入口影响、业务副作用；核实真实等待节点 | 本机审批意图；确认后仅该节点 | 新信息与 N02 不符重审；不选择“第一个 WAIT” |
| N10 首次发布 | Flow 读取已验证清单并固定 digest；仅创建本次服务对象 | 本次工作负载；入口需单独范围许可 | 控制器已观察当前代次；无未授权对象写入 |
| N11 验收 | Ready、实际 imageID/digest、事件、端点、允许的 HTTP/业务核验；比较保护基线 | 只读及已明确业务验证动作 | 记录基础/入口/业务三类结果，未验证不得写全通过 |
| N12 收尾 | 保存发布记录，开放日常镜像更新菜单；关闭重复初始化入口 | 本机记录、本次初始化入口状态 | COMPLETE；待办单独交接，不自动接入下一个项目 |

前端服务不执行 ACR/ACS 专属步骤，改用第 8 节流程；同一项目各服务独立记录，不把一个服务成功扩展为整个项目成功。

## 8. 发布、验收与失败恢复细则

### 8.1 日常后端发布

1. 用户准备好提交；选择推送配置分支或直接构建远端已有提交。push 不 commit、不合并、不强推。
2. 构建前锁定期望 full SHA、唯一 release_id；构建后核对实际 SHA 与精确镜像 digest。
3. 生成仅镜像更新计划，记录旧 digest、资源 UID、模板摘要、当前版本和运行 ID。
4. 明确确认并核对审批节点后才上线。长时间等待审批后重新预检；凭据刷新，旧检查不能无限有效。
5. 默认构建轮询 15 秒、上限 60 分钟；超时记为结果待核实，不自动再构建或认定远端已终止。
6. 默认 rollout 上限 10 分钟；应用确有更长启动要求时在计划中显式配置。Ready 后入口默认给 120 秒同步窗口，再每 10 秒检查一次、最多 5 分钟，要求连续 3 次符合预期。
7. 第一次 503 不立即回滚。401 只能按预期说明可达性，不能当业务成功。

Pod imageID 与 ACR digest 的比较需考虑 manifest/index 与平台镜像的关系；默认单平台 linux/amd64，若构建产出多架构索引，先建立 index→平台 manifest 证据，不能凭字符串差异误判或跳过。

### 8.2 回滚与停止

- 后续发布失败先停止后续动作、保存事件/日志和当前版本；用户选择已验收旧 digest 后，仅变更镜像字段，保留网络/配置/资源规格。
- 禁止直接 `rollout undo` 把历史网络变更一并回退。
- 首次没有旧版本时不能伪造“回滚成功”；将新项目停到 0 副本也属于写操作，仅在预先确认的应急范围或追加明确授权内执行。
- 不因新项目失败操作旧项目，也不以删除 Namespace 作为默认清理。
- 如果写入后其他人已改对象，停止自动恢复，报告最新状态；不得覆盖其变更。

### 8.3 OSS 发布顺序

1. 确认代码 SHA、干净独立工作目录、lockfile 与构建命令；不默认升级依赖。
2. 构建后检查产物目录、base path、引用关系、敏感文件误入产物及发布前缀边界。
3. 为本次发布生成对象清单，记录每个对象的本地 SHA-256、长度、缓存与 Content-Type；建立前缀内的版本备份位置。
4. 首次发布前缀若非空且无本项目历史记录则停止。日常发布先备份将覆盖的入口和必要对象；Bucket 已有版本功能则同时记录 versionId，不自动开启。
5. 先上传带 hash 资源并验证，再更新入口 HTML；入口使用符合现有站点约定的低缓存策略。
6. 仅对明确配置的 CDN URL 刷新并查询结果；访问检查匹配本次入口及关键资源版本。
7. 失败恢复以旧入口和被覆盖对象为限，不删除新旧 hash 资源、不整桶 sync --delete。
8. 已有站点策略不支持新项目路径、SPA 路由或安全访问时记为准备项，不修改 Bucket 网站配置解决。

### 8.4 恢复判定表

| 现象 | 第一步 | 可继续条件 | 禁止动作 |
|---|---|---|---|
| 请求超时/进程退出 | 回读精确资源或 run | 归属、状态和计划一致 | 原写请求无条件重发 |
| 权限不足 | 记录失败身份、对象、动作 | 管理员独立处理后只读核验 | 自动 grant / 切主账号 |
| 新 Namespace 不可拉镜像 | 核查事件与现有拉取范围 | 在不变更共享配置的前提下可用，或独立变更已完成 | 借用 ETBST SA/Namespace |
| 构建关联不唯一 | 列本次候选与证据缺口 | 唯一 run/tag/SHA/digest | 取最新镜像或短 SHA 第一条 |
| 审批/发布已启动但本地未知 | 查询记录中的准确 run | 状态明确后衔接 | 再启动第二条发布 |
| 源码/模板/对象被并发修改 | 重读并比较确认摘要 | 新计划重新确认 | 继续使用旧确认 |
| 发现既有生产异常 | 停止本任务后续写入、保存有界证据 | 人工判断后明确下一步 | 自动重启/回滚旧项目 |

## 9. 必要测试及验收清单

离线命令替身不得访问真实生产凭据；所有云端写操作都需要独立隔离目标。文档任务不运行下表测试；实施时逐项附证据。

| 编号 | 场景 | 通过标准 |
|---|---|---|
| T01 | 账号/组织/集群/Namespace 错误 | 第一次写入前拒绝 |
| T02 | ETBST 等既有 ID 被作为目标传入 | apply、update、run、approve、stop 等写路径均拒绝 |
| T03 | 同名资源、标签伪装、UID 更换 | 不接管，恢复要求真实创建记录匹配 |
| T04 | API 分页、Code/IsSuccess 失败、字段差异 | 结果准确，业务失败不误判成功 |
| T05 | 拒绝授权、组件缺范围、共享网络变更需求 | 输出准确阻塞项，无自动授权/扩范围 |
| T06 | release 与非 release、worktree、分支移动 | 正确解析分支；实际 SHA 变化阻止发布 |
| T07 | 同 SHA 两次构建、跨页 tag、多候选 | 唯一关联本次 run/tag/digest |
| T08 | 错 digest、错审批 job、重复上线/并发 | 不发布，不通过无关节点 |
| T09 | 超时已创建、进程中断、旧锁、恢复 | 先回读，无重复资源/运行 |
| T10 | Java API、.NET API、Worker | 正确构建/探针/单副本行为；Worker 无多余入口 |
| T11 | 缺配置、拉取失败、探针失败、503、401 | 准确分层报告，不把基础可达视为业务通过 |
| T12 | OSS 前缀空/越界/冲突、上传中断 | 不覆盖其他站点；入口未提前切换 |
| T13 | OSS 恢复、ETag 非 MD5、缓存更新 | 原入口可恢复，版本证据完整，无整桶删除 |
| T14 | 多 Pod、上一实例、日志量超限 | 归属准确、标注来源、有界输出，不修改应用 |
| T15 | 导入清单含共享/集群级资源、危险 Service/Job | server dry-run 前即可拒绝越界资源 |
| T16 | ConfigStore 并行编辑、旧菜单兼容 | 新项目定点增加，旧内容与无关更新不丢失 |
| T17 | 新项目发布失败及镜像恢复 | 只变指定镜像；不回退网络、不碰旧项目 |
| T18 | 基线出现他人修改、完成收尾 | 报告差异不盲目恢复；交付后停止 |

功能完成要求：离线保护测试通过，隔离三类代表验证有证据，新项目首次使用按实际授权验收；已存在生产对象没有被本任务执行部署、重启、缩扩容、删除或回滚，共享配置未被本任务修改。未完成自然业务周期观察时保持该项“未验证”，不安排未授权后台任务。

## 10. 交接记录与执行人检查卡

每次操作记录只保留：时间、执行人、步骤 ID、目标、批准范围、输入摘要、请求/资源/运行 ID、结果、脱敏证据位置、下一步。审批记录必须能对应准确计划，不以一句泛化“已授权”覆盖未来所有项目。

### 10.1 开始前

- [ ] 本轮是文档、开发、隔离验证还是新项目上线，范围已明确。
- [ ] 已读当前计划、核对实现基线和仓库无关改动。
- [ ] G01—G06 的状态真实，历史成功没有冒充本次验证。
- [ ] 保护对象、新资源及共享控制器影响范围明确。
- [ ] 凭据不输出；只读查询有界；无自动共享配置修改。

### 10.2 每个写动作前

- [ ] 目标属于本次新项目，ID/UID 和确认摘要一致。
- [ ] 输入、权限、容量、业务副作用前提仍成立。
- [ ] 状态和 intent 已保存，已知道超时如何回读。
- [ ] 无生产旧项目 ID、通配删除、强制覆盖或未确认入口变更。

### 10.3 完成后

- [ ] 记录真实验收结果和仍未验证的业务项。
- [ ] 比较相关保护基线；差异有归因，不自动恢复他人修改。
- [ ] 清理本机临时凭据；云端资源清理未擅自执行。
- [ ] 任务相关 Git 提交、分支交付、远端核验完成。
- [ ] 不自动进入下一项目、历史迁移或生产优化任务。

**下一位执行人的第一步：读取本文件第 2、3 节，完成 D00；当前没有任何 G 门槛被本文标记为“本次已通过”。**

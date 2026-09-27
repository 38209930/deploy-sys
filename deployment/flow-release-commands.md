# 云效 Flow 发布命令（API/Worker → ACR/ACS）

**现行方案（2026-09-27）：** ETBST 及后续 18 个服务的构建流水线仍手动触发；构建后核对唯一 tag/digest 并进入独立 Flow 人工确认流水线。确认通过后，使用本机 `kubectl 1.36.1` 和短时 ACS 访问配置只更新镜像。原 ETBST Flow `KubectlSetImage` 使用 `kubectl 1.27.9`，已从当前确认流水线移除。下方早期试点记录保留为历史；服务映射、流水线 ID 和现行菜单用法见[多项目发布清单](flow/multi-project-release.md)。

状态：2026-09-27 更新。生产 api/worker 服务已迁入北京 ACS（镜像在 ACR），本地不再打包部署到单机 ECS；本篇记录 deploySys 的云效 Flow 远程发布命令与试点结果。试点项目 **etbst-api**。.NET 项目的 ACS 运维文档仍在 [dotnet-acs](dotnet-acs/) 目录。

## 架构与命令

```
本地 deploySys ──▶ 构建流水线：Codeup 指定分支 → Docker build → push ACR
               └─▶ ACR API 回读唯一 tag 的 digest
                    └─▶ 确认流水线：输入校验 → 人工确认
                         └─▶ 本机 kubectl 1.36.1：固定 digest 更新 ACS Deployment 镜像
```

- **不做 push 自动构建**：流水线手动触发。`build` 构建完成后核对镜像并启动部署流水线，停在人工确认；`deploy` 才通过卡点。
- 本地命令：`scripts/flow-release.sh`，子命令 `push | build | deploy | status | apply`。
- 认证：阿里云 CLI，显式 `--profile ruishi-prod-acr --region cn-beijing`（默认 Profile 属其他账号，禁止省略）；每次操作前 STS 核对账号 `1442361567788059`。凭据失效执行 `aliyun configure --profile ruishi-prod-acr`。
- 云效组织：`svision100的代码库`，OrganizationId `659a5cefd64a2eb2dceb72f3`（脚本默认值；与 etbst Codeup 仓库相同组织）。

## 现网核实结论（2026-09-27）

| 项 | 结论 |
|---|---|
| 云效组织 | `svision100的代码库`，org `659a5cefd64a2eb2dceb72f3`；`power-application-user` 已手动同步为普通成员，`ListJoinedOrganizations` 和 `ListPipelines` API 成功；正式流水线 `5300352` 已创建 |
| devops API | 当前 svision100 组织中 `power-application-user` 已创建并回读 etbst-api 正式流水线 `5300352`；首次真实构建运行 `1` 因连接 ACR 超时失败，未推送镜像或进入部署 |
| 服务连接 | ACR `lhjkwns3zhj879ic`（API ID `943301`）、Codeup `xdghn746erjk8hdo`（API ID `580982`）、ACK `fmayt57b9ttcjq61`（API ID `943303`）均可由 `power-application-user` 通过 API 查询；实际拉取、推送和集群访问仍待流水线验证 |
| etbst 仓库 | `/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api`，origin `codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api.git`，`release` 分支在用，根目录 Dockerfile（多阶段 Maven 构建，适配容器部署） |
| Codeup API | svision100 主账号确认目标仓库 ID `6424213`，并经 `AddRepositoryMember` 将 `power-application-user` 加为单仓库浏览者（20）；管理员成员列表与该 RAM 用户的 `ListRepositories` 均回读成功 |
| ACR 直连 API | 同一 Profile 于 2026-09-27 复核 `GetInstance` 成功；此前 Unauthorized 不代表当前持续无权 |
| ACS/CS API | 同一 Profile 于 2026-09-27 复核 `DescribeClusterUserKubeconfig` 成功（未读取或保存内容）；此前 `ErrorClusterNotFound` 不代表当前持续无权 |

云效组织成员、目标代码仓库浏览权限及三个服务连接可见性已解决。已在 Flow 注册目标集群 `ruishi-prod-acs`，集群 ID `UIuvaR8vFrIjY4lj`，`power-application-user` 为使用者。服务连接 ID、真实 ACS 集群 ID 与 Flow 注册集群 ID 是不同对象。2026-09-27 以该 ID 执行 `apply` 成功创建流水线 `5300352`，并通过 `GetPipeline` 回读 YAML；此前 OCR 将大写 `I`/小写 `l` 混淆导致的“不存在”报错已解决。

2026-09-27 构建运行 `1` 登录 ACR 公网端点超时。经用户授权，对 ACR 实例 `cri-73ffxebpi6ruw6sn` 的公网 Registry 白名单追加云效北京公共构建集群所需的五个 `/32`：`112.126.70.240/32`、`123.56.255.38/32`、`47.94.150.88/32`、`47.93.89.246/32`、`47.94.150.17/32`；原有三条保留，回读共八条。地址来源：[云效构建集群官方文档](https://help.aliyun.com/zh/yunxiao/user-guide/build-a-cluster)。运行 `2` 登录成功，但源 Dockerfile 的基础镜像是 VPC 域名，公共构建机无法解析。流水线临时生成 `Dockerfile.flow`，仅将两个基础镜像地址换为同一实例的公网域名，不修改源码仓库 Dockerfile。运行 `3` 构建及推送成功，但旧版后续 digest 命令步骤失败；因此改为独立构建和部署两条流水线。

构建流水线 `5300352` 运行 `4` 整体 **SUCCESS**；Codeup `release` Commit `1e09bf8147b5eba0d04ef4fe0333003e4ad887b2`，ACR tag `2026-09-27-18-40-20-1e09bf81`，ACR API `get-repo-tag` 回读 Digest `325cefc75daa088d274c073873884a2a1e4fd15f81b9bc64f135e5a92e30526d`，状态 `NORMAL`。部署流水线 `5300396` 运行 `2` 先通过镜像地址/Commit 输入校验并停在人工确认；运行 `1` 曾用于验证卡点，随后主动停止，未执行部署。

**上线验收（2026-09-27）：** 用户明确授权生产镜像更新后，通过部署流水线 `5300396` 运行 `2` 的人工卡点；输入校验、人工确认和 ACS 部署三个阶段均为 **SUCCESS**。上线前通过 CS API 获取 15 分钟临时 kubeconfig，仅作只读核验，临时文件放仓库外、权限 `0600`、用后删除。目标为北京集群 `cebc88343a44b4d759aa983a47b787835`、Namespace/Deployment/容器 `etbst-api`。原镜像回滚地址为 `ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api@sha256:efc2382dce053cc3e15d915f8f36ae726546563d65337b0efae337110008692e`；原状态为 1/1 Ready、Pod 重启数 0。部署步骤只执行该 Deployment 容器的 `kubectl set image`，未改 Secret、Service 或 Ingress。上线后 Deployment 第 5 代已被控制器观察，更新副本/Ready/可用均为 1/1；`kubectl rollout status deployment/etbst-api` 成功，新 Pod `etbst-api-66955b596-8zw7s` Running/Ready、重启数 0，旧 Pod 已退出，EndpointSlice 唯一 Ready endpoint 指向新 Pod。Deployment 镜像回读为 `ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api@sha256:325cefc75daa088d274c073873884a2a1e4fd15f81b9bc64f135e5a92e30526d`。Ingress Host 为 `et-bst-api.svision100.com`；DNS 指向北京 ALB，HTTPS TLS 校验通过，未登录访问 `/actuator/health` 返回 `401`，与上线前一致。认证业务、短信真实投递、调度周期及应用依赖日志未验收，不能以 Ready 或 401 代替这些业务验证。

本次构建和部署由 CLI/API 分别启动以排查问题；`scripts/flow-release.sh build` 新增的“构建成功后自动关联 ACR tag 并启动部署流水线”编排尚未作为一个命令端到端重跑。脚本已通过语法检查，构建、ACR 回读、运行变量传递、人工卡点及 `deploy` 子命令分别在本次运行中验证。

注意：`ListServiceConnections` 查询 Codeup 时必须传 `--sericeConnectionType codeup`（小写）；CLI 帮助列出的 `Codeup`（大写）会返回空列表。此前由此造成的“连接未生效”判断已纠正。

2026-09-27 通过 svision100 主账号的 CLI OAuth 配置 `svision100code` 执行单仓库授权：`power-application-user`（`accountId=203420990220401362`）在组织中状态为 `normal`、角色为“成员”，在 `ddmp/et-bst-api` 仓库中为活跃浏览者（20）。此后又对本轮多项目目标的 10 个 Codeup 仓库逐库添加只读浏览权限（20），均回读为 active，详见[多项目发布清单](flow/multi-project-release.md)。

流水线模板中的 `ACREEDockerBuild` 已按[云效官方步骤清单](https://help.aliyun.com/zh/yunxiao/user-guide/step-steps-list)核对。试点阶段用过的 `KubectlSetImage` 已从现行流水线移除。本地脚本在成功运行的源码 Commit、ACR 镜像创建时间和 tag 后缀之间建立唯一关联，再以 `get-repo-tag` 回读 digest；匹配不唯一时拒绝启动确认流水线。

目标 ACR 仓库 `ruishi-java-prod/etbst-api`，仓库 ID `crr-gkqkb2np05u435bf`；`get-repo-tag` 已验证本次新构建 tag 的 Digest。部署流水线变量 `IMAGE_DIGEST_REF` 使用 VPC 域名加 `@sha256:`；`SOURCE_COMMIT` 记录完整源码提交。ETBST 首次 ACS 执行和 Pod 验收已完成，见上文验收记录。

## 控制台一次性授权清单（已完成，运行能力待验证）

已通过阿里云 devops API 和云效控制台完成连接配置，并将各 ID 回填 `deployment/flow/pipeline-etbst-api.yaml` 后执行 `apply`：

1. **Codeup 服务连接**：连接 `xdghn746erjk8hdo`（API ID `580982`）已对 `power-application-user` 可见，并已回填模板；仍需通过流水线核验它能否拉取目标仓库。
2. **容器镜像服务（企业版）服务连接**：新连接 `lhjkwns3zhj879ic`（API ID `943301`）已对 `power-application-user` 可见并回填 YAML；仍需通过流水线核验其对北京实例 `cri-73ffxebpi6ruw6sn` 的实际推送能力。
3. **容器服务 Kubernetes（ACK）服务连接**：已创建 `fmayt57b9ttcjq61`（API ID `943303`），`power-application-user` 经 API 可见。创建时 API 的 `scope=PERSON` 返回 `Invalidscope`，`scope=CUSTOM` 成功。
4. **Flow Kubernetes 集群注册**：已在云效「全局设置 > Kubernetes 集群管理」用 ACK 服务连接 `fmayt57b9ttcjq61` 关联 `ruishi-prod-acs`（真实集群 ID `cebc88343a44b4d759aa983a47b787835`），Flow 集群 ID `UIuvaR8vFrIjY4lj`，并邀请 `power-application-user` 为使用者。该 ID 已通过流水线创建校验。参见[云效 Kubernetes 集群管理](https://help.aliyun.com/zh/yunxiao/user-guide/kubernetes-cluster-management)。
5. （备选）若部署阶段不走 Flow 集群资源而用 shell+阿里云 CLI：需为 CI 准备经批准的 ACR/CS 权限并确认集群 API 可达。优先完成上述集群注册。

流水线 YAML 校验报错时按报错信息调整 step 标识符（以云效「YAML 步骤清单」为准），apply 可反复执行直至通过。

## 命令用法（etbst-api 试点）

日常通过 deploySys 菜单/网页执行；也可手工：

```bash
cd /Volumes/SSD/work/deploy-sys

# 1. 推送本地已提交的 release 分支（本地须为远端后代；未提交文件不会推送）
FLOW_PIPELINE_ID=<ID> FLOW_REPO_DIR=/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api \
  bash scripts/flow-release.sh push

# 2. 触发构建并跟踪（不推送；流水线源分支固定 release）
FLOW_PIPELINE_ID=5300352 FLOW_DEPLOY_PIPELINE_ID=5300396 \
FLOW_ACR_INSTANCE_ID=cri-73ffxebpi6ruw6sn FLOW_ACR_REPO_ID=crr-gkqkb2np05u435bf \
FLOW_IMAGE_REPO=ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api \
FLOW_SERVICE=etbst-api FLOW_DEPLOY_MODE=local bash scripts/flow-release.sh build
#    成功后核对 ACR digest、启动部署流水线并停在人工确认。

# 3. 通过确认卡点上线（等价于在控制台点确认，必须显式 FLOW_CONFIRM=yes）
FLOW_DEPLOY_PIPELINE_ID=5300396 FLOW_SERVICE=etbst-api FLOW_DEPLOY_MODE=local \
FLOW_ACR_INSTANCE_ID=cri-73ffxebpi6ruw6sn FLOW_ACR_REPO_ID=crr-gkqkb2np05u435bf \
FLOW_IMAGE_REPO=ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api \
FLOW_NAMESPACE=etbst-api FLOW_DEPLOYMENT=etbst-api FLOW_CONTAINER=etbst-api FLOW_EXPECTED_REPLICAS=1 FLOW_CONFIRM=yes \
  bash scripts/flow-release.sh deploy

# 4. 只读状态（最近 5 次运行 + 本地状态文件 data/flow-state/<service>.env）
FLOW_PIPELINE_ID=5300396 FLOW_SERVICE=etbst-api bash scripts/flow-release.sh status

# 5. 创建/更新两条流水线
FLOW_PIPELINE_ID=5300352 bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml
FLOW_PIPELINE_ID=5300396 bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api-confirm.yaml
```

**首次上线验收**按 [etbst 仓库内发布说明书](https://codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api)（分支 `docs/etbst-acs-release-handbook-20260926`，`Doc/deployment/etbst-api-acs-release-runbook.md`）执行：核对源 Commit 与镜像 digest、探针/日志/DNS/Host 验收、回滚目标记录。上线只更新镜像字段；Secret、资源规格、Ingress 变更仍走人工变更流程。

## 扩展到其他项目

本轮 18 个服务已完成配置，映射和流水线 ID 见[多项目发布清单](flow/multi-project-release.md)。后续新增服务按以下步骤：

1. 核对仓库、源分支、Dockerfile、ACR 仓库和 ACS Deployment，写入 `deployment/flow/services.yaml`；运行 `python3 scripts/generate-flow-pipelines.py` 生成构建及确认 YAML。
2. 创建两条手动流水线，将 ID 写入 `deployment/flow/pipeline-ids.yaml`；运行 `python3 scripts/sync-flow-menus.py` 更新本机菜单。
3. 首次构建和上线另行授权并按项目 runbook 验收；登记首次发布日期和镜像 digest。

Java 服务（ACS 在用）：dgye-api、vet-api（0 副本）、stopmp-api、etbst-api、ddmp-api、yangu-api、m1x-api、m1x-worker。.NET 五项目仓库与角色见 [dotnet-acs/inventory.md](dotnet-acs/inventory.md)。

## 风险与边界

- 云效免费版有构建时长额度，全量接入前评估用量；ACR 经济版构建并发限制与 Flow 无关（Flow 构建在 Flow Runner，push 不受限）。
- 部署卡点人工确认不自动化跳过；`deploy` 必须显式 `FLOW_CONFIRM=yes`。
- Worker 类 Deployment（m1x-worker 等）上线前仍须按交接文档确认旧实例停机与在途任务，流水线只负责镜像更新。

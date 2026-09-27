# 云效 Flow 发布命令（API/Worker → ACR/ACS）

状态：2026-09-27 更新。生产 api/worker 服务已迁入北京 ACS（镜像在 ACR），本地不再打包部署到单机 ECS；本篇记录 deploySys 的云效 Flow 远程发布命令与试点结果。试点项目 **etbst-api**。.NET 项目的 ACS 运维文档仍在 [dotnet-acs](dotnet-acs/) 目录。

## 架构与命令

```
本地 deploySys ──▶ 构建流水线 5300352：Codeup release → Docker build → push ACR
               └─▶ ACR API 回读唯一 tag 的 digest
                    └─▶ 部署流水线 5300396：输入校验 → 人工确认 → 固定 digest 更新 ACS Deployment
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

构建流水线 `5300352` 运行 `4` 整体 **SUCCESS**；Codeup `release` Commit `1e09bf8147b5eba0d04ef4fe0333003e4ad887b2`，ACR tag `2026-09-27-18-40-20-1e09bf81`，ACR API `get-repo-tag` 回读 Digest `325cefc75daa088d274c073873884a2a1e4fd15f81b9bc64f135e5a92e30526d`，状态 `NORMAL`。部署流水线 `5300396` 运行 `2` 已通过镜像地址/Commit 输入校验，**WAITING** 在人工确认，尚未更新 ACS。运行 `1` 曾用于验证卡点，随后主动停止，未执行部署。上线前还需只读回读目标 Deployment 的实际容器名和原镜像，以保留回滚目标。

注意：`ListServiceConnections` 查询 Codeup 时必须传 `--sericeConnectionType codeup`（小写）；CLI 帮助列出的 `Codeup`（大写）会返回空列表。此前由此造成的“连接未生效”判断已纠正。

2026-09-27 通过 svision100 主账号的 CLI OAuth 配置 `svision100code` 执行单仓库授权：`power-application-user`（`accountId=203420990220401362`）在组织中状态为 `normal`、角色为“成员”，在 `ddmp/et-bst-api` 仓库中为活跃浏览者（20）。未授予其他仓库权限。

流水线模板中的 `ACREEDockerBuild` 和 `KubectlSetImage` 已按[云效官方步骤清单](https://help.aliyun.com/zh/yunxiao/user-guide/step-steps-list)核对。本地脚本在成功运行的源码 Commit、ACR 镜像创建时间和 tag 后缀之间建立唯一关联，再以 `get-repo-tag` 回读 digest；匹配不唯一时拒绝启动部署。

目标 ACR 仓库 `ruishi-java-prod/etbst-api`，仓库 ID `crr-gkqkb2np05u435bf`；`get-repo-tag` 已验证本次新构建 tag 的 Digest。部署流水线变量 `IMAGE_DIGEST_REF` 使用 VPC 域名加 `@sha256:`；`SOURCE_COMMIT` 记录完整源码提交。首次 ACS 执行和 Pod 验收仍待完成。

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

# 1. 推送本地 release 分支（要求工作区干净、本地为远端后代，可快进）
FLOW_PIPELINE_ID=<ID> FLOW_REPO_DIR=/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api \
  bash scripts/flow-release.sh push

# 2. 触发构建并跟踪（不推送；流水线源分支固定 release）
FLOW_PIPELINE_ID=5300352 FLOW_DEPLOY_PIPELINE_ID=5300396 \
FLOW_ACR_INSTANCE_ID=cri-73ffxebpi6ruw6sn FLOW_ACR_REPO_ID=crr-gkqkb2np05u435bf \
FLOW_IMAGE_REPO=ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api \
FLOW_SERVICE=etbst-api bash scripts/flow-release.sh build
#    成功后核对 ACR digest、启动部署流水线并停在人工确认。

# 3. 通过确认卡点上线（等价于在控制台点确认，必须显式 FLOW_CONFIRM=yes）
FLOW_DEPLOY_PIPELINE_ID=5300396 FLOW_RUN_ID=<部署运行ID> FLOW_CONFIRM=yes \
  bash scripts/flow-release.sh deploy

# 4. 只读状态（最近 5 次运行 + 本地状态文件 data/flow-state/<service>.env）
FLOW_PIPELINE_ID=5300396 FLOW_SERVICE=etbst-api bash scripts/flow-release.sh status

# 5. 创建/更新两条流水线
FLOW_PIPELINE_ID=5300352 bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml
FLOW_PIPELINE_ID=5300396 bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api-deploy.yaml
```

**首次上线验收**按 [etbst 仓库内发布说明书](https://codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api)（分支 `docs/etbst-acs-release-handbook-20260926`，`Doc/deployment/etbst-api-acs-release-runbook.md`）执行：核对源 Commit 与镜像 digest、探针/日志/DNS/Host 验收、回滚目标记录。上线只更新镜像字段；Secret、资源规格、Ingress 变更仍走人工变更流程。

## 复制到其他项目（模板）

每个服务（api 或 worker）三步：

1. 复制构建及部署两份 YAML，改名称/仓库/分支/ACR 仓库/Deployment 名，分别 `apply` 创建流水线；
2. `config/projects.local.yaml` 对应项目下新增 `api-flow-push/build/deploy` 服务条目，填构建及部署流水线 ID、ACR 实例/仓库 ID 与镜像仓库地址；
3. 首次构建成功后按 runbook 验收，并在本文件登记：流水线 ID、首次发布日期、镜像 digest。

Java 服务（ACS 在用）：dgye-api、vet-api（0 副本）、stopmp-api、etbst-api、ddmp-api、yangu-api、m1x-api、m1x-worker。.NET 五项目仓库与角色见 [dotnet-acs/inventory.md](dotnet-acs/inventory.md)。

## 风险与边界

- 云效免费版有构建时长额度，全量接入前评估用量；ACR 经济版构建并发限制与 Flow 无关（Flow 构建在 Flow Runner，push 不受限）。
- 部署卡点人工确认不自动化跳过；`deploy` 必须显式 `FLOW_CONFIRM=yes`。
- Worker 类 Deployment（m1x-worker 等）上线前仍须按交接文档确认旧实例停机与在途任务，流水线只负责镜像更新。

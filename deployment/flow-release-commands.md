# 云效 Flow 发布命令（API/Worker → ACR/ACS）

状态：2026-09-27 建立。生产 api/worker 服务已迁入北京 ACS（镜像在 ACR），本地不再打包部署到单机 ECS；本篇记录 deploySys 新增的云效 Flow 远程发布命令、现网核实结论和待办的控制台授权清单。试点项目 **etbst-api**，跑通后按「复制到其他项目」模板逐个接入。.NET 项目的 ACS 运维文档仍在 [dotnet-acs](dotnet-acs/) 目录，与本篇互不覆盖。

## 架构与命令

```
本地 deploySys ──aliyun devops API──▶ 云效 Flow 流水线（etbst-api-发布）
                                        ├─ 构建阶段：Codeup release 分支 → docker build → push ACR
                                        │  （ruishi-java-prod/etbst-api，tag 不可变，记录 digest）
                                        ├─ 人工确认卡点（本地 deploy 命令或云效控制台通过）
                                        └─ 部署阶段：固定 digest 更新 ACS Deployment（滚动）
```

- **不做 push 自动构建**：流水线手动触发，两种用法——`push`（先推送本地 release 分支）+ `build`（触发构建远端 release 当前提交），或只 `build`。
- 本地命令：`scripts/flow-release.sh`，子命令 `push | build | deploy | status | apply`。
- 认证：阿里云 CLI，显式 `--profile ruishi-prod-acr --region cn-beijing`（默认 Profile 属其他账号，禁止省略）；每次操作前 STS 核对账号 `1442361567788059`。凭据失效执行 `aliyun configure --profile ruishi-prod-acr`。
- 云效组织：`svision100的代码库`，OrganizationId `659a5cefd64a2eb2dceb72f3`（脚本默认值；与 etbst Codeup 仓库相同组织）。

## 现网核实结论（2026-09-27）

| 项 | 结论 |
|---|---|
| 云效组织 | `svision100的代码库`，org `659a5cefd64a2eb2dceb72f3`；`power-application-user` 已手动同步为普通成员，`ListJoinedOrganizations` 和 `ListPipelines` API 成功；当前无流水线 |
| devops API | 先前在旧组织完成 CreatePipeline → StartPipelineRun → GetPipelineRun → DeletePipeline 冒烟；当前 svision100 组织的成员及只读 API 已验证，创建/运行尚待服务连接就绪 |
| 服务连接 | svision100 主账号与 `power-application-user` 经 API 查询均仅见 ACR 连接 `o1gxp5wzksoe1mtu`（API ID `581029`）；Codeup/ACK 列表为空。此前控制台曾显示私密 Codeup 连接 `xdghn746erjk8hdo`，但 API 未返回，不能视作可用；目标 ACR 企业版实例适配性尚未验证 |
| etbst 仓库 | `/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api`，origin `codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api.git`，`release` 分支在用，根目录 Dockerfile（多阶段 Maven 构建，适配容器部署） |
| Codeup API | svision100 主账号确认目标仓库 ID `6424213`，并经 `AddRepositoryMember` 将 `power-application-user` 加为单仓库浏览者（20）；管理员成员列表与该 RAM 用户的 `ListRepositories` 均回读成功 |
| ACR 直连 API | 同一 Profile 于 2026-09-27 复核 `GetInstance` 成功；此前 Unauthorized 不代表当前持续无权 |
| ACS/CS API | 同一 Profile 于 2026-09-27 复核 `DescribeClusterUserKubeconfig` 成功（未读取或保存内容）；此前 `ErrorClusterNotFound` 不代表当前持续无权 |

云效组织成员与目标代码仓库浏览权限已解决。下一步需确认可用的 Codeup、ACR 和 ACK 服务连接及其对流水线的可见范围。

2026-09-27 通过 svision100 主账号的 CLI OAuth 配置 `svision100code` 执行单仓库授权：`power-application-user`（`accountId=203420990220401362`）在组织中状态为 `normal`、角色为“成员”，在 `ddmp/et-bst-api` 仓库中为活跃浏览者（20）。未授予其他仓库权限。

流水线模板中的企业版镜像步骤 `ACREEDockerBuild` 和 Kubernetes 镜像步骤 `KubectlSetImage` 已按[云效官方步骤清单](https://help.aliyun.com/zh/yunxiao/user-guide/step-steps-list)核对。镜像步骤的标准制品包含 tag 地址，尚无已验证的 digest 传递方式；上线前必须取得 ACR digest 并传给部署步骤，不能用 tag 地址替代。

ACR 直连 API 已能读取目标仓库 `ruishi-java-prod/etbst-api`，仓库 ID 为 `crr-gkqkb2np05u435bf`。`cr list-repo-tag` 的返回含 `Digest` 字段；构建完成后可按本次唯一 tag 调用 `cr get-repo-tag --instance-id cri-73ffxebpi6ruw6sn --repo-id crr-gkqkb2np05u435bf --tag <本次tag> --region cn-beijing --profile ruishi-prod-acr` 查 digest。该查询能力已由现存 tag 的只读 API 返回证实，尚需验证新构建 tag 到部署任务的实际传值链路。

## 控制台一次性授权清单（待办）

优先通过阿里云 devops API 核验、创建可用连接；Codeup 的 OAuth 授权若 API 无法完成，需由授权账号处理。完成后把各 ID 回填到 `deployment/flow/pipeline-etbst-api.yaml` 并执行 `apply`：

1. **Codeup 服务连接**：单仓库浏览者权限已就绪。此前控制台可见的私密连接 `xdghn746erjk8hdo` 未出现在主账号 API 列表中；需取得当前流水线可用的连接 ID `<CODEUP_SC>`，并核验其对目标仓库的访问。
2. **容器镜像服务（企业版）服务连接**：核验现有连接 `o1gxp5wzksoe1mtu` 对北京实例 `cri-73ffxebpi6ruw6sn` 的适配性与流水线可用性，不合适再创建；记录 ID `<ACR_SC>`。
3. **容器服务 Kubernetes（ACK）服务连接**：选集群 `ruishi-prod-acs`（`cebc88343a44b4d759aa983a47b787835`），记录 ID `<ACK_SC>`。
4. （备选）若部署阶段不走 ACK 服务连接而用 shell+阿里云 CLI：需为 CI 准备经批准的 ACR/CS 权限并确认集群 API 可达。优先用 1-3 的服务连接方案。

流水线 YAML 校验报错时按报错信息调整 step 标识符（以云效「YAML 步骤清单」为准），apply 可反复执行直至通过。

## 命令用法（etbst-api 试点）

日常通过 deploySys 菜单/网页执行；也可手工：

```bash
cd /Volumes/SSD/work/deploy-sys

# 1. 推送本地 release 分支（要求工作区干净、本地为远端后代，可快进）
FLOW_PIPELINE_ID=<ID> FLOW_REPO_DIR=/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api \
  bash scripts/flow-release.sh push

# 2. 触发构建并跟踪（不推送；流水线源分支固定 release）
FLOW_PIPELINE_ID=<ID> bash scripts/flow-release.sh build
#    运行卡在人工确认时，命令会提示；也可在云效控制台确认。

# 3. 通过确认卡点上线（等价于在控制台点确认，必须显式 FLOW_CONFIRM=yes）
FLOW_PIPELINE_ID=<ID> FLOW_RUN_ID=<运行ID> FLOW_CONFIRM=yes \
  bash scripts/flow-release.sh deploy

# 4. 只读状态（最近 5 次运行 + 本地状态文件 data/flow-state/<service>.env）
FLOW_PIPELINE_ID=<ID> FLOW_SERVICE=etbst-api bash scripts/flow-release.sh status

# 5. 创建/更新流水线（YAML 见 deployment/flow/pipeline-etbst-api.yaml）
bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml
```

**首次上线验收**按 [etbst 仓库内发布说明书](https://codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api)（分支 `docs/etbst-acs-release-handbook-20260926`，`Doc/deployment/etbst-api-acs-release-runbook.md`）执行：核对源 Commit 与镜像 digest、探针/日志/DNS/Host 验收、回滚目标记录。上线只更新镜像字段；Secret、资源规格、Ingress 变更仍走人工变更流程。

## 复制到其他项目（模板）

每个服务（api 或 worker）三步：

1. 复制 `deployment/flow/pipeline-etbst-api.yaml` 改名称/仓库/分支/ACR 仓库/Deployment 名，`apply` 创建流水线；
2. `config/projects.local.yaml` 对应项目下新增 `api-flow-push/build/deploy` 服务条目（填 FLOW_PIPELINE_ID）；
3. 首次构建成功后按 runbook 验收，并在本文件登记：流水线 ID、首次发布日期、镜像 digest。

Java 服务（ACS 在用）：dgye-api、vet-api（0 副本）、stopmp-api、etbst-api、ddmp-api、yangu-api、m1x-api、m1x-worker。.NET 五项目仓库与角色见 [dotnet-acs/inventory.md](dotnet-acs/inventory.md)。

## 风险与边界

- 云效免费版有构建时长额度，全量接入前评估用量；ACR 经济版构建并发限制与 Flow 无关（Flow 构建在 Flow Runner，push 不受限）。
- 部署卡点人工确认不自动化跳过；`deploy` 必须显式 `FLOW_CONFIRM=yes`。
- Worker 类 Deployment（m1x-worker 等）上线前仍须按交接文档确认旧实例停机与在途任务，流水线只负责镜像更新。

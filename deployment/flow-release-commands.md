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
- 云效组织：`ruishi365的企业`，OrganizationId `658d5b8ae7f9ce3ec8199dc0`（脚本已固化默认值）。

## 现网核实结论（2026-09-27）

| 项 | 结论 |
|---|---|
| 云效组织 | 已开通，org `658d5b8ae7f9ce3ec8199dc0`；现有 4 条 2024 年测试流水线（yangu-train-test 等，coding.net 代码源） |
| devops API | 冒烟全通：CreatePipeline → StartPipelineRun（API 触发）→ GetPipelineRun → DeletePipeline，运行 SUCCESS |
| 服务连接 | 仅有 Codeup 连接 `578243`（2024-01 建，对 `ddmp/et-bst-api` 无访问权限）；**无 ACR、无 ACK 服务连接** |
| etbst 仓库 | `/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api`，origin `codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api.git`，`release` 分支在用，根目录 Dockerfile（多阶段 Maven 构建，适配容器部署） |
| ACR 直连 API | 当前 RAM 用户 `power-application-user` 调 ACR EE API 返回 `AUTHENTICATION_FAILED`（Unauthorized） |
| ACS/CS API | 同一身份 `GET /clusters` 返回空、kubeconfig 接口报 `ErrorClusterNotFound`——**该 RAM 用户当前看不到集群**（交接期曾可用，权限有变动） |

权限缺口不影响本地命令（只用 devops API），但影响流水线构建/部署阶段和服务连接创建，见下方清单。

## 控制台一次性授权清单（待办）

以下操作需要云效/阿里云控制台权限（OAuth、RAM 授权），CLI 无法代做。完成后把各 ID 回填到 `deployment/flow/pipeline-etbst-api.yaml` 并执行 `apply`：

1. **Codeup 服务连接**（流水线设置 → 服务连接管理 → 新建 Codeup）：授权账号须能访问 `ddmp/et-bst-api`（Codeup 组织 `659a5cefd64a2eb2dceb72f3`）。旧连接 `578243` 无权限，建议新建并记录 ID `<CODEUP_SC>`。
2. **容器镜像服务（企业版）服务连接**：选北京实例 `cri-73ffxebpi6ruw6sn`，记录 ID `<ACR_SC>`。
3. **容器服务 Kubernetes（ACK）服务连接**：选集群 `ruishi-prod-acs`（`cebc88343a44b4d759aa983a47b787835`），记录 ID `<ACK_SC>`。
4. （备选）若部署阶段不走 ACK 服务连接而用 shell+阿里云 CLI：需为 CI 准备一个有 ACR/CS 权限的 RAM 用户并确认集群公网 API 可达；当前 `power-application-user` 两项都缺。优先用 1-3 的服务连接方案。

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

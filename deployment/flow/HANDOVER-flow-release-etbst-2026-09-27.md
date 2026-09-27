# 交接：云效 Flow 发布命令接入（etbst-api 试点）

日期：2026-09-27。操作仓库：deploy-sys，分支 `deploy/acs-acceptance-evidence`。运维细节以 [../flow-release-commands.md](../flow-release-commands.md) 为准，本篇是任务交接：目标、进度、待办、问题。

## 一、任务目标

生产 api/worker 服务已从"本地打包 + SSH 部署单机 ECS"迁入北京 ACS（镜像在 ACR 企业版）。目标是在本地 deploySys 里执行部署任务，远程完成"构建镜像 → push ACR → 上线 ACS"，即：

1. 采用**云效 Flow**（不沿用 ACR 云构建 + 短时 kubeconfig + kubectl 的手工链路）；
2. 流水线**手动触发，push 不自动构建**；本地可"先推送 release 再触发"，也可"直接对远端 release 当前提交触发构建"；
3. 上线前保留**人工确认卡点**（不自动化跳过）；
4. 试点 `ruishi-java-prod` 下的 **etbst-api**，完全跑通验收后，按模板依次接入其余项目（dgye/vet/stopmp/ddmp/yangu/m1x-api/m1x-worker 及 .NET 五项目）。

## 二、当前进度

**已完成：**

- 现网只读核实（身份、云效组织、服务连接、etbst 仓库/Dockerfile/发布说明书、ACR/CS 权限现状），结论见 [../flow-release-commands.md](../flow-release-commands.md)。
- devops API 曾在旧组织完成创建流水线 → 触发运行 → SUCCESS → 删除的冒烟（流水线 `5300139` 已清理）。当前 svision100 组织已验证成员及只读 API，尚未创建正式流水线。
- `scripts/flow-release.sh`：子命令 `push | build | deploy | status | apply`。STS 核验和云效 API 调用均显式使用 `--profile ruishi-prod-acr --region cn-beijing`；`deploy` 必须显式 `FLOW_CONFIRM=yes`；`apply` 会拒绝尚有占位符的 YAML；状态落盘 `data/flow-state/`（已 gitignore）。
- 流水线 YAML 模板 `deployment/flow/pipeline-etbst-api.yaml`（已按官方步骤清单核对 ACR 企业版构建和 Kubernetes 镜像更新的标识符及字段；服务连接、人工确认及 digest 传递待回填和验证）。
- deploySys 本机注册：ETBST 项目下 `api-flow-push / api-flow-build / api-flow-deploy` 三个命令块（`config/projects.local.yaml`，私有不入库），流水线 ID 待填。
- 文档：`deployment/flow-release-commands.md`、README 新章节、`config/projects.yaml` 模板注释。
- `power-application-user` 已手动同步为 `svision100的代码库`（`659a5cefd64a2eb2dceb72f3`）的普通成员；`ListJoinedOrganizations`、`ListPipelines`、`ListServiceConnections` API 已可调用。发布脚本默认组织已纠正为该组织。
- 已用 svision100 主账号通过阿里云 API 将 `power-application-user` 加为 `ddmp/et-bst-api`（仓库 ID `6424213`）的单仓库浏览者（20）；管理员成员列表和该 RAM 用户的仓库列表均已回读确认。
- 新 ACR 服务连接 `lhjkwns3zhj879ic`（API ID `943301`）已由 svision100 设置为指定成员可见，`power-application-user` 经 devops API 回读可见；目标企业版实例推送能力尚待流水线实测。
- Codeup 服务连接 `xdghn746erjk8hdo`（API ID `580982`）已将 `power-application-user` 列为使用者；以 `--sericeConnectionType codeup`（小写）调用 API 后回读可见。目标仓库拉取能力尚待流水线实测。
- 仓库单测 27/28 过，1 个失败是本机 git 2.15 过旧（不支持 `git init -b`）的既有环境问题，与本次无关。

**未完成（服务连接和 digest 传递待落实）：** 流水线正式创建、首次真实构建与上线验收。

## 三、待办事项

**A. 服务连接待办（优先经 API，必要时由授权账号在控制台处理）：**

1. 核验 **Codeup 服务连接** `xdghn746erjk8hdo`（API ID `580982`）在流水线中能否实际拉取 `ddmp/et-bst-api`；单仓库浏览者权限和服务连接可见性均已回读确认。
2. 核验新 **ACR 服务连接** `lhjkwns3zhj879ic`（API ID `943301`）能否用于企业版实例 `cri-73ffxebpi6ruw6sn` 及目标流水线；其对目标 RAM 用户的可见性已验证，推送能力尚未验证。
3. 创建 **Kubernetes（ACK/ACS）服务连接**：集群 `ruishi-prod-acs`（`cebc88343a44b4d759aa983a47b787835`）；`power-application-user` 查询 ACK 连接列表为空。
4. 对服务授权和服务连接使用范围做最小权限核验，再以 API 回读确认。

**B. 管理员完成 A 之后（AI 会话可继续执行）：**

1. Codeup 与 ACR 服务连接 ID 已回填 `deployment/flow/pipeline-etbst-api.yaml`；继续回填 `<ACK_SC>`，补齐人工确认、实际容器名及构建产物 digest 的查询、校验和传递。当前 YAML 仍是骨架，不能直接 apply；云效镜像制品默认提供 tag 地址，不得直接用于要求固定 digest 的生产部署。
2. `bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml` 创建流水线，把流水线 ID 填入 `config/projects.local.yaml`（替换 `__FLOW_PIPELINE_ID__`）并更新模板文档。
3. 与管理员确认时机后跑首次真实构建：`push`（如需）→ `build` → 按仓库内 etbst 发布说明书（分支 `docs/etbst-acs-release-handbook-20260926`，`Doc/deployment/etbst-api-acs-release-runbook.md`）验收上线。
4. 跑通后按 [../flow-release-commands.md](../flow-release-commands.md)「复制到其他项目」模板逐个接入，并在该文件登记流水线 ID。

## 四、遇到的问题和难点

1. **Codeup 服务连接查询大小写**：旧组织连接 `578243` 对 `ddmp/et-bst-api` 报"代码仓库不存在或者无权限"；正确组织的仓库成员权限和连接可见性已修复。`ListServiceConnections --sericeConnectionType Codeup`（CLI 帮助中的大小写）返回空，改用 `codeup` 后主账号与目标 RAM 用户均可见连接 `xdghn746erjk8hdo`。
2. **权限现状需区分产品核验**：此前 ACR/CS 调用曾失败；2026-09-27 同一 Profile 调用 ACR `GetInstance` 成功，CS `DescribeClusterUserKubeconfig`（15 分钟临时配置）也成功，未显示或保存 kubeconfig。云效组织成员资格已修复，剩余问题是服务授权及连接的目标实例、可见范围。
3. **固定 digest 尚未打通**：云效官方步骤清单明确企业版镜像构建为 `ACREEDockerBuild`、Kubernetes 镜像更新为 `KubectlSetImage`，但构建步骤的标准镜像制品给出的是 tag 地址。需在部署前取得并校验 ACR digest，并确认能传给 `KubectlSetImage.artifact`；不能把 tag 地址当作固定 digest。
4. **手动触发与代码源默认 webhook 的张力**：要求"push 不自动构建"，模板用 `triggerEvents: []`，创建后需回读配置确认没有残留 push 触发。
5. **既有资料的两点澄清**：生产链路目前是 ACR 云构建+手工 kubectl，本次要切到 Flow；旧组织 `658d5b8ae7f9ce3ec8199dc0` 的 2024 年测试流水线不属于当前 `svision100` 组织，不能作为本试点的现有流水线。

## 五、关键常量速查

| 项 | 值 |
|---|---|
| 阿里云账号 / RAM 用户 | `1442361567788059` / `power-application-user`（Profile `ruishi-prod-acr`，cn-beijing） |
| 云效组织 | `svision100的代码库`，OrganizationId `659a5cefd64a2eb2dceb72f3` |
| devops API 端点 | `devops.cn-hangzhou.aliyuncs.com`（CLI 必须显式 `--endpoint`） |
| ACS 集群 | `ruishi-prod-acs`，`cebc88343a44b4d759aa983a47b787835` |
| ACR 企业版实例 | `cri-73ffxebpi6ruw6sn`，Java 命名空间 `ruishi-java-prod` |
| etbst 源码 | `/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api`，origin `codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api.git` |
| 本地状态目录 | `data/flow-state/`（gitignored） |

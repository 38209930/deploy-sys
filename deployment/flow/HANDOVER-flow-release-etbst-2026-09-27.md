# 交接：云效 Flow 发布命令接入（etbst-api 试点）

日期：2026-09-27。操作仓库：deploy-sys，分支 `deploy/acs-acceptance-evidence`，提交 `4cd7811`、`e07a58d`（均已推送）。运维细节以 [../flow-release-commands.md](../flow-release-commands.md) 为准，本篇是任务交接：目标、进度、待办、问题。

## 一、任务目标

生产 api/worker 服务已从"本地打包 + SSH 部署单机 ECS"迁入北京 ACS（镜像在 ACR 企业版）。目标是在本地 deploySys 里执行部署任务，远程完成"构建镜像 → push ACR → 上线 ACS"，即：

1. 采用**云效 Flow**（不沿用 ACR 云构建 + 短时 kubeconfig + kubectl 的手工链路）；
2. 流水线**手动触发，push 不自动构建**；本地可"先推送 release 再触发"，也可"直接对远端 release 当前提交触发构建"；
3. 上线前保留**人工确认卡点**（不自动化跳过）；
4. 试点 `ruishi-java-prod` 下的 **etbst-api**，完全跑通验收后，按模板依次接入其余项目（dgye/vet/stopmp/ddmp/yangu/m1x-api/m1x-worker 及 .NET 五项目）。

## 二、当前进度

**已完成：**

- 现网只读核实（身份、云效组织、服务连接、etbst 仓库/Dockerfile/发布说明书、ACR/CS 权限现状），结论见 [../flow-release-commands.md](../flow-release-commands.md)。
- devops API 冒烟全通：API 创建流水线 → API 触发运行 → 运行 SUCCESS → 删除（冒烟流水线 `5300139` 已清理）。
- `scripts/flow-release.sh`：子命令 `push | build | deploy | status | apply`。每次先 STS 核验账号 `1442361567788059`、显式 `--profile ruishi-prod-acr --region cn-beijing`；`deploy` 必须显式 `FLOW_CONFIRM=yes`；状态落盘 `data/flow-state/`（已 gitignore）。错误路径已实测。
- 流水线 YAML 模板 `deployment/flow/pipeline-etbst-api.yaml`（源码核验阶段已验证可用；构建/部署阶段的 step 标识符与服务连接待回填）。
- deploySys 本机注册：ETBST 项目下 `api-flow-push / api-flow-build / api-flow-deploy` 三个命令块（`config/projects.local.yaml`，私有不入库），流水线 ID 待填。
- 文档：`deployment/flow-release-commands.md`、README 新章节、`config/projects.yaml` 模板注释。
- 仓库单测 27/28 过，1 个失败是本机 git 2.15 过旧（不支持 `git init -b`）的既有环境问题，与本次无关。

**未完成（被授权卡住）：** 流水线正式创建、首次真实构建与上线验收。

## 三、待办事项

**A. 管理员控制台操作（一次性授权，CLI 无法代做）：**

1. 云效控制台新建 **Codeup 服务连接**：授权须能访问 `ddmp/et-bst-api`（Codeup 组织 `659a5cefd64a2eb2dceb72f3`）；旧连接 `578243`（2024-01 建）对该仓库无权限。
2. 新建 **容器镜像服务（企业版）服务连接**：北京实例 `cri-73ffxebpi6ruw6sn`。
3. 新建 **Kubernetes（ACK/ACS）服务连接**：集群 `ruishi-prod-acs`（`cebc88343a44b4d759aa983a47b787835`）。
4. 确认第 4 节"权限回退"问题：是否需要恢复或补授。

**B. 管理员完成 A 之后（AI 会话可继续执行）：**

1. 把三个服务连接 ID 回填 `deployment/flow/pipeline-etbst-api.yaml` 占位符（`<CODEUP_SC>` / `<ACR_SC>` / `<ACK_SC>`），确认构建/部署 step 标识符（对照云效「YAML 步骤清单」，apply 报错则按报错调整，可反复）。
2. `bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml` 创建流水线，把流水线 ID 填入 `config/projects.local.yaml`（替换 `__FLOW_PIPELINE_ID__`）并更新模板文档。
3. 与管理员确认时机后跑首次真实构建：`push`（如需）→ `build` → 按仓库内 etbst 发布说明书（分支 `docs/etbst-acs-release-handbook-20260926`，`Doc/deployment/etbst-api-acs-release-runbook.md`）验收上线。
4. 跑通后按 [../flow-release-commands.md](../flow-release-commands.md)「复制到其他项目」模板逐个接入，并在该文件登记流水线 ID。

## 四、遇到的问题和难点

1. **旧 Codeup 服务连接无权限**：连接 `578243` 对 `ddmp/et-bst-api` 报"代码仓库不存在或者无权限"，创建流水线失败。Codeup 服务连接是 OAuth 授权，只能控制台重做，CLI 代建不了（`CreateServiceAuth` 仅支持 RAM 类型）。
2. **ACR/CS API 权限回退（重点疑点）**：交接文档记载 `power-application-user`（`ruishi-prod-acr` Profile）曾成功调用 ACR EE API 与 CS kubeconfig 接口；本次实测 ACR EE API 返回 `AUTHENTICATION_FAILED`，`GET /clusters` 返回空、kubeconfig 接口报 `ErrorClusterNotFound`。疑似交接后被收权。影响：无法用 CLI 直读镜像构建记录和集群状态；备选的 shell+AK 部署方案也被阻塞。未擅自改权限，需管理员确认。
3. **YAML step 标识符无权威可查**：云效官方文档只确认了 `JavaBuild`、`ArtifactUpload`、`Command` 等；"镜像构建并推送 ACR 企业版""Kubernetes 部署"的 YAML 标识符文档不可达，devops API 也不提供步骤清单。对策：apply 时借 YAML 校验报错迭代确认。
4. **手动触发与代码源默认 webhook 的张力**：要求"push 不自动构建"，模板用 `triggerEvents: []`，创建后需回读配置确认没有残留 push 触发。
5. **既有资料的两点澄清**：生产链路不是云效 Flow（是 ACR 云构建+手工 kubectl，本次正是要切到 Flow）；`docs/dgye_*实施手册` 里的 Flow 流水线只是规划，并未创建（现存 4 条流水线均为 2024 年测试线，coding.net 代码源）。

## 五、关键常量速查

| 项 | 值 |
|---|---|
| 阿里云账号 / RAM 用户 | `1442361567788059` / `power-application-user`（Profile `ruishi-prod-acr`，cn-beijing） |
| 云效组织 | `ruishi365的企业`，OrganizationId `658d5b8ae7f9ce3ec8199dc0` |
| devops API 端点 | `devops.cn-hangzhou.aliyuncs.com`（CLI 必须显式 `--endpoint`） |
| ACS 集群 | `ruishi-prod-acs`，`cebc88343a44b4d759aa983a47b787835` |
| ACR 企业版实例 | `cri-73ffxebpi6ruw6sn`，Java 命名空间 `ruishi-java-prod` |
| etbst 源码 | `/Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api`，origin `codeup.aliyun.com/659a5cefd64a2eb2dceb72f3/ddmp/et-bst-api.git` |
| 本地状态目录 | `data/flow-state/`（gitignored） |

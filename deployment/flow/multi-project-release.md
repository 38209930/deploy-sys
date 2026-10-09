# 多项目 ACS 发布菜单与流水线（2026-09-27）

首次生产发布与 ACS 回读结果见 [验收记录](acceptance-2026-09-27.md)。

## Java 依赖源

7 条 Java 构建流水线均从项目 Dockerfile 显式使用仓库内的 `maven-settings.xml`，把 Maven Central 映射到阿里云公共镜像。Yangu、DDMP 保留已有配置；M1X API／Worker、STOPMP、DGYE、VET 在各自代码库的 `release` 分支补齐 Dockerfile 与设置文件。Flow 仅将基础镜像地址从 VPC 域名改为公网域名，不再改写 Maven 命令。每次手动构建开始时，准备步骤检查设置文件、镜像地址及 Dockerfile 的 `COPY`／`mvn -s`，失败则阻止后续构建；通过时输出 `maven_mirror_verified=aliyun-public source=dockerfile`。构建完成后，原有命令继续核对源码提交、ACR tag 和 digest。本次只更新代码和流水线定义，没有触发构建或上线；首次运行时由流水线执行上述检查。

| 代码库 | `release` 配置提交 |
| --- | --- |
| M1X API／Worker | `f713093` |
| STOPMP API | `e47808e` |
| DGYE API | `a488242` |
| VET API | `287c1eb` |

以下记录的是配置阶段的状态：当时仅完成配置与只读核验，尚未启动新流水线构建或更新生产镜像。

## 发布路径

1. 在项目菜单选择对应服务的「发布」，查看生产发布提示并选择需要合入 release 的分支，继续执行。菜单自动切换或使用已有 release 工作区，同步并推送所选源码。
2. 同一个命令自动完成 Flow 构建、唯一源码提交与 ACR digest 核验、确认卡点、ACS 镜像更新和 rollout 验收。菜单显式设置 `FLOW_CONFIRM=yes`。同一提交的未结束构建可继续跟踪，已构建的待上线镜像可复用；提交变化后重新构建。Flow 本身不随 push 自动构建；新零售 ACR 自动构建仍是独立路径，不要同时人工触发另一条构建。
3. 同一服务选择「状态检查」，可读取构建 Flow、确认 Flow 以及 ACS Deployment/Pod 资源和重启情况。需要查看日志时直接运行 `scripts/etbst-logs.py` 并传入目标 namespace、deployment、container。

ETBST 已有构建流水线 `5300352`，人工确认流水线 `5300396` 已更新为仅确认。本机菜单也改用相同的本机镜像更新路径。原 Flow `KubectlSetImage` 配置 `kubectl 1.27.9`，与当前 ACS API Server `1.36.1` 差距过大，故暂不用于更新生产镜像。

## 服务映射与流水线 ID

| 服务 | 分支 | Dockerfile | ACR 仓库 ID | ACS Namespace / Deployment / 容器 | 副本 | 构建 ID | 确认 ID |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| ETBST API | `release` | `Dockerfile` | `crr-gkqkb2np05u435bf` | `etbst-api / etbst-api / etbst-api` | 1 | 5300352 | 5300396 |
| Yangu API | `release` | `Dockerfile` | `crr-7eg2q1ccbyn326lv` | `yangu-api / yangu-api / yangu-api` | 1 | 5300550 | 5300551 |
| M1X API | `release` | `Dockerfile.api` | `crr-nvuwwmvp3yl6251q` | `m1x-api / m1x-api / m1x-api` | 1 | 5300552 | 5300553 |
| M1X Worker | `release` | `Dockerfile.worker` | `crr-7uns9jn34ldb8tq8` | `m1x-api / m1x-worker / m1x-worker` | 1 | 5300554 | 5300555 |
| DDMP API | `release` | `Dockerfile` | `crr-rs4b947f800rjbnq` | `ddmp-api / ddmp-api / ddmp-api` | 1 | 5300556 | 5300557 |
| STOPMP API | `release` | `Dockerfile` | `crr-t3ee0w9d3h4nr0u4` | `stopmp-api / stopmp-api / stopmp-api` | 1 | 5300558 | 5300559 |
| DGYE API | `release` | `Dockerfile` | `crr-681p10rite288myu` | `dgye-api / dgye-api / dgye-api` | 0 | 5300560 | 5300561 |
| VET API | `release` | `Dockerfile` | `crr-x7n66p8xupkad79q` | `vet-api / vet-api / vet-api` | 0 | 5300562 | 5300563 |
| 新零售前台 API | `release` | `Dockerfile.frontapi` | `crr-15tsn10lfuopeca3` | `new-retail / new-retail-front / front` | 1 | 5300564 | 5300565 |
| 新零售后台 API | `release` | `Dockerfile.backapi` | `crr-jgcdoev5lsv3c13n` | `new-retail / new-retail-back / back` | 1 | 5300566 | 5300567 |
| 新零售 Worker | `release` | `Dockerfile.worker` | `crr-6qbw9xs9j2g89y07` | `new-retail / new-retail-worker / worker` | 1 | 5300568 | 5300569 |
| 积分商城前台 API | `release` | `Visionisok.Api/Dockerfile` | `crr-vdgtaw2phsb1n76h` | `points-mall / points-mall-front / points-mall-front` | 1 | 5312498 | 5312499 |
| 积分商城后台 API | `release` | `Visionisok.Admin/Dockerfile` | `crr-wl4s6tkt2g800cb1` | `points-mall / points-mall-back / points-mall-back` | 1 | 5300570 | 5300571 |
| 积分商城 Worker | `release` | `Visionisok.Worker/Dockerfile` | `crr-2cjij63p35rdmn30` | `points-mall / points-mall-worker / points-mall-worker` | 1 | 5300572 | 5300573 |
| 售后工单前台 API | `release` | `Dockerfile.front` | `crr-g81gg6q5ug03sf67` | `service-order / service-order-front / service-order-front` | 1 | 5300574 | 5300575 |
| 售后工单后台 API | `release` | `Dockerfile.back` | `crr-xb24atsy4999plnt` | `service-order / service-order-back / service-order-back` | 1 | 5300576 | 5300577 |
| 售后工单 Worker | `release` | `Dockerfile.worker` | `crr-svf8bbfgno27xoxx` | `service-order / service-order-worker / service-order-worker` | 1 | 5300578 | 5300579 |
| AI 自习室后台 API | `release` | `Dockerfile.backapi` | `crr-ts4ie274rsl4e5s8` | `ai-study / ai-study-back / ai-study-back` | 1 | 5300580 | 5300581 |
| AI 自习室 Worker | `release` | `Dockerfile.worker` | `crr-bdsng7yy7sw22xla` | `ai-study / ai-study-worker / ai-study-worker` | 1 | 5300583 | 5300584 |
| 授权经销商 API | `release` | `AgentQuery.DealerQuery/Dockerfile` | `crr-4i7hgjfdejp786j5` | `agent-query / agent-query-api / api` | 1 | 5300585 | 5300586 |

`services.yaml` 还记录 Codeup 地址及本机仓库路径；`pipeline-ids.yaml` 记录完整流水线 ID。所有 Flow 构建流水线 `triggerEvents: []`，仅手动触发；每个确认流水线均含 `ManualValidate`。积分商城前台的构建/确认流水线分别为 `5312498`、`5312499`，由 `Visionisok.Api/Dockerfile` 构建并发布到现有 `points-mall-front` Deployment。2026-10-01 新零售三服务已迁至独立 `new-store/new-store-api.git` 的 `release`，本地清单、生成模板、本机菜单与云端定义对齐；旧 `product/new-retail` 只作历史入口。ACR 自动构建开启与 Flow 手动构建是两条不同路径，配置回读不证明首次新仓构建或上线成功。

## 安全边界与遗留入口

- `power-application-user` 已逐库获得上述目标代码库只读级别 `20`，逐库 API 回读为 `active`；无仓库写权限。
- 上线前必须从本次 Flow 构建关联唯一 ACR digest。镜像仓库、ACS 命名空间、Deployment、容器及副本数均有本机校验；DGYE、VET 必须保持 0 副本。
- 已迁入 ACS 的旧生产 ECS API 发布／重启入口已从本机菜单移除。积分商城 Front、Back、Worker 均由 ACS Flow 菜单管理；测试、PC、OSS、小程序及其他现用入口保留。授权经销商前后台共用 `agent-query-api`。
- `config/projects.local.yaml` 只在本机更新，不入库；可用 `python3 scripts/sync-flow-menus.py` 按清单与 ID 重新同步。

## 验收范围

2026-10-09 当前清单统一登记 20 个服务及 40 条构建／确认流水线（包含既有 ETBST 两条流水线）。17 个项目菜单和 51 个生产发布命令已排查，20 个 ACS 服务均改为单个发布入口。本次 86 项相关测试通过，包括模拟云效/ACS 的完整发布、构建超时续跑、源码不匹配拒绝上线和 rollout 失败重试；未触发真实云端构建或生产镜像更新。缺失 release 分支等实际阻碍见 [菜单排查记录](menu-audit-2026-10-09.md)。历史首次上线结果见上方验收记录。

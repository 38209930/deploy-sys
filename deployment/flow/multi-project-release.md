# 多项目 ACS 发布菜单与流水线（2026-09-27）

本次仅完成配置与只读核验；未启动任何新流水线构建，也未更新生产镜像。

## 发布路径

1. 在项目菜单选择对应服务的「Flow 推送」，将本地已提交的指定分支推到 Codeup。推送不会自动构建。
2. 选择「Flow 构建」，云效手动构建并推送至 ACR。命令核对唯一源码提交、当前运行时间内唯一 tag、ACR 回读 digest，随后启动独立人工确认流水线。
3. 审查提交、tag、digest 与目标服务后，选择「Flow 上线」。该菜单显式设置 `FLOW_CONFIRM=yes`，通过人工卡点，再用本机兼容的 `kubectl 1.36.1` 和 15 分钟 ACS 临时配置仅更新 Deployment 镜像字段，回读镜像与副本数。
4. 选择「ACS 查看日志」，可追加 `normal`、`error`、`warning`、`events`；DGYE/VET 零副本时显示无 Pod 日志，仍查询告警事件。

ETBST 已有构建流水线 `5300352`，人工确认流水线 `5300396` 已更新为仅确认。本机菜单也改用相同的本机镜像更新路径。原 Flow `KubectlSetImage` 配置 `kubectl 1.27.9`，与当前 ACS API Server `1.36.1` 差距过大，故暂不用于更新生产镜像。

## 服务映射与流水线 ID

| 服务 | 分支 | Dockerfile | ACR 仓库 ID | ACS Namespace / Deployment / 容器 | 副本 | 构建 ID | 确认 ID |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| Yangu API | `release` | `Dockerfile` | `crr-7eg2q1ccbyn326lv` | `yangu-api / yangu-api / yangu-api` | 1 | 5300550 | 5300551 |
| M1X API | `release` | `Dockerfile.api` | `crr-nvuwwmvp3yl6251q` | `m1x-api / m1x-api / m1x-api` | 1 | 5300552 | 5300553 |
| M1X Worker | `release` | `Dockerfile.worker` | `crr-7uns9jn34ldb8tq8` | `m1x-api / m1x-worker / m1x-worker` | 1 | 5300554 | 5300555 |
| DDMP API | `release` | `Dockerfile` | `crr-rs4b947f800rjbnq` | `ddmp-api / ddmp-api / ddmp-api` | 1 | 5300556 | 5300557 |
| STOPMP API | `release` | `Dockerfile` | `crr-t3ee0w9d3h4nr0u4` | `stopmp-api / stopmp-api / stopmp-api` | 1 | 5300558 | 5300559 |
| DGYE API | `release` | `Dockerfile` | `crr-681p10rite288myu` | `dgye-api / dgye-api / dgye-api` | 0 | 5300560 | 5300561 |
| VET API | `release` | `Dockerfile` | `crr-x7n66p8xupkad79q` | `vet-api / vet-api / vet-api` | 0 | 5300562 | 5300563 |
| 新零售前台 API | `product/new-retail` | `Dockerfile.frontapi` | `crr-15tsn10lfuopeca3` | `new-retail / new-retail-front / front` | 1 | 5300564 | 5300565 |
| 新零售后台 API | `product/new-retail` | `Dockerfile.backapi` | `crr-jgcdoev5lsv3c13n` | `new-retail / new-retail-back / back` | 1 | 5300566 | 5300567 |
| 新零售 Worker | `product/new-retail` | `Dockerfile.worker` | `crr-6qbw9xs9j2g89y07` | `new-retail / new-retail-worker / worker` | 1 | 5300568 | 5300569 |
| 积分商城后台 API | `release` | `Visionisok.Admin/Dockerfile` | `crr-wl4s6tkt2g800cb1` | `points-mall / points-mall-back / points-mall-back` | 1 | 5300570 | 5300571 |
| 积分商城 Worker | `release` | `Visionisok.Worker/Dockerfile` | `crr-2cjij63p35rdmn30` | `points-mall / points-mall-worker / points-mall-worker` | 1 | 5300572 | 5300573 |
| 售后工单前台 API | `release` | `Dockerfile.front` | `crr-g81gg6q5ug03sf67` | `service-order / service-order-front / service-order-front` | 1 | 5300574 | 5300575 |
| 售后工单后台 API | `release` | `Dockerfile.back` | `crr-xb24atsy4999plnt` | `service-order / service-order-back / service-order-back` | 1 | 5300576 | 5300577 |
| 售后工单 Worker | `release` | `Dockerfile.worker` | `crr-svf8bbfgno27xoxx` | `service-order / service-order-worker / service-order-worker` | 1 | 5300578 | 5300579 |
| AI 自习室后台 API | `release` | `Dockerfile.backapi` | `crr-ts4ie274rsl4e5s8` | `ai-study / ai-study-back / ai-study-back` | 1 | 5300580 | 5300581 |
| AI 自习室 Worker | `release` | `Dockerfile.worker` | `crr-bdsng7yy7sw22xla` | `ai-study / ai-study-worker / ai-study-worker` | 1 | 5300583 | 5300584 |
| 授权经销商 API | `release` | `AgentQuery.DealerQuery/Dockerfile` | `crr-4i7hgjfdejp786j5` | `agent-query / agent-query-api / api` | 1 | 5300585 | 5300586 |

`services.yaml` 还记录 Codeup 地址及本机仓库路径；`pipeline-ids.yaml` 记录完整流水线 ID。所有构建流水线 `triggerEvents: []`，仅手动触发；每个确认流水线均含 `ManualValidate`。新零售 `product/new-retail` 已快进到 `5ad0459`，包含 ACS 构建文件。

## 安全边界与遗留入口

- `power-application-user` 已逐库获得上述目标代码库只读级别 `20`，逐库 API 回读为 `active`；无仓库写权限。
- 上线前必须从本次 Flow 构建关联唯一 ACR digest。镜像仓库、ACS 命名空间、Deployment、容器及副本数均有本机校验；DGYE、VET 必须保持 0 副本。
- 已迁入 ACS 的旧生产 ECS API 发布／重启入口已从本机菜单移除。积分商城 Front 仍在 ECS；测试、PC、OSS、小程序及其他现用入口保留。授权经销商前后台共用 `agent-query-api`。
- `config/projects.local.yaml` 只在本机更新，不入库；可用 `python3 scripts/sync-flow-menus.py` 按清单与 ID 重新同步。

## 验收范围

云效 API 已回读 36 条流水线定义，源码分支、手动触发和人工卡点与入库 YAML 一致。18 个服务的 Dockerfile 已从对应 Codeup 目标分支读取核对。菜单与安全拒绝路径做了本地验证。首次云端构建与业务验收尚未进行，不能将流水线创建成功视为构建成功。

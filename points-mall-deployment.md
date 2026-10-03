# 积分商城 deploySys 部署与分支规则

2026-10-03 按主公指令设置。本规则仅修改积分商城菜单；其他项目保留原配置。

开发分支完成验证后合入 `dev` 并推送。测试部署选取最新 `origin/dev`，自动切换到 `dev`；生产部署选取 `release`，此前须人工将最新 `dev` 合入 `release`。生产命令在启动 Flow 前核验祖先关系，未合入 dev、未推送提交、分叉或无关未提交改动均拒绝发布。不自动 stash、覆盖或强推。分支已有 worktree 时使用该工作区，避免抢占其他正在使用的分支。

发布成功后，核验发布 SHA、远端 release/dev/master 未发生冲突性变化，再以快进方式收口 master 并核验 0/0。生产镜像必须与当前 release SHA 相同。开发者需提前将本次所有已完成分支合入 dev；工具会报告仍未进入 master 的历史或未完成分支，不在发布时临时混入未验收代码。

## 测试 API

在 deploySys 选择“积分商城 → 后端前台 API / 后端后台服务 → test → run”。

| 服务 | 服务器 | 端口 | 目录 | systemd |
| --- | --- | --- | --- | --- |
| 前台 API | 172.27.182.78 | 3090 | /home/publish/jifen90/api_front | jifen90.api |
| 后台 API | 172.27.182.78 | 3091 | /home/publish/jifen90/api_back | jifen90.admin |

发布入口调用 dev 源码内既有部署脚本，生成仅含非敏感连接元数据的临时部署环境文件，密码只从主公授权的本机 `depoy/dev-ecs.md` 在进程内取得，不写入菜单、日志或持久文件。需要本机 dotnet、rsync、ssh、sshpass 和已确认的 SSH known_hosts。程序替换保留服务器既有配置，默认不清理备份。部署前核验现有服务目录及 3090/3091，部署后检查 `/health/ready`。3040/3041 不使用。

`points-mall-test-api.py front|back --check` 仅显示非敏感目标，不验证服务器在线状态。修改菜单不是本次重新发布证据。

## 生产入口核对

2026-10-03 通过 aliyun devops GetPipeline 与 ListPipelines 只读核对：

- 后台 API：构建 5300570，人工确认 5300571；云端源码分支 release。
- Worker：构建 5300572，人工确认 5300573；云端源码分支 release。
- 实际路径为本机启动云效 Flow 构建、固定 digest 人工确认，随后本机脚本更新 ACS 镜像，不是全部步骤都在流水线内执行。
- 本组织 38 条流水线清单及本地登记中没有积分商城前台 API Flow。旧 api-front/prod 菜单使用 ECS 私有发布脚本且要求过期分支名，已改为明确拒绝入口，须先完成前台 API Flow 登记/迁移再开放。
- 后台 OSS、小程序上传保留既有发布方式；不将这些入口称为 Flow。
- 测试 Worker、OSS、小程序未安装/发布/联调；保留原入口并增加分支准备，不代表对应环境已可用。

本次没有调用 StartPipelineRun、PassPipelineValidate、UpdatePipeline、ACS 镜像更新、生产 SSH 或真实渠道。

## 菜单设置与验证

`python3 scripts/configure-points-mall-branches.py --tool-root /Volumes/SSD/work/deploy-sys --script-root <本次脚本所在工具工作区>` 通过 ConfigStore 版本锁、备份、原子写入只更新 jifen 项目。重复设置不叠加包装。共享工具目录存在其他项目未提交改动期间，可将 script-root 指向本次隔离工作区；保留该工作区直到菜单已切换到合入后的工具目录。

验证：`python3 -m unittest discover -s tests -p 'test_points_mall_deploy.py' -v`，12 项；`python3 -m unittest discover -s tests -p 'test_flow_release_safety.py' -q`，9 项。均仅使用合成 Git 仓库或 mock，不执行真实发布。三份新增 Python 脚本 py_compile 成功。

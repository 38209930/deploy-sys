# 售后工单部署分支与菜单

生效日期：2026-10-03。仅适用于 `service-order` 项目，不修改其他项目的 Git 或部署方式。

## 分支与执行顺序

业务开发分支经验证、提交、推送后合入并推送 `dev`。测试菜单先执行 `scripts/service-order-deploy.py`，自动切换对应仓库 `dev` 并快进到 `origin/dev`，再执行原测试发布脚本。原脚本中的 dev 检查保留。

获得对应生产发布授权后，先将本次需交付的业务分支全部合入 `dev`，再将最新 `dev` 合入 `release`。生产菜单自动切到 `release`；必须包含最新 `origin/dev`，且能够快进收口 `origin/master`。本地 dev/master 未推送、工作树有未提交/未跟踪文件、detached HEAD 或目标分支分叉都会停止，不自动 stash/reset、强推或合并未知分支。

API 的推送菜单允许本地 release 比远端领先，用于推送已人工合入的 dev；构建/部署菜单要求 release 与远端一致。生产静态发布没有独立推送菜单，必须先自行推送已准备好的 release。

## 现有生产链路

API 保留 `scripts/flow-release.sh`：推送 release → 启动阿里云 Flow 构建 → 查询构建结果与 ACR 固定 digest → 启动确认流水线 → 等待人工确认 → 本机 ACS 更新与滚动验证。构建成功和等待确认均不等于发布完成。

| 服务 | 构建流水线 | 确认流水线 | 构建分支 |
| --- | --- | --- | --- |
| Front | 5300574 | 5300575 | release |
| Admin API（back） | 5300576 | 5300577 | release |
| Worker | 5300578 | 5300579 | release |

2026-10-03 使用 `GetPipeline` 独立只读查询六条云端配置成功，三条构建源分支均为 release。仓库内模板声明 `triggerEvents: []`；本次云端返回的源字段含 `triggerFilter: .*`，settings 未返回自动触发开关，故未据此断言云端 release 推送触发已禁用。生产授权前仍需由云效负责人确认该触发边界；不通过实际推送探测。

Admin PC/H5 仍使用既有生产 OSS 静态发布脚本，本次没有把它们改成 API 流水线。

## 发布后主干收口

Flow 上线前核对本地待发布状态的 `source_commit` 等于当前 release；不同则停止，要求重新构建。`flow-release.sh` 在确认、失败重试、成功状态中保留源码提交。

API 三个服务的状态均为 `DEPLOY_SUCCESS` 且绑定同一个 release 提交后，才将 API 仓 release 快进合入并推送 master。单服务成功会提示等待其余服务，不冒称全仓发布完成。PC/H5 各自在原静态发布脚本成功后收口对应仓库 master。

收口前重新 fetch，若 release/dev/master 在发布期间变化而不再满足已发布版本的关系，停止并记录“发布完成但 master 未收口”。推送 master 后再 fetch 并核验 0/0，最后切回 release。不得为收口重新执行已经成功的部署；失败收口由发布负责人按已保存版本证据处理。

所有应交付业务变更必须先进入 dev，master 含本次 dev/release 才能覆盖这些变更。脚本不会自动判定、合并或删除所有历史业务分支，也不将不同仓库的状态冒充一套配套发布证明。

## 菜单设置与维护

实际菜单位于忽略的 `config/projects.local.yaml`。执行以下命令仅设置菜单，不执行部署：

```bash
cd /Volumes/SSD/work/deploy-sys
python3 scripts/configure-service-order-branches.py
```

脚本通过既有 ConfigStore 的版本冲突保护、备份和原子写入，只包装售后 16 个目标：API 三服务的推送/构建/上线共 9 个，测试 API/Worker/PC/H5 共 5 个，生产 PC/H5 共 2 个。状态、日志、其他项目及原有确认参数保持。兼容两条命令或单个多行命令块；入口结构/数量变化停止，不猜测替换。

CLI 和本地浏览器客户端都执行持久化的原命令块。刷新配置并重新选择目标后执行；不要在命令预览中覆盖掉包装入口。脚本、测试与本文纳入 Git；私有菜单与自动备份不提交。

当前仅授权测试交付及菜单设置：本次未执行任何部署，售后三仓 release/master/freeze 仍冻结。未来菜单具备生产能力不构成本次生产发布授权。

## 直接相关验证

```bash
python3 -m unittest discover -s tests -p 'test_service_order_deploy.py'
python3 -m unittest discover -s tests -p 'test_flow_release_safety.py'
python3 -m unittest discover -s tests -p 'test_deploysys.py' -k ConfigStoreTests
python3 -m py_compile scripts/service-order-deploy.py scripts/configure-service-order-branches.py
bash -n scripts/flow-release.sh
```

使用临时 bare Git 仓库、合成数据和流水线替身；不启动真实流水线或访问业务数据库。覆盖分支切换、落后快进、未推送/分叉保护、release 包含 dev、失败/等待状态、同源码三服务收口、发布期间分支变化，以及源提交跨确认失败重试保留。

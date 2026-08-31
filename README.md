# deploy-sys

`deploy-sys` 是一个轻量部署运维工具，用来把多个项目、多个子任务服务的常用命令集中保存，并通过终端菜单或本地浏览器客户端执行。

它不接管 CI/CD，不维护服务器配置，也不要求你把部署流程拆成固定字段。你输入原始命令，工具负责保存、展示、执行和记录日志。

## Features

- 项目、子任务、执行目标三层管理：`project -> service -> target`
- 每个执行目标保存一组原始命令，支持粘贴多行命令
- 执行目标名称可自定义，例如 `默认`、`test`、`prod`、`local`
- 多行命令在同一个 shell 会话运行，`cd`、`export` 等上下文会保留到下一行
- 状态检查命令按执行目标单独保存，可直接粘贴多行命令
- 本地浏览器客户端支持点击项目、服务、执行目标后直接执行
- 本地浏览器客户端支持直接编辑命令预览并保存
- 本地浏览器客户端新增服务时可一次填写服务 ID、执行目标和执行命令
- 本地浏览器客户端新增执行目标时可一次填写目标名称和执行命令
- 本地浏览器客户端只监听 `127.0.0.1`，避免 Tk 原生控件在 macOS 上卡死
- 命令编辑后必须保存才可执行，切换或刷新会提示未保存内容
- 全局同一时间只执行一个任务，可在页面内取消
- 本地浏览器客户端日志采用分块刷新并限制页面保留量，避免长输出导致界面卡顿
- 执行日志本地保存，并对疑似敏感值做脱敏
- 可查看项目完整配置和配置文件路径，并可编辑或删除项目、服务、执行目标
- 保存采用原子写入、版本冲突保护和本地备份，避免多窗口覆盖配置

## Install

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

## Usage

终端版：

```bash
python3 deploysys.py
```

本地浏览器客户端：

```bash
python3 deploysys_gui.py
```

mac 也可以直接双击，启动后会自动打开浏览器：

```text
deploysys_gui.command
```

Windows 可以双击：

```text
deploysys_gui.cmd
```

首次启动会自动生成：

- `config/projects.yaml`
- `config/settings.yaml`
- `.gitignore`
- `logs/`
- `data/`

首次保存项目后生成 `config/projects.local.yaml`；真实项目配置始终写入该私有文件。

首页菜单：

```text
1. 选择项目
2. 新增项目
0. 退出
```

选择项目后进入当前项目菜单：

```text
1. 执行服务命令
2. 服务状态检查
3. 新增服务
4. 查看项目配置
5. 删除已录入内容
0. 返回项目列表
```

终端导航按 `首页 -> 项目列表 -> 当前项目菜单 -> 服务 -> 执行目标 -> 操作` 逐级进入；所有编号菜单都可以输入 `0` 返回上一级。执行命令或状态检查结束后，会回到当前项目菜单，不会跳回首页。新增服务、删除服务或删除命令后仍停留在当前项目；删除整个项目后返回项目列表。

表单和多行命令录入中，输入 `:back` 可取消当前录入。命令输入仍以空行结束，部署命令按录入顺序保存在同一命令块里执行。

## Data Model

录入模型保持简单：

- 项目：例如 `demo-platform`
- 子任务服务：例如 `front-api`、`back-api`、`web-admin`
- 执行目标：例如 `默认`、`test`、`prod`，名称可自定义
- 命令：每个执行目标保存一组多行原始命令，并在同一个 shell 中按顺序执行

系统不会要求你输入 `local/ssh`、`host`、`workdir`、端口、Health URL、密钥名，也不会要求你把命令拆成 `build/deploy/start/stop`。命令怎么执行，由你粘贴的原始命令决定。

本地浏览器客户端里：

- 点“新增服务”时，可以一次填写服务 ID、服务名称、执行目标和执行命令。
- 选中某个服务后点“新增执行目标”时，可以一次填写执行目标和执行命令。
- 状态检查使用独立页签；首次录入可直接粘贴多行，不会弹出单行输入框。
- 命令输入框支持直接粘贴多行命令，保存后会自动重新加载并保留选中项。

## Example Config

`config/projects.yaml` 示例：

```yaml
schema_version: 2
revision: 1
projects:
  - id: demo-platform
    name: Demo Platform
    type: other
    platform: mac
    services:
      - id: front-api
        name: Front API
        type: dotnet
        targets:
          test:
            shell: auto
            commands:
              run:
                - cd /path/to/demo/front-api
                - ENV_FILE=config/env.test.example bash scripts/deploy-front-api.sh
          prod:
            commands:
              run:
                - cd /path/to/demo/front-api
                - ENV_FILE=config/env.prod.example bash scripts/deploy-front-api.sh
            status_commands:
              - cd /path/to/demo/front-api
              - bash scripts/check-front-api.sh
```

命令录入示例。部署成功后的本地清理由最后一行明确命令完成；工具不会根据输出自动删除目录：

```text
命令[1]: cd /path/to/demo/front-api
命令[2]: ENV_FILE=config/env.prod.example bash scripts/deploy-front-api.sh
命令[3]: your-existing-cleanup-command
```

浏览器客户端可以一次粘贴完整命令块。终端兼容入口可逐行粘贴或一次粘贴多行，仍以空行结束录入。

## Safety Notes

- `config/projects.yaml` 是公开模板，默认保持 `projects: []`。
- 本机真实项目配置写入 `config/projects.local.yaml`，该文件默认不会提交到 Git。
- `config/secrets*`、`logs/`、`data/operation_logs.jsonl`、`data/config-backups/` 默认不会提交到 Git。
- 配置损坏时会保留原文件并尝试恢复最近一次有效备份；版本冲突不会静默覆盖另一个窗口的数据。
- 不要把真实密码、Token、证书、私钥写进公开配置或 README。
- 如果命令里必须使用密钥，建议从本机环境变量、私有配置文件或部署脚本内部读取。
- 公开仓库只应保留示例路径，例如 `/path/to/demo/app`。

## Test

```bash
python3 -m unittest discover -s tests
python3 -m py_compile deploysys.py deploysys_gui.py tests/test_deploysys.py
```

## DDMP 同源 Java API 发布

`scripts/deploy-ddmp-family-api.sh` 用于 DDMP 同源 Java API 的本机受控发布。它固定从本机 `release` 分支构建，不依赖服务器源码目录或历史 `de-api-test.sh`。

发布流程包含以下门禁：

- 本机仓库必须干净，且 `HEAD` 与 `origin/release` 完全一致。
- 使用 JDK 8 执行 Maven 完整测试和打包。
- 新 jar 先上传为唯一临时文件，并核对本地与服务器 SHA-256。
- 只允许存在一个目标 Java 进程；目标端口若被其他进程占用则拒绝发布。
- 使用 `TERM` 等待旧进程退出，不执行强制终止。
- 原 jar 保存到服务器 `backups/` 后再原子替换；新进程验收失败时自动恢复备份。
- 启动参数固定使用 `prod`，端口沿用应用现有配置；验收同时检查进程数、端口归属、HTTP 响应和运行 jar SHA-256。

真实仓库路径、SSH 配置入口和公网探测地址保存在忽略提交的 `config/projects.local.yaml`，不写入公开配置。deploySys 中分别选择对应项目的 `API -> prod` 执行发布，使用“状态检查”做只读验收。

# deploy-sys

`deploy-sys` 是一个轻量终端部署运维 CLI，用来把多个项目、多个子任务服务的常用命令集中保存，并通过菜单选择后执行。

它不接管 CI/CD，不维护服务器配置，也不要求你把部署流程拆成固定字段。你输入原始命令，工具负责保存、展示、执行和记录日志。

## Features

- 项目、子任务、环境三层管理：`project -> service -> test/prod`
- 每个环境保存一组原始命令，支持粘贴多行命令
- 状态检查命令按环境单独保存，首次使用时引导录入
- 生产环境执行前要求确认词
- 执行日志本地保存，并对疑似敏感值做脱敏
- 可查看项目配置和配置文件路径
- 可删除项目、子任务或环境下保存的命令

## Install

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

## Usage

```bash
python3 deploysys.py
```

首次启动会自动生成：

- `config/projects.yaml`
- `config/settings.yaml`
- `config/secrets.enc`
- `.gitignore`
- `logs/`
- `data/`

首页菜单：

```text
1. 项目部署/服务操作
2. 服务状态检查
3. 新增项目
4. 查看项目配置
5. 删除已录入内容
0. 退出
```

## Data Model

录入模型保持简单：

- 项目：例如 `demo-platform`
- 子任务服务：例如 `front-api`、`back-api`、`web-admin`
- 环境：固定为 `test` 和 `prod`
- 命令：每个环境保存一组多行原始命令

系统不会要求你输入 `local/ssh`、`host`、`workdir`、端口、Health URL、密钥名，也不会要求你把命令拆成 `build/deploy/start/stop`。命令怎么执行，由你粘贴的原始命令决定。

## Example Config

`config/projects.yaml` 示例：

```yaml
projects:
  - id: demo-platform
    name: Demo Platform
    type: other
    services:
      - id: front-api
        name: Front API
        type: dotnet
        environments:
          test:
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

命令录入示例：

```text
命令[1]: cd /path/to/demo/front-api
命令[2]: ENV_FILE=config/env.prod.example bash scripts/deploy-front-api.sh
命令[3]:
```

看到空白的下一行提示时，直接回车结束录入。

## Safety Notes

- `config/secrets*`、`logs/`、`data/operation_logs.jsonl` 默认不会提交到 Git。
- 不要把真实密码、Token、证书、私钥写进公开配置或 README。
- 如果命令里必须使用密钥，建议从本机环境变量、私有配置文件或部署脚本内部读取。
- 公开仓库只应保留示例路径，例如 `/path/to/demo/app`。

## Test

```bash
python3 -m unittest discover -s tests
python3 -m py_compile deploysys.py tests/test_deploysys.py
```

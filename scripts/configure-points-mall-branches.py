#!/usr/bin/env python3
"""通过 ConfigStore 精确更新积分商城菜单，保留其他项目及状态命令。"""
import argparse
from pathlib import Path
import shlex
import sys

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE))
from deploysys_store import ConfigStore, ConfigError

WORKSPACE = Path('/Volumes/SSD/work/mall/积分商城')


def update_menu(data, tool_root, script_root):
    projects = [p for p in data['projects'] if p.get('id') == 'jifen']
    if len(projects) != 1:
        raise ConfigError('未找到唯一的积分商城项目')
    wrapper = shlex.quote(str(script_root / 'scripts/points-mall-deploy.py'))
    q = shlex.quote
    for service in projects[0]['services']:
        sid = service['id']
        if sid.startswith('flow-points-mall-') and sid.rsplit('-', 1)[-1] in ('push', 'build', 'deploy'):
            action = sid.rsplit('-', 1)[-1]
            target = service['targets']['prod']
            lines = target['commands']['run']
            if any('points-mall-deploy.py' in line for line in lines):
                continue
            if len(lines) != 2 or ' bash scripts/flow-release.sh ' not in lines[-1]:
                raise ConfigError('Flow 菜单结构变化：' + sid)
            env, command = lines[-1].split(' bash scripts/flow-release.sh ', 1)
            lines[-1] = (env + f' FLOW_STATE_DIR={q(str(tool_root / "data/flow-state"))} python3 {wrapper}'
                         f' --command-dir {q(str(tool_root))} prod {q(str(WORKSPACE / "jifen-api"))} {action}'
                         f' -- bash scripts/flow-release.sh {command}')
        elif sid in ('api-front', 'api-back'):
            role = 'front' if sid == 'api-front' else 'back'
            target = service['targets'].get('test')
            if target:
                target['commands']['run'] = [f'python3 {wrapper} test {q(str(WORKSPACE / "jifen-api"))} deploy --'
                    f' python3 {q(str(script_root / "scripts/points-mall-test-api.py"))} {role}']
                target['status_commands'] = [f'python3 {q(str(script_root / "scripts/points-mall-test-api.py"))} {role} --check']
            if sid == 'api-front' and 'prod' in service['targets']:
                service['targets']['prod']['commands']['run'] = [
                    "echo '停止：前台 API 尚未登记可核验的阿里云 Flow 流水线；旧 ECS 生产发布入口停用，请先完成流水线迁移。' >&2", 'exit 1']
        elif sid in ('worker', 'admin-oss', 'miniapp'):
            repo = WORKSPACE / ('jifen-miniapp' if sid == 'miniapp' else 'jifen-admin' if sid == 'admin-oss' else 'jifen-api')
            for environment, target in service['targets'].items():
                if environment not in ('test', 'prod'):
                    continue
                lines = target['commands']['run']
                if any('points-mall-deploy.py' in line for line in lines):
                    continue
                # 保留部署命令原文及私有路径。后台 OSS 构建脚本在 API 仓运行，
                # 单独准备 admin 源分支后再准备 API 脚本分支。
                if len(lines) != 2 or not lines[0].startswith('cd '):
                    raise ConfigError('部署菜单结构变化：' + sid)
                command = lines[-1]
                if 'DEPLOY_ENV_FILE=scripts/deploy/' in command:
                    command = command.replace('DEPLOY_ENV_FILE=scripts/deploy/', 'DEPLOY_ENV_FILE=' + str(WORKSPACE / 'jifen-api/scripts/deploy') + '/')
                    # 带中文路径仍通过整个 shell 命令参数安全传入。
                original = 'cd "$POINTS_MALL_SOURCE_DIR"\n' + command
                related = f' --related-repo {q(str(repo))}' if sid == 'admin-oss' else ''
                source = WORKSPACE / 'jifen-api' if sid == 'admin-oss' else repo
                lines = [f'python3 {wrapper}{related} {environment} {q(str(source))} deploy -- bash -eu -c {q(original)}']
                target['commands']['run'] = lines


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tool-root', type=Path, default=SOURCE)
    p.add_argument('--script-root', type=Path, default=SOURCE)
    a = p.parse_args()
    store = ConfigStore(a.tool_root / 'config/projects.local.yaml', a.tool_root / 'config/projects.yaml', a.tool_root / 'data/config-backups')
    snapshot = store.load()
    updated = store.mutate(snapshot.revision, lambda data: update_menu(data, a.tool_root, a.script_root))
    print('积分商城菜单已更新，revision=' + str(updated.revision))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""只更新售后工单部署菜单的分支准备和发布后收口命令。"""
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deploysys_store import ConfigStore, ConfigError

WORKSPACE = Path('/Volumes/SSD/work/mall/售后工单系统')
WRAPPER = ROOT / 'scripts/service-order-deploy.py'
TEST_RUNTIME_STATUS = (
    'cd ' + shlex.quote(str(WORKSPACE)) + '\n'
    + 'bash ' + shlex.quote(str(WORKSPACE / 'service-order-api/scripts/deploy/migrate-test-runtime-config.sh'))
    + ' status'
)


def update_menu(data):
    projects = [p for p in data['projects'] if p.get('id') == 'service-order']
    if len(projects) != 1:
        raise ConfigError('未找到唯一的售后工单项目')
    count = 0
    for service in projects[0]['services']:
        sid = service['id']
        # 测试菜单必须展示实际远端运行态，不能只保留部署命令。
        # 该脚本只输出服务、环境、配置文件存在性、端口和健康检查摘要，
        # 不读取或输出任何配置值、密码或密钥。
        if sid in ('api-front', 'api-back', 'worker') and 'test' in service['targets']:
            service['targets']['test']['status_commands'] = [TEST_RUNTIME_STATUS]
        if sid.startswith('flow-service-order-') and sid.rsplit('-', 1)[-1] in ('push', 'build', 'deploy'):
            action = sid.rsplit('-', 1)[-1]
            repo = WORKSPACE / 'service-order-api'
            env = 'prod'
            targets = ['prod']
        elif sid in ('api-front', 'api-back', 'worker', 'admin-pc', 'h5-oss'):
            repo = WORKSPACE / ('service-order-admin' if sid == 'admin-pc' else 'service-orderr-miniapp' if sid == 'h5-oss' else 'service-order-api')
            action = 'deploy'
            targets = [t for t in service['targets'] if t in ('test', 'prod')]
        else:
            continue
        for target in targets:
            env = target
            lines = service['targets'][target]['commands']['run']
            # 支持两条命令或单个多行命令块；保留原块结构、其他服务和确认参数。
            if any('service-order-deploy.py' in line for line in lines):
                continue
            physical = [line for block in lines for line in block.splitlines()]
            if len(physical) != 2 or 'bash scripts/' not in physical[-1]:
                raise ConfigError('菜单命令结构变化，停止：' + sid + '/' + target)
            before, command = physical[-1].split('bash scripts/', 1)
            expected = 'flow-release.sh' if sid.startswith('flow-service-order-') else 'deploy-'
            if not command.startswith(expected):
                raise ConfigError('部署入口不符合预期：' + sid)
            if sid.startswith('flow-service-order-') and 'FLOW_RELEASE_BRANCH=' in before and 'FLOW_RELEASE_BRANCH=release ' not in before:
                raise ConfigError('Flow源分支不是release：' + sid)
            wrapped = before + 'python3 ' + shlex.quote(str(WRAPPER)) + ' ' + env + ' ' + shlex.quote(str(repo)) + ' ' + action + ' -- bash scripts/' + command
            lines[-1] = lines[-1].removesuffix(physical[-1]) + wrapped
            count += 1
    if count not in (0, 16):
        raise ConfigError('菜单数量变化，停止；预期16，实际' + str(count))


def main():
    store = ConfigStore(ROOT / 'config/projects.local.yaml', ROOT / 'config/projects.yaml', ROOT / 'data/config-backups')
    snapshot = store.load()
    updated = store.mutate(snapshot.revision, update_menu)
    print('售后工单部署菜单已更新，revision=' + str(updated.revision))


if __name__ == '__main__':
    main()

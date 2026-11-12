#!/usr/bin/env python3
"""幂等补齐 Yangu 三个前端的 OSS 菜单，保留项目已有服务。"""
from pathlib import Path
import copy
import shlex
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deploysys_store import ConfigStore, ConfigError

REPO = '/Volumes/SSD/work/ddmp/prod/yangu-prod/yangu-manage'
NODE_DIR = '/Users/chaofengsong/.nvm/versions/node/v14.21.3/bin'


def update_menu(data):
    matches = [p for p in data['projects'] if p['id'] == 'yangu']
    if len(matches) != 1:
        raise ConfigError('未找到唯一 Yangu 项目')
    services = matches[0]['services']
    command = 'env PATH=' + NODE_DIR + ':$PATH NODE_OPTIONS= ' + shlex.quote(NODE_DIR + '/node') + ' ' + shlex.quote(str(ROOT / 'scripts/yangu-manage-oss-release.js'))
    service = {'id': 'manage-oss', 'name': 'Yangu 管理端生产 OSS', 'type': 'vue2', 'targets': {
        'prod': {'shell': 'bash', 'commands': {'run': [
            'cd ' + shlex.quote(REPO),
            'env PATH=' + NODE_DIR + ':$PATH NODE_OPTIONS= npm run build:prod',
            'YANGU_OSS_CONFIRM=yes ' + command + ' deploy',
        ]}, 'status_commands': [command + ' status']}}}
    requested = [service]
    for frontend, directory, label in [('manage', 'yangu-manage', '管理端'), ('exam', 'yan-exam', 'exam 前端'), ('train', 'yangu-train', 'train 前端')]:
        environments = ['test'] if frontend == 'manage' else ['test', 'prod']
        targets = {}
        for environment in environments:
            invocation = command + ' deploy - ' + frontend + ' ' + environment
            targets[environment] = {
                'shell': 'bash',
                'commands': {'run': [
                    'cd ' + shlex.quote(str(Path(REPO).parent / directory)),
                    'env PATH=' + NODE_DIR + ':$PATH NODE_OPTIONS= npm run build:prod' + (' -- --mode staging' if environment == 'test' else ''),
                    'YANGU_OSS_CONFIRM=yes ' + invocation,
                ]},
                'status_commands': [command + ' status - ' + frontend + ' ' + environment],
            }
        requested.append({'id': frontend + '-test-oss' if frontend == 'manage' else frontend + '-oss',
                          'name': 'Yangu ' + label + ' OSS', 'type': 'vue2', 'targets': targets})
    for service in requested:
        current = [item for item in services if item['id'] == service['id']]
        if len(current) > 1:
            raise ConfigError('菜单重复')
        if current and current[0] != service:
            raise ConfigError('已有不同配置，请核对')
        if not current:
            services.append(service)


if __name__ == '__main__':
    store = ConfigStore(ROOT / 'config/projects.local.yaml', ROOT / 'config/projects.yaml', ROOT / 'data/config-backups')
    snapshot = store.load()
    expected = copy.deepcopy(snapshot.data)
    update_menu(expected)
    result = store.mutate(snapshot.revision, update_menu)
    assert result.data['projects'] == expected['projects']
    print('Yangu 三个前端 OSS 菜单已注册，revision=' + str(result.revision))

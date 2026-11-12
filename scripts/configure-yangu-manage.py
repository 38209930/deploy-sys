#!/usr/bin/env python3
"""幂等补齐 Yangu 管理端生产 OSS 菜单，保留项目已有服务。"""
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
    current = [s for s in services if s['id'] == service['id']]
    if len(current) > 1:
        raise ConfigError('管理端菜单重复')
    if current:
        if current[0] != service:
            raise ConfigError('管理端已有不同配置，请人工核对')
    else:
        services.append(service)


if __name__ == '__main__':
    store = ConfigStore(ROOT / 'config/projects.local.yaml', ROOT / 'config/projects.yaml', ROOT / 'data/config-backups')
    snapshot = store.load()
    expected = copy.deepcopy(snapshot.data)
    update_menu(expected)
    result = store.mutate(snapshot.revision, update_menu)
    assert result.data['projects'] == expected['projects']
    print('Yangu → Yangu 管理端生产 OSS → prod 已注册，revision=' + str(result.revision))

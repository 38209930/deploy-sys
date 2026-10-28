#!/usr/bin/env python3
"""将 M1X 测试 API 和两个 OSS 测试目标写入 deploySys 私有菜单。"""
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deploysys_store import ConfigStore, ConfigError

WORKSPACE = Path('/Volumes/SSD/work/ddmp/prod/stopmp/M1-X')


def api_command(action):
    return ['python3 ' + shlex.quote(str(ROOT / 'scripts/m1x-test-api.py')) + ' ' + action]


def update_menu(data):
    projects = [p for p in data['projects'] if p['id'] == 'm1x']
    if len(projects) != 1:
        raise ConfigError('未找到唯一 M1X 项目')
    services = projects[0]['services']
    # 先核对两个既有前端，避免部分菜单写入。
    fronts = {}
    for sid in ('manage-oss', 'exam-oss'):
        matches = [s for s in services if s['id'] == sid]
        if len(matches) != 1:
            raise ConfigError('未找到唯一前端服务：' + sid)
        fronts[sid] = matches[0]
    targets = {'test': {'shell': 'bash', 'release_required': False,
                        'commands': {'run': api_command('deploy'), 'restart': api_command('restart')},
                        'status_commands': api_command('status')}}
    matches = [s for s in services if s['id'] == 'm1x-api-test']
    if len(matches) > 1:
        raise ConfigError('测试 API 菜单重复')
    if matches:
        matches[0].setdefault('targets', {}).update(targets)
    else:
        services.append({'id': 'm1x-api-test', 'name': 'M1X API 测试环境', 'type': 'java', 'targets': targets})
    for sid, repo, bucket, domain in [
        ('manage-oss', 'm1x-pc', 'm1x-manage-test', 'm1x-man-test.svision100.com'),
        ('exam-oss', 'm1x-exam', 'm1x-exam-test', 'm1x-exam-test.svision100.com'),
    ]:
        fronts[sid]['targets']['test'] = {
            'shell': 'bash', 'release_required': False,
            'commands': {'run': ['cd ' + shlex.quote(str(WORKSPACE / repo)),
                "M1X_OSS_BUCKET=" + bucket + " M1X_OSS_DOMAIN=https://" + domain
                + " M1X_OSS_BUILD_COMMAND='npm run build:test' npm run deploy:oss"]},
            'status_commands': ['curl --fail --silent --show-error --connect-timeout 5 --max-time 15 '
                                + 'https://' + domain + '/index.html >/dev/null'],
        }


def main():
    store = ConfigStore(ROOT / 'config/projects.local.yaml', ROOT / 'config/projects.yaml', ROOT / 'data/config-backups')
    snapshot = store.load()
    updated = store.mutate(snapshot.revision, update_menu)
    print('M1X 测试目标已加入，revision=' + str(updated.revision))


if __name__ == '__main__':
    main()

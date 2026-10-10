#!/usr/bin/env python3
"""精确补充本机 ECS 测试重启与 ACS 重新部署菜单，保留原发布命令。"""
import argparse
from pathlib import Path
import shlex
import sys
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deploysys_store import ConfigStore

ECS = {
    ('yangu', 'yangu-api-ecs-test-deploy'): 'yangu-api',
    ('newsale', 'newsale-test-front'): 'newsale-front',
    ('newsale', 'newsale-test-back'): 'newsale-back',
    ('jifen', 'worker'): 'points-mall-worker',
    ('service-order', 'api-front'): 'service-order-front',
    ('service-order', 'api-back'): 'service-order-back',
    ('service-order', 'worker'): 'service-order-worker',
    ('ai-study-room', 'API-front'): 'ai-study-front',
    ('ai-study-room', 'API-BACK'): 'ai-study-back',
    ('ai-study-room', 'work-service'): 'ai-study-worker',
}
OLD_ROOTS = ('/Volumes/SSD/work/deploy-sys-points-mall-delivery', '/Volumes/SSD/work/deploy-sys-points-mall')


def update_menu(data, rows, root=ROOT):
    q = shlex.quote
    rows = {f"flow-{row['id']}-release": row for row in rows}
    changed = 0
    for project in data['projects']:
        services = {service['id']: service for service in project.get('services', [])}
        for sid, service in services.items():
            row = rows.get(sid)
            if row and 'prod' in service.get('targets', {}):
                target = service['targets']['prod']
                if row['replicas'] > 0:
                    flags = dict(namespace=row['namespace'], deployment=row['deployment'],
                                 container=row['container'], expected_replicas=row['replicas'])
                    target.setdefault('commands', {})['restart'] = [
                        f'python3 {q(str(root / "scripts/acs-image-deploy.py"))} --restart ' +
                        ' '.join(f'--{key.replace("_", "-")} {q(str(value))}' for key, value in flags.items())]
                    changed += 1
                else:
                    target.setdefault('commands', {}).pop('restart', None)
                continue
            target = service.get('targets', {}).get('test')
            if not target:
                continue
            profile = ECS.get((project['id'], sid))
            if profile:
                target.setdefault('commands', {})['restart'] = [
                    f'python3 {q(str(root / "scripts/ecs-test-restart.py"))} {profile}']
                changed += 1
            elif project['id'] == 'jifen' and sid in ('api-front', 'api-back'):
                role = 'front' if sid == 'api-front' else 'back'
                target.setdefault('commands', {})['restart'] = [
                    f'python3 {q(str(root / "scripts/points-mall-test-api.py"))} {role} --restart']
                # 清理掉的工具 worktree 曾被私有菜单写死，只修复这些已知路径。
                for key in ('run', 'restart'):
                    target['commands'][key] = [repair_root(line, root) for line in target['commands'].get(key, [])]
                target['status_commands'] = [repair_root(line, root) for line in target.get('status_commands', [])]
                changed += 1
            elif project['id'] == 'apollo' and sid in ('api-front', 'api-back', 'worker'):
                existing = services.get(sid + '-restart', {}).get('targets', {}).get('test', {})
                commands = existing.get('commands', {}).get('run')
                if commands:
                    target.setdefault('commands', {})['restart'] = list(commands)
                    changed += 1
    return changed


def repair_root(line, root):
    for old in OLD_ROOTS:
        line = line.replace(old + '/', str(root) + '/')
    return line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.tool_root.resolve()
    rows = yaml.safe_load((root / 'deployment/flow/services.yaml').read_text())['services']
    store = ConfigStore(root / 'config/projects.local.yaml', root / 'config/projects.yaml', root / 'data/config-backups')
    snapshot = store.load()
    counts = []
    updated = store.mutate(snapshot.revision, lambda data: counts.append(update_menu(data, rows, root)))
    print(f'已配置 {counts[0]} 个服务的重启操作，revision={updated.revision}')


if __name__ == '__main__':
    main()

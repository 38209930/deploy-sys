#!/usr/bin/env python3
"""只在 deploySys 的 Apollo 项目中安装后台前端合并分支菜单。"""

from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import deploysys


def main():
    store = deploysys.projects_store()
    snapshot = store.load()
    menu = {
        'id': 'admin-pc-merge',
        'name': '合并分支',
        'type': 'vue3',
        'targets': {'prod': {'shell': 'bash', 'commands': {'run': [
            f'cd {shlex.quote(str(ROOT))}',
            'python3 scripts/merge-apollo-admin.py',
        ]}}},
    }
    project = deploysys.find_project(snapshot.data, 'apollo')
    if project is None:
        raise RuntimeError('本机配置中未找到 Apollo 项目，未修改其他项目。')
    if deploysys.find_service(project, menu['id']) == menu:
        print('Apollo 合并分支菜单已是最新。')
        return

    def update(data):
        services = deploysys.find_project(data, 'apollo')['services']
        existing = next((i for i, item in enumerate(services) if item['id'] == menu['id']), None)
        if existing is not None:
            services[existing] = menu
        else:
            position = next((i + 1 for i, item in enumerate(services) if item['id'] == 'admin-pc'), len(services))
            services.insert(position, menu)

    store.mutate(snapshot.revision, update)
    print('已安装：阿波罗数据中台 → 合并分支 → prod。刷新 deploySys 页面即可看到。')


if __name__ == '__main__':
    main()

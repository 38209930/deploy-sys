#!/usr/bin/env python3
"""Apollo 后台前端分支集成；仅操作 Git 和本地构建，不发布 OSS。"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


DEFAULT_REPO = Path('/Volumes/SSD/work/mall/apollo/prod/pc')


def run(repo, *args, capture=False):
    result = subprocess.run(args, cwd=repo, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def git(repo, *args):
    return run(repo, 'git', *args, capture=True)


def require_clean(repo):
    if git(repo, 'status', '--porcelain'):
        raise RuntimeError('工作区存在未提交改动，请先提交或自行整理；不会自动 stash。')


def integrate(repo):
    repo = repo.resolve()
    require_clean(repo)
    branch = git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if branch == 'master':
        raise RuntimeError('请切换到待发布开发分支或 release，再执行合并分支。')
    original_head = git(repo, 'rev-parse', 'HEAD')
    remote = git(repo, 'remote', 'get-url', 'origin')
    identity = {key: git(repo, 'config', key) for key in ('user.name', 'user.email')}
    branches = list(dict.fromkeys(['master', 'release', branch]))

    with tempfile.TemporaryDirectory(prefix='apollo-admin-merge-') as directory:
        work = Path(directory)
        run(work, 'git', 'init', '--quiet')
        for key, value in identity.items():
            run(work, 'git', 'config', key, value)
        run(work, 'git', 'remote', 'add', 'origin', remote)
        # 新开发分支可以尚未推送，但 release 和 master 必须已存在。
        existing = git(work, 'ls-remote', '--heads', 'origin', *['refs/heads/' + b for b in branches])
        snapshot = {line.split()[1]: line.split()[0] for line in existing.splitlines()}
        for required in ('master', 'release'):
            if 'refs/heads/' + required not in snapshot:
                raise RuntimeError(f'远端缺少 {required}，请先核对项目分支约定。')
        refs = [f'+refs/heads/{b}:refs/remotes/origin/{b}'
                for b in branches if 'refs/heads/' + b in snapshot]
        run(work, 'git', 'fetch', 'origin', *refs)
        # 以 fetch 后的提交作为并发检查基线。
        snapshot = {'refs/heads/' + b: git(work, 'rev-parse', 'origin/' + b)
                    for b in branches if 'refs/heads/' + b in snapshot}
        run(work, 'git', 'fetch', str(repo), f'refs/heads/{branch}:refs/remotes/pending/source')
        if git(work, 'rev-parse', 'refs/remotes/pending/source') != original_head:
            raise RuntimeError('本地待发布分支已变化，请重新执行。')
        run(work, 'git', 'checkout', '-b', 'admin-integration-source', original_head)
        if 'refs/heads/' + branch in snapshot:
            run(work, 'git', 'merge', '--no-edit', 'origin/' + branch)
        print(f'待发布分支：{branch}；合入最新 origin/master', flush=True)
        run(work, 'git', 'merge', '--no-edit', 'origin/master')
        run(work, 'npm', 'ci', '--no-audit', '--no-fund')
        run(work, 'npm', 'run', 'build:prod')
        validated_tree = git(work, 'rev-parse', 'HEAD^{tree}')
        run(work, 'git', 'checkout', '-b', 'admin-integration-release', 'origin/release')
        run(work, 'git', 'merge', '--no-edit', 'admin-integration-source')
        if git(work, 'rev-parse', 'HEAD^{tree}') != validated_tree:
            print('release 含额外变更，验证最终集成版本。', flush=True)
            run(work, 'npm', 'ci', '--no-audit', '--no-fund')
            run(work, 'npm', 'run', 'build:prod')
        release_head = git(work, 'rev-parse', 'HEAD')
        run(work, 'git', 'checkout', '-b', 'admin-integration-master', 'origin/master')
        run(work, 'git', 'merge', '--ff-only', 'admin-integration-release')
        final_head = git(work, 'rev-parse', 'HEAD')
        latest = git(work, 'ls-remote', '--heads', 'origin', *['refs/heads/' + b for b in branches])
        latest_snapshot = {line.split()[1]: line.split()[0] for line in latest.splitlines()}
        if snapshot != latest_snapshot:
            raise RuntimeError('构建期间远端分支已更新，未推送；请重新执行以包含同事的新提交。')
        require_clean(repo)
        if git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD') != branch or git(repo, 'rev-parse', 'HEAD') != original_head:
            raise RuntimeError('本地分支或提交已变化，未推送；请重新执行。')
        # 原子推送：任何分支拒绝更新时，全部不更新；不强推。
        pushes = [f'{release_head}:refs/heads/release', f'{final_head}:refs/heads/master']
        if branch != 'release':
            pushes.append(f'{final_head}:refs/heads/{branch}')
        run(work, 'git', 'push', '--atomic', 'origin', *pushes)
        pushed = git(work, 'ls-remote', '--heads', 'origin', *['refs/heads/' + b for b in branches])
        actual = {line.split()[1]: line.split()[0] for line in pushed.splitlines()}
        if any(actual.get('refs/heads/' + b) != final_head for b in branches):
            raise RuntimeError('推送后远端已变化，请核验；不会自动再次推送。')
        require_clean(repo)
        if git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD') != branch or git(repo, 'rev-parse', 'HEAD') != original_head:
            raise RuntimeError('远端已推送，但本地分支已变化；请手工同步，未修改本地工作区。')
        run(repo, 'git', 'fetch', 'origin', *[f'+refs/heads/{b}:refs/remotes/origin/{b}' for b in branches])
        if git(repo, 'rev-parse', 'origin/' + branch) != final_head:
            raise RuntimeError('远端再次更新，请手工同步；未自动快进本地分支。')
        run(repo, 'git', 'merge', '--ff-only', 'origin/' + branch)
        print(f'合并完成：{branch} → release → master\nmaster 提交：{final_head}\n本地待发布分支已快进至该提交；未上传 OSS。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=DEFAULT_REPO)
    args = parser.parse_args()
    # 只阻止该菜单重复运行，不创建后台任务。
    common = Path(git(args.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    lock = common / 'apollo-admin-merge.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('已有 Apollo 合并任务运行；若上次被强制终止，请核验后移除 Git 目录中的 apollo-admin-merge.lock。')
    try:
        os.close(fd)
        integrate(args.repo)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'合并分支失败：{error}', file=sys.stderr)
        sys.exit(1)

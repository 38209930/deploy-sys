#!/usr/bin/env python3
"""积分商城部署：测试选 dev，生产选 release，成功发布后收口 master。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


class DeployError(RuntimeError):
    pass


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise DeployError('Git 操作失败：' + ' '.join(args[:2]))
    return r.stdout.rstrip("\n")


def ancestor(repo, older, newer):
    r = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', older, newer], capture_output=True)
    if r.returncode not in (0, 1):
        raise DeployError('无法核验分支祖先关系')
    return r.returncode == 0


def local_ref(repo, branch):
    r = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', 'refs/heads/' + branch], capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def require_clean(repo):
    # 只检查文件名，不读取本地环境差异；Git 切换仍会保护可能冲突的文件。
    allowed = {'jifen-api': 'scripts/deploy/deploy.prod.env', 'jifen-miniapp': 'env.js'}
    keep = allowed.get(Path(git(repo, 'rev-parse', '--show-toplevel')).name)
    for row in git(repo, 'status', '--porcelain', '-z').split('\0'):
        if row and not (row[:2] == ' M' and row[3:] == keep):
            raise DeployError('有未提交改动，停止；不自动 stash、回退或覆盖')
    if not git(repo, 'branch', '--show-current'):
        raise DeployError('detached HEAD，停止部署')


def checkout_for(repo, branch):
    for block in git(repo, 'worktree', 'list', '--porcelain').split('\n\n'):
        rows = block.splitlines()
        if 'branch refs/heads/' + branch in rows:
            path = Path(rows[0].removeprefix('worktree '))
            if not path.is_dir():
                raise DeployError('分支工作区不存在，请先修复 worktree 登记')
            return path
    return Path(repo)


def select(repo, branch, remote, selected):
    work = checkout_for(repo, branch)
    require_clean(work)
    if local_ref(work, branch):
        git(work, 'switch', branch)
        if selected == remote:
            git(work, 'merge', '--ff-only', 'origin/' + branch)
    else:
        git(work, 'switch', '--track', '-c', branch, 'origin/' + branch)
    if git(work, 'rev-parse', 'HEAD') != selected:
        raise DeployError('切换后的 SHA 与核验结果不符')
    return work


def prepare(repo, environment, action):
    repo = Path(repo).resolve()
    branch = 'dev' if environment == 'test' else 'release'
    refs = ['dev'] if environment == 'test' else ['dev', 'release', 'master']
    git(repo, 'fetch', '--quiet', 'origin', *[f'refs/heads/{r}:refs/remotes/origin/{r}' for r in refs])
    remote = git(repo, 'rev-parse', 'origin/' + branch)
    local = local_ref(repo, branch)
    selected = remote
    if local and not ancestor(repo, local, remote):
        if environment == 'prod' and action == 'push' and ancestor(repo, remote, local):
            selected = local
        else:
            raise DeployError(branch + ' 有未推送提交或分叉，请先合并并推送')
    if environment == 'prod':
        if not ancestor(repo, 'origin/dev', selected):
            raise DeployError('release 尚未包含最新 origin/dev，请先将 dev 合入 release')
        if not ancestor(repo, 'origin/master', selected):
            raise DeployError('release 尚未包含 master，请先经 dev/release 合入主干变更')
    work = select(repo, branch, remote, selected)
    print(f'deploy_source={branch} commit={selected} workspace={work}', flush=True)
    return work, selected


def read_state(path):
    if not path.is_file():
        raise DeployError('缺少 Flow 构建记录')
    return dict(row.split('=', 1) for row in path.read_text().splitlines() if '=' in row)


def verify_state(path, head, service):
    state = read_state(path)
    if state.get('service') != service or state.get('last_status') not in ('WAITING_CONFIRM', 'APPROVED_PENDING_DEPLOY'):
        raise DeployError('Flow 记录不属于本服务或不处于待发布状态')
    if state.get('source_commit') != head:
        raise DeployError('镜像源码 SHA 与 release 不一致，请重新构建')


def finish_master(repo, expected):
    repo = Path(repo).resolve()
    git(repo, 'fetch', '--quiet', 'origin', *[f'refs/heads/{r}:refs/remotes/origin/{r}' for r in ('dev', 'release', 'master')])
    if git(repo, 'rev-parse', 'origin/release') != expected or git(repo, 'rev-parse', 'HEAD') != expected:
        raise DeployError('发布期间 release 变化，master 未收口')
    if not ancestor(repo, 'origin/dev', expected) or not ancestor(repo, 'origin/master', expected):
        raise DeployError('发布期间 dev/master 变化，master 未收口')
    local = local_ref(repo, 'master')
    remote = git(repo, 'rev-parse', 'origin/master')
    if local and not ancestor(repo, local, remote):
        raise DeployError('本地 master 有未推送提交，master 未收口')
    master_work = select(repo, 'master', remote, remote)
    try:
        git(master_work, 'merge', '--ff-only', expected)
        git(master_work, 'push', '--quiet', 'origin', 'master')
        git(master_work, 'fetch', '--quiet', 'origin', 'refs/heads/master:refs/remotes/origin/master')
        if git(master_work, 'rev-parse', 'HEAD') != git(master_work, 'rev-parse', 'origin/master'):
            raise DeployError('master 推送回读不一致')
        print(f'master_closed={expected} ahead=0 behind=0', flush=True)
        pending = git(master_work, 'for-each-ref', '--format=%(refname:short)', '--no-merged=master', 'refs/heads')
        if pending:
            print('仍未进入 master 的历史/未完成分支（不自动混合）：' + ', '.join(pending.splitlines()), flush=True)
    finally:
        if master_work == repo:
            git(repo, 'switch', 'release')


def execute(repo, environment, action, command, command_dir=None, related_repo=None):
    work, head = prepare(repo, environment, action)
    env = dict(os.environ, FLOW_REPO_DIR=str(work), POINTS_MALL_SOURCE_DIR=str(work))
    related = prepare(related_repo, environment, action) if related_repo else None
    if related:
        env['JIFEN_ADMIN_ROOT'] = str(related[0])
    service = env.get('FLOW_SERVICE')
    state = Path(env.get('FLOW_STATE_DIR', str(Path(command_dir or work) / 'data/flow-state'))) / f'{service}.env'
    if environment == 'prod' and action == 'push' and service:
        git(work, 'push', '--quiet', 'origin', 'release:release')
        git(work, 'fetch', '--quiet', 'origin', 'refs/heads/release:refs/remotes/origin/release')
        if git(work, 'rev-parse', 'origin/release') != head:
            raise DeployError('release 推送核验失败')
        print('release 推送核验 0/0', flush=True)
        return 0
    if environment == 'prod' and action == 'deploy' and service:
        verify_state(state, head, service)
    result = subprocess.run(command, cwd=command_dir or work, env=env)
    if result.returncode:
        return result.returncode
    if environment == 'prod' and action == 'deploy':
        if service and read_state(state).get('last_status') != 'DEPLOY_SUCCESS':
            raise DeployError('Flow 未确认实际发布成功，master 未收口')
        finish_master(work, head)
        if related:
            finish_master(*related)
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--command-dir', type=Path)
    p.add_argument('--related-repo', type=Path)
    p.add_argument('environment', choices=['test', 'prod'])
    p.add_argument('repo', type=Path)
    p.add_argument('action', choices=['push', 'build', 'deploy'])
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command:
        p.error('缺少部署命令')
    try:
        return execute(a.repo, a.environment, a.action, command, a.command_dir, a.related_repo)
    except (DeployError, OSError) as e:
        print('停止：' + (str(e) if isinstance(e, DeployError) else type(e).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

"""部署菜单的 release 准备与按提交记录的构建证据。"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import shlex
import subprocess

import yaml
from deploysys_store import ConfigError


def git(repo, *args, optional=False):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if result.returncode:
        if optional:
            return ''
        raise ConfigError(f'Git 操作失败（{" ".join(args[:2])}）：请检查分支、工作区或网络；未继续部署。')
    return result.stdout.rstrip('\n')


def tokens(commands):
    try:
        return shlex.split('\n'.join(commands), comments=True)
    except ValueError as exc:
        raise ConfigError('无法解析部署命令，请检查引号。') from exc


def flow_service(commands):
    return next((t.split('=', 1)[1] for t in tokens(commands) if t.startswith('FLOW_SERVICE=')), '')


def source_repos(commands, root, project=None, target_cfg=None):
    """只解析已有源码路径，不运行配置命令，也不读取环境文件。"""
    ts = tokens(commands)
    sid = flow_service(commands)
    if sid and project:
        for service in project.get('services', []):
            for target in service.get('targets', {}).values():
                for lines in target.get('commands', {}).values():
                    if isinstance(lines, list) and flow_service(lines) == sid:
                        ts += tokens(lines)
    explicit = (target_cfg or {}).get('release_repos')
    if explicit is not None and (not isinstance(explicit, list) or not explicit or
                                 any(not isinstance(p, str) for p in explicit)):
        raise ConfigError('release_repos 必须是非空源码目录列表。')
    paths = []
    for i, t in enumerate(ts):
        if t.startswith(('FLOW_REPO_DIR=', 'JIFEN_ADMIN_ROOT=')):
            paths.append(t.split('=', 1)[1])
        if t in ('--related-repo', '--repo') and i + 1 < len(ts):
            paths.append(ts[i + 1])
        if Path(t).name in ('points-mall-deploy.py', 'service-order-deploy.py'):
            for j in range(i + 1, len(ts) - 1):
                if ts[j] in ('prod', 'test'):
                    paths.append(ts[j + 1])
                    break
        if t == 'cd' and i + 1 < len(ts):
            paths.append(ts[i + 1].rstrip(';'))
    sid = flow_service(commands)
    if sid:
        manifest = Path(root) / 'deployment/flow/services.yaml'
        if manifest.is_file():
            rows = (yaml.safe_load(manifest.read_text()) or {}).get('services', [])
            paths += [r['repo_dir'] for r in rows if r.get('id') == sid]
    if explicit is not None:
        paths = explicit
    repos = []
    common = set()
    tool_common = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir', optional=True)
    for path in paths:
        if '$' in path or path.startswith('~'):
            continue
        resolved = Path(path).resolve()
        if resolved == Path(root).resolve():
            continue
        toplevel = git(resolved, 'rev-parse', '--show-toplevel', optional=True)
        if explicit is not None and not toplevel:
            raise ConfigError(f'登记的源码目录不存在或不是 Git 仓库：{path}。')
        if toplevel:
            identity = common_repo(toplevel)
            if identity != tool_common and identity not in common:
                common.add(identity)
                repos.append(toplevel)
    return repos


def is_build(commands, action=''):
    text = '\n'.join(commands)
    return action == 'build' or bool(re.search(r'(?:flow-release\.sh\s+(?:build|release)\b|npm\s+run\s+build(?:[\s:]|$)|dotnet\s+(?:build|publish)\b|mvn\s+.*(?:package|install)\b)', text))


def needs_release(target, commands, action, target_cfg=None):
    if target.lower() not in ('prod', 'production', '生产') or action in ('status', '状态检查', 'logs', 'start', 'stop', 'restart'):
        return False
    if 'release_required' in (target_cfg or {}):
        if not isinstance(target_cfg['release_required'], bool):
            raise ConfigError('release_required 必须为布尔值。')
        return target_cfg['release_required']
    ts = tokens(commands)
    for i, token in enumerate(ts):
        name = Path(token).name.lower()
        if re.search(r'(?:restart|rollback|health|migrate|service-control)', name):
            continue
        if name == 'flow-release.sh':
            if i + 1 < len(ts) and ts[i + 1] in ('push', 'build', 'deploy', 'release'):
                return True
            continue
        if re.match(r'(?:deploy|upload|release)[\w.-]*\.(?:sh|py|js|ps1)$', name) or name in ('points-mall-deploy.py', 'service-order-deploy.py', 'branch_flow.py'):
            return True
        if token == 'npm' and ts[i+1:i+2] == ['run'] and i + 2 < len(ts):
            if re.match(r'(?:build|deploy|upload|release|prodoss|oss)(?:[:.-]|$)', ts[i+2]):
                return True
    return action in ('deploy', 'build')


def evidence_path(data_dir):
    return Path(data_dir) / 'build-success.json'


def evidence(data_dir):
    path = evidence_path(data_dir)
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text())
        if not isinstance(records, dict):
            raise ValueError('invalid records')
        return records
    except (ValueError, OSError) as exc:
        raise ConfigError('构建成功记录无法读取，请检查 data/build-success.json。') from exc


def common_repo(repo):
    return git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')


def state_for(commands, data_dir):
    sid = flow_service(commands)
    if not sid or not re.fullmatch(r'[\w.-]+', sid):
        return {}
    state_dir = next((t.split('=', 1)[1] for t in tokens(commands) if t.startswith('FLOW_STATE_DIR=')), str(Path(data_dir) / 'flow-state'))
    path = Path(state_dir) / f'{sid}.env'
    if not path.is_file():
        return {}
    # 仅保留本任务需要的非敏感构建字段。
    fields = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    return {k: fields.get(k, '') for k in ('service', 'source_commit', 'last_status')}


def build_snapshot(commands, root, project=None, target_cfg=None):
    return [{'repo': r, 'common': common_repo(r), 'branch': git(r, 'branch', '--show-current'),
             'head': git(r, 'rev-parse', 'HEAD')} for r in source_repos(commands, root, project, target_cfg)]


def record_build(snapshot, data_dir, service_id):
    records = evidence(data_dir)
    for row in snapshot:
        if git(row['repo'], 'rev-parse', 'HEAD') != row['head'] or git(row['repo'], 'branch', '--show-current') != row['branch']:
            continue
        records[row['common'] + ':' + row['head']] = {'branch': row['branch'], 'service': service_id,
            'time': dt.datetime.now().isoformat(timespec='seconds')}
    path = evidence_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def clean(repo):
    # 环境文件仅允许工作区未暂存差异；git switch 自身仍会阻止覆盖。
    allowed = {'.env', '.env.development', '.env.production', '.env.test', 'env.js', 'scripts/deploy/deploy.prod.env'}
    rows = git(repo, 'status', '--porcelain', '-z').split('\0')
    if any(row and not (row[:2] == ' M' and row[3:] in allowed) for row in rows):
        raise ConfigError(f'工作区有未提交改动：{repo}；请先整理，不自动 stash 或覆盖。')
    if not git(repo, 'branch', '--show-current'):
        raise ConfigError(f'工作区处于 detached HEAD：{repo}。')
    if git(repo, 'rev-parse', '--verify', 'MERGE_HEAD', optional=True):
        raise ConfigError(f'存在未完成合并：{repo}。')


def release_work(repo):
    for block in git(repo, 'worktree', 'list', '--porcelain').split('\n\n'):
        rows = block.splitlines()
        if 'branch refs/heads/release' in rows:
            return str(Path(rows[0].removeprefix('worktree ')).resolve())
    return repo


def plan_release(target, commands, action, root, data_dir, project=None, target_cfg=None):
    if not needs_release(target, commands, action, target_cfg):
        return None
    repos = source_repos(commands, root, project, target_cfg)
    if not repos:
        raise ConfigError('无法定位部署源码仓库，请在执行目标登记 release_repos；未继续部署。')
    records = evidence(data_dir)
    flow_state = state_for(commands, data_dir)
    plan = []
    for repo in repos:
        clean(repo)
        git(repo, 'fetch', '--quiet', '--prune', 'origin')
        remote = git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/release', optional=True)
        if not remote:
            raise ConfigError(f'远端缺少 release：{repo}；请先核对项目分支约定。')
        work = release_work(repo)
        clean(work)
        if repo != work and not any(repo in cmd for cmd in commands):
            raise ConfigError(f'release 被其他工作区占用，包装命令无法替换源码目录：{repo}；请使用可指定源码目录的入口。')
        local = git(repo, 'rev-parse', '--verify', 'refs/heads/release', optional=True)
        base = remote
        if local:
            result = git(repo, 'rev-list', '--left-right', '--count', f'{local}...{remote}').split()
            if int(result[0]) and int(result[1]):
                raise ConfigError(f'本地 release 与远端分叉：{repo}；请先处理。')
            if int(result[0]):
                base = local
        common = common_repo(repo)
        candidates = []
        refs = git(repo, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads', 'refs/remotes/origin')
        for line in refs.splitlines():
            ref, head = line.split()
            if ref in ('refs/heads/release', 'refs/remotes/origin/release', 'refs/remotes/origin/HEAD'):
                continue
            ahead, behind = map(int, git(repo, 'rev-list', '--left-right', '--count', f'{head}...{base}').split())
            if not ahead:
                continue
            label = ref.removeprefix('refs/heads/').removeprefix('refs/remotes/')
            # 相同提交的本地和远端分支只展示一次。
            duplicate = next((c for c in candidates if c['head'] == head), None)
            if duplicate:
                duplicate['aliases'].append(label)
                continue
            success = records.get(common + ':' + head)
            if not success and flow_state.get('service') == flow_service(commands) and flow_state.get('source_commit') == head and flow_state.get('last_status') in ('BUILD_SUCCESS', 'WAITING_CONFIRM', 'APPROVED_PENDING_DEPLOY', 'DEPLOY_SUCCESS'):
                success = {'service': flow_state.get('service'), 'time': 'Flow 构建记录'}
            candidates.append({'ref': ref, 'name': label, 'aliases': [], 'head': head, 'ahead': ahead,
                'behind': behind, 'build': success})
        plan.append({'repo': repo, 'work': work, 'branch': git(repo, 'branch', '--show-current'),
            'head': git(repo, 'rev-parse', 'HEAD'), 'release': base, 'remote': remote, 'local': local,
            'candidates': candidates})
    return plan


def prompt_selection(plan, prompt, emit):
    emit('继续会切换、同步并推送 release，然后执行所选生产命令；只合并您选择的分支。ACS 发布会自动完成构建、确认上线和结果检查。')
    selected = []
    choices = []
    for row in plan:
        emit(f"源码仓库：{row['repo']}；当前 {row['branch']} → release（{row['work']}）")
        for candidate in row['candidates']:
            choices.append((row, candidate))
            status = '构建成功：' + str(candidate['build'].get('time', '')) if candidate['build'] else '当前提交未记录构建成功'
            emit(f"{len(choices)}. {candidate['name']} {candidate['head'][:8]}，比 release 多 {candidate['ahead']} 个提交；{status}" + ('；已分叉' if candidate['behind'] else ''))
    answer = prompt('选择合并并推送 release 的分支编号（逗号分隔；回车不合并继续；0 取消部署）').strip()
    if answer == '0':
        return None
    if answer:
        try:
            indices = [int(x.strip()) for x in answer.split(',')]
        except ValueError as exc:
            raise ConfigError('分支编号无效，已停止部署。') from exc
        if any(n < 1 or n > len(choices) for n in indices):
            raise ConfigError('分支编号无效，已停止部署。')
        selected = [{'repo': choices[n-1][0]['repo'], 'ref': choices[n-1][1]['ref']} for n in dict.fromkeys(indices)]
    return selected


def apply_release(plan, selected, commands, emit):
    if not isinstance(selected, list):
        raise ConfigError('缺少分支选择，请重新执行部署。')
    valid = {(r['repo'], c['ref']): c for r in plan for c in r['candidates']}
    picked = []
    for item in selected:
        if not isinstance(item, dict):
            raise ConfigError('分支选择格式无效，请重新选择。')
        key = (item.get('repo'), item.get('ref'))
        if key not in valid or key in picked:
            raise ConfigError('所选分支不在当前候选列表中，请重新选择。')
        picked.append(key)
    # 在修改任何仓库前核验全部快照，防止等待选择期间的并发变更。
    for row in plan:
        repo = row['repo']
        clean(repo)
        clean(row['work'])
        git(repo, 'fetch', '--quiet', '--prune', 'origin')
        if (git(repo, 'rev-parse', 'HEAD') != row['head'] or git(repo, 'branch', '--show-current') != row['branch']
            or git(repo, 'rev-parse', 'refs/remotes/origin/release') != row['remote']
            or git(repo, 'rev-parse', '--verify', 'refs/heads/release', optional=True) != (row['local'] or '')
            or release_work(repo) != row['work']):
            raise ConfigError('等待选择期间分支已变化，请重新执行；未继续部署。')
        for candidate in row['candidates']:
            if git(repo, 'rev-parse', candidate['ref']) != candidate['head']:
                raise ConfigError('候选分支已更新，请重新选择；未继续部署。')
    updated = list(commands)
    for row in plan:
        work = row['work']
        if row['local']:
            git(work, 'switch', 'release')
            git(work, 'merge', '--ff-only', row['remote'])
        else:
            git(work, 'switch', '--track', '-c', 'release', 'origin/release')
        emit(f"已切换到 release：{work}")
        for key in picked:
            if key[0] != row['repo']:
                continue
            candidate = valid[key]
            emit(f"合并 {candidate['name']}（{candidate['head'][:8]}）→ release")
            try:
                git(work, 'merge', '--no-ff', '--no-edit', candidate['head'])
            except ConfigError as exc:
                raise ConfigError(f'合并失败：{work}；已停止部署，请检查冲突并处理或执行 git merge --abort。') from exc
        head = git(work, 'rev-parse', 'HEAD')
        if head != row['remote']:
            git(work, 'push', '--quiet', 'origin', 'release:release')
            git(work, 'fetch', '--quiet', 'origin', 'release')
            if git(work, 'rev-parse', 'origin/release') != head:
                raise ConfigError('release 推送后回读不一致，已停止部署。')
            emit('release 已推送并核验。')
        # 使用已登记的 release 工作区，不能在开发目录执行旧源码构建。
        if row['repo'] != work:
            # 同时覆盖带引号的仓库子目录，不改变其他同前缀目录。
            pattern = re.escape(row['repo']) + r"(?=/|[\s'\";]|$)"
            updated = [re.sub(pattern, lambda _: work, cmd) for cmd in updated]
    sid = flow_service(commands)
    if sid and re.search(r'flow-release\.sh\s+deploy\b', '\n'.join(commands)):
        # 合并后必须重新构建，不能拿旧 SHA 的镜像执行上线。
        return updated, True
    return updated, False

#!/usr/bin/env python3
"""积分商城测试 API 发布；保留服务器配置，使用已授权文档中的 SSH 凭据。"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HOST = '172.27.182.78'
WORKSPACE = Path('/Volumes/SSD/work/mall/积分商城')
SERVICES = {
    'front': ('api_front', 'jifen90.api', 3090, 'deploy-api-front.sh'),
    'back': ('api_back', 'jifen90.admin', 3091, 'deploy-api-back.sh'),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('service', choices=SERVICES)
    p.add_argument('--check', action='store_true', help='仅显示非敏感目标，不 SSH、不构建、不发布')
    a = p.parse_args()
    directory, unit, port, script = SERVICES[a.service]
    target = '/home/publish/jifen90/' + directory
    print(f'test_target={HOST}:{port} directory={target} unit={unit}', flush=True)
    if a.check:
        return 0
    repo = Path.cwd()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip()
    if branch != 'dev' or not (repo / 'scripts/deploy' / script).is_file():
        raise RuntimeError('必须经积分商城 dev 分支部署入口执行')
    # 只在进程内使用密码，不写入菜单、文件或日志。
    text = (WORKSPACE / 'depoy/dev-ecs.md').read_text()
    match = re.search(r'^\s*password\s*[:=：]\s*(.+?)\s*$', text, re.I | re.M)
    if not match:
        raise RuntimeError('测试 SSH 文档未包含预期密码字段')
    password = match.group(1).strip().strip(',').strip('"\x27')
    env = dict(os.environ, SSHPASS=password, DEPLOY_PASSWORD=password)
    ssh = ['sshpass', '-e', 'ssh', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
           '-o', 'PreferredAuthentications=password,keyboard-interactive', '-o', 'PubkeyAuthentication=no',
           '-o', 'NumberOfPasswordPrompts=1', 'root@' + HOST]
    # 防止旧端口、旧目录或错误服务被选中；不读取服务器敏感配置内容。
    command = (f'test "$(systemctl show {unit} -p WorkingDirectory --value)" = "{target}" '
               f'&& systemctl show {unit} -p Environment --value | grep -q "{HOST}:{port}"')
    r = subprocess.run(ssh + [command], env=env, capture_output=True, timeout=30)
    if r.returncode:
        raise RuntimeError('测试服务目录/端口核对失败，尚未发布')
    with tempfile.TemporaryDirectory(prefix='points-mall-test-') as tmp:
        env_file = Path(tmp) / 'deploy.test.env'
        env_file.write_text(f'''DEPLOY_TARGET=test
DEPLOY_HOST={HOST}
DEPLOY_USER=root
SSH_PORT=22
SSH_EXTRA_OPTIONS='-o StrictHostKeyChecking=yes -o ConnectTimeout=10'
API_FRONT_DIR=/home/publish/jifen90/api_front
API_BACK_DIR=/home/publish/jifen90/api_back
API_FRONT_SERVICE=jifen90.api
API_BACK_SERVICE=jifen90.admin
BACKUP_ROOT=/home/publish/jifen90/backups
RESTART_SERVICE=1
PRUNE_BACKUPS=0
''')
        env_file.chmod(0o600)
        env['DEPLOY_ENV_FILE'] = str(env_file)
        r = subprocess.run(['bash', 'scripts/deploy/' + script], env=env)
        if r.returncode:
            return r.returncode
    # 服务重启后可能需要数秒启动；轮询探活，不重复部署、不回滚。
    # 此检查不连接 Redis、不执行 SQL、不调用业务渠道。
    readiness_url = f'http://{HOST}:{port}/health/ready'
    readiness_command = (
        'attempt=0; while [ "$attempt" -lt 30 ]; do '
        f'if curl --fail --silent --output /dev/null --connect-timeout 1 --max-time 2 "{readiness_url}"; then '
        'echo readiness_http=200; exit 0; fi; '
        'attempt=$((attempt + 1)); sleep 2; done; '
        f'code=$(curl --silent --output /dev/null --write-out "%{{http_code}}" '
        f'--connect-timeout 1 --max-time 2 "{readiness_url}" || true); '
        'echo readiness_failed_http=$code; exit 1'
    )
    r = subprocess.run(ssh + [readiness_command], env=env, capture_output=True, text=True, timeout=95)
    if r.returncode:
        detail = (r.stdout + r.stderr).strip()
        raise RuntimeError('发布后 readiness 未通过；未自动重试部署或回滚' + (f'；{detail}' if detail else ''))
    print('测试发布完成，' + r.stdout.strip(), flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('停止：' + (str(e) if isinstance(e, RuntimeError) else type(e).__name__), file=sys.stderr)
        sys.exit(1)

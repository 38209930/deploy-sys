#!/usr/bin/env python3
"""仅重启已配置的 ECS 测试 systemd 服务；不构建、上传或修改运行配置。"""
import argparse
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

MALL = Path('/Volumes/SSD/work/mall')
STUDY = MALL / 'ai自习室/prod@aliyun/ai-study-api'
YANGU = Path('/Volumes/SSD/work/ddmp/prod/yangu-prod/api')
PROFILES = {
    'newsale-front': ('newsale', 'newsale.api', '/home/publish/newsale/api_front', False),
    'newsale-back': ('newsale', 'newsale.admin', '/home/publish/newsale/api_back', False),
    'service-order-front': ('service-order', 'serviceorder.front', None, False),
    'service-order-back': ('service-order', 'serviceorder.admin', None, False),
    'service-order-worker': ('service-order', 'serviceorder.worker', None, True),
    'points-mall-worker': ('points-mall', 'jifen90.worker', None, True),
    'ai-study-front': ('ai-study', 'ruishistore.api', 'API_DIR', False),
    'ai-study-back': ('ai-study', 'ruishistore.admin', 'ADMIN_DIR', False),
    'ai-study-worker': ('ai-study', 'ruishistore.worker', 'WORKER_DIR', True),
    'yangu-api': ('yangu', 'train-web.service', '/home/admin/app', False),
}

# 远端只输出固定结果字段，不输出 Environment、配置或 HTTP 响应正文。
REMOTE = r'''
import json, re, shlex, socket, subprocess, sys, time, urllib.request
c = json.loads(sys.stdin.read())
unit = c['unit']
def systemctl(*args):
    p = subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise RuntimeError('systemd 操作未确认成功；请先检查状态')
    return p.stdout.strip()
try:
    if systemctl('show', unit, '-p', 'LoadState', '--value') != 'loaded':
        raise RuntimeError('测试服务未安装')
    directory = systemctl('show', unit, '-p', 'WorkingDirectory', '--value')
    if not directory.startswith('/') or (c['directory'] and directory.rstrip('/') != c['directory'].rstrip('/')):
        raise RuntimeError('测试服务目录不匹配')
    env = dict(item.split('=', 1) for item in shlex.split(systemctl('show', unit, '-p', 'Environment', '--value')) if '=' in item)
    if c['java']:
        start = systemctl('show', unit, '-p', 'ExecStart', '--value')
        if not re.search(r'(?:spring.profiles.active=|SPRING_PROFILES_ACTIVE=)test(?:\s|;|$)', start + ' ' + ' '.join(k+'='+v for k,v in env.items())):
            raise RuntimeError('无法确认 Java 测试环境')
    elif env.get('ASPNETCORE_ENVIRONMENT', env.get('DOTNET_ENVIRONMENT')) not in ('Test', 'Development'):
        raise RuntimeError('服务不是 Test/Development 环境')
    url = None
    if not c['worker']:
        port = c.get('port') or re.search(r':(\d+)(?:/|$|;)', env.get('ASPNETCORE_URLS', ''))
        if not port:
            raise RuntimeError('无法确认健康检查端口；未执行重启')
        port = int(port if isinstance(port, int) else port.group(1))
        url = 'http://127.0.0.1:%d/health/ready' % port
    systemctl('restart', unit)
    stable_pid, stable_checks = None, 0
    for attempt in range(30):
        active = subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0
        if active:
            if url:
                try:
                    if c['java']:
                        with socket.create_connection(('127.0.0.1', port), timeout=2):
                            print('service_restarted unit=%s active=true listening=true' % unit)
                            break
                    with urllib.request.urlopen(url, timeout=2) as response:
                        if response.status == 200:
                            print('service_restarted unit=%s active=true ready=true' % unit)
                            break
                except Exception:
                    pass
            else:
                pid = systemctl('show', unit, '-p', 'MainPID', '--value')
                stable_checks = stable_checks + 1 if pid == stable_pid and pid != '0' else 1
                stable_pid = pid
                if stable_checks >= 3 and pid != '0':
                    print('service_restarted unit=%s active=true readiness=systemd' % unit)
                    break
        else:
            stable_pid, stable_checks = None, 0
        time.sleep(2)
    else:
        raise RuntimeError('重启后的服务未就绪；请先检查状态，不自动再次重启')
except Exception as exc:
    # 仅传播自己定义的固定错误，不转发底层异常中的环境信息。
    print(str(exc) if isinstance(exc, RuntimeError) else '测试重启检查失败', file=sys.stderr)
    sys.exit(1)
'''


def read_fields(text):
    def field(name):
        match = re.search(r'^\s*' + name + r'\s*[:=：]\s*(.+?)\s*$', text, re.I | re.M)
        if not match:
            raise RuntimeError('测试 SSH 说明缺少必要字段')
        return match.group(1).strip().strip(',').strip('"\x27')
    return {'host': field('ip'), 'user': field('username'), 'password': field('password')}


def env_values(path, names):
    # 沿用项目的 shell 环境文件；只提取 SSH 与服务定位字段，源文件输出不进入日志。
    code = 'import json,os; print(json.dumps({k:os.environ.get(k, "") for k in ' + repr(names) + '}))'
    result = subprocess.run(['bash', '-c', 'set -a; source "$1" >/dev/null 2>&1 || exit 1; python3 -c "$2"',
                             'restart-env', str(path), code], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('无法加载已有测试 SSH 环境文件')
    return json.loads(result.stdout)


def connection(profile):
    group, unit, directory, worker = PROFILES[profile]
    port, key = None, ''
    if group == 'ai-study':
        values = env_values(STUDY / 'scripts/deploy/deploy.dev.env',
                            ['DEPLOY_HOST', 'DEPLOY_USER', 'DEPLOY_PASSWORD', 'SSH_PORT', 'DEPLOY_SSH_KEY',
                             'API_DIR', 'ADMIN_DIR', 'WORKER_DIR', 'API_SERVICE', 'ADMIN_SERVICE', 'WORKER_SERVICE'])
        role = directory.removesuffix('_DIR')
        directory = values[directory]
        if not directory:
            raise RuntimeError('缺少测试服务目录')
        unit = values[role + '_SERVICE'] or unit
        config = dict(host=values['DEPLOY_HOST'], user=values['DEPLOY_USER'], password=values['DEPLOY_PASSWORD'],
                      ssh_port=values['SSH_PORT'] or '22')
        key = values['DEPLOY_SSH_KEY']
    elif group == 'yangu':
        names = ['YANGU_API_TEST_HOST', 'YANGU_API_TEST_USER', 'YANGU_API_TEST_PASS', 'YANGU_API_TEST_PORT',
                 'YANGU_API_SSH_PORT', 'YANGU_API_TEST_APP_DIR', 'YANGU_API_SERVICE_NAME', 'YANGU_API_TEST_LISTEN_PORT',
                 'YANGU_API_KNOWN_HOSTS_FILE']
        path = YANGU / 'deploy/deploy.local.env'
        values = env_values(path, names) if path.is_file() else {name: os.environ.get(name, '') for name in names}
        config = dict(host=values[names[0]] or '172.27.182.60', user=values[names[1]] or 'root',
                      password=values[names[2]], ssh_port=values[names[3]] or values[names[4]] or '22')
        directory, unit = values[names[5]] or directory, values[names[6]] or unit
        port = int(values[names[7]] or '8090')
        config['known_hosts'] = values[names[8]]
    elif group == 'points-mall':
        # 复用已验证的积分商城测试 SSH 连接，不猜测文档格式或服务器地址。
        spec = importlib.util.spec_from_file_location('points_test_restart', Path(__file__).with_name('points-mall-test-api.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ssh, env = module.load_ssh_connection()
        return ssh, env, dict(unit=unit, directory=directory, worker=worker, java=False, port=None)
    else:
        paths = {'newsale': MALL / '新零售/config.md', 'service-order': MALL / '售后工单系统/deploy/dev-ecs.md',
                 'points-mall': MALL / '积分商城/depoy/dev-ecs.md'}
        text = paths[group].read_text()
        if group == 'newsale':
            text = text.split('测试服务器', 1)[1].split('}', 1)[0]
            port = 3095 if profile.endswith('front') else 3097
        config = read_fields(text)
    ipaddress.ip_address(config['host'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', config['user']) or not re.fullmatch(r'[A-Za-z0-9_.@-]+', unit):
        raise RuntimeError('SSH 用户或服务名格式无效')
    ssh_port = int(config.get('ssh_port', '22'))
    if not 1 <= ssh_port <= 65535:
        raise RuntimeError('SSH 端口无效')
    ssh = ['ssh', '-p', str(ssh_port), '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
           '-o', 'NumberOfPasswordPrompts=1']
    env = dict(os.environ)
    if key:
        ssh.extend(['-i', key])
    if config.get('known_hosts'):
        ssh.extend(['-o', 'UserKnownHostsFile=' + config['known_hosts']])
    if config['password']:
        env['SSHPASS'] = config['password']
        ssh = ['sshpass', '-e', *ssh]
    else:
        ssh.extend(['-o', 'BatchMode=yes'])
    ssh.append(config['user'] + '@' + config['host'])
    return ssh, env, dict(unit=unit, directory=directory, worker=worker, java=group == 'yangu', port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=PROFILES)
    args = parser.parse_args()
    ssh, env, target = connection(args.profile)
    result = subprocess.run(ssh + ['python3 -c ' + shlex.quote(REMOTE)], input=json.dumps(target),
                            env=env, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('ECS 测试服务重启未确认成功；请先执行状态检查')
    print(result.stdout.strip())


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        print('测试服务重启未确认成功；请检查 SSH、环境和服务状态，不自动重试', file=sys.stderr)
        sys.exit(1)

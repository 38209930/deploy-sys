#!/usr/bin/env python3
"""M1X 测试 API：锁定兼容提交构建，保留服务器私有配置；不部署 Worker。"""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO = Path('/Volumes/SSD/work/ddmp/prod/stopmp/M1-X/m1x-api')
SSH_DOCUMENT = Path('/Volumes/SSD/work/mall/售后工单系统/deploy/dev-ecs.md')
HOST = '172.27.182.61'
# 匿名渠道收敛尚未验收，禁止默认构建工作分支或 release 的最新代码。
COMMIT = '88cacbcab99f5ab8c8e804c209b41dd7120884ca'
PUBLIC_HEALTH = 'https://m1x-api-test.svision100.com/actuator/health'
JAVA_HOME = Path('/Library/Java/JavaVirtualMachines/jdk-1.8.jdk/Contents/Home')

REMOTE = r'''
import hashlib, json, os, pathlib, pwd, re, shutil, subprocess, sys, time, urllib.request
c=json.load(sys.stdin)
unit='m1x-test-api.service'
root=pathlib.Path('/opt/m1x-test')
jar=root/'releases/api-88cacbc.jar'
def control(*args):
    return subprocess.check_output(['systemctl',*args],stderr=subprocess.DEVNULL,text=True,timeout=45).strip()
def digest(path):
    with path.open('rb') as stream:
        value=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''): value.update(chunk)
    return value.hexdigest()
def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18080/actuator/health',timeout=2) as response:
            return response.status==200 and json.load(response).get('status')=='UP'
    except Exception: return False
def ready():
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if control('show',unit,'-p','ActiveState','--value')=='active' and healthy(): return
        time.sleep(2)
    raise RuntimeError('API 健康检查失败')
def status():
    pid=int(control('show',unit,'-p','MainPID','--value'))
    listeners=subprocess.check_output(['ss','-lntp'],text=True)
    owned=any(re.search(r':18080\s',line) and ('pid=%d,'%pid) in line for line in listeners.splitlines())
    if not owned or not healthy(): raise RuntimeError('API 健康或端口归属检查失败')
    print(json.dumps(dict(service=unit,active=True,port=18080,health='UP',jar_sha256=digest(jar))))
try:
    if control('show',unit,'-p','WorkingDirectory','--value')!=str(root):
        raise RuntimeError('测试 API 工作目录不匹配')
    start=control('show',unit,'-p','ExecStart','--value')
    if str(jar) not in start or 'file:/opt/m1x-test/config/application.yml' not in start:
        raise RuntimeError('测试 API 制品或外部配置路径不匹配')
    if not (root/'config/application.yml').is_file() or not (root/'config/api.env').is_file():
        raise RuntimeError('测试私有配置缺失')
    if c['action']=='restart':
        control('restart',unit)
        ready()
    elif c['action']=='deploy':
        stage=pathlib.Path(c['stage'])
        if stage.parent!=root/'releases' or not re.fullmatch(r'\.upload-[a-f0-9]{32}\.jar',stage.name):
            raise RuntimeError('上传路径无效')
        if digest(stage)!=c['sha256']: raise RuntimeError('上传制品校验失败')
        backup=jar.with_name(jar.name+'.backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+stage.stem[-8:])
        shutil.copy2(jar,backup)
        try:
            control('stop',unit)
            shutil.copy2(stage,jar)
            user=pwd.getpwnam('m1x-test')
            os.chown(jar,user.pw_uid,user.pw_gid)
            os.chmod(jar,0o640)
            control('start',unit)
            ready()
            if digest(jar)!=c['sha256']: raise RuntimeError('运行制品校验失败')
            status()
        except Exception:
            control('stop',unit)
            shutil.copy2(backup,jar)
            control('start',unit)
            ready()
            raise RuntimeError('发布失败，已恢复上一版 API')
        finally: stage.unlink(missing_ok=True)
        print('backup='+str(backup))
        sys.exit(0)
    status()
except Exception as exc:
    print(str(exc) if isinstance(exc,RuntimeError) else '测试 API 操作未确认成功，请先检查状态',file=sys.stderr)
    sys.exit(1)
'''


class Connection:
    def __init__(self):
        text = SSH_DOCUMENT.read_text()
        block = re.search(r'Server\s*:\s*\{([^}]+)\}', text)
        if not block:
            raise RuntimeError('SSH 文档缺少 Server 块')
        fields = {}
        for key in ('ip', 'username', 'password'):
            match = re.search(r'(?m)^\s*' + key + r'\s*:\s*([^\s,}]+)', block[1])
            if not match:
                raise RuntimeError('SSH 文档缺少必要字段')
            fields[key] = match[1]
        if fields['ip'] != HOST or not re.fullmatch(r'[A-Za-z0-9_-]+', fields['username']):
            raise RuntimeError('SSH 测试目标不匹配')
        self.user = fields['username']
        self.password = fields['password']

    def run(self, command, *, payload=None, copy=False):
        # 密码仅经匿名管道交给 sshpass，不进入命令、环境变量或日志。
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, (self.password + '\n').encode())
        finally:
            os.close(write_fd)
        options = ['-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
                   '-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no',
                   '-o', 'NumberOfPasswordPrompts=1']
        args = ['sshpass', '-d', str(read_fd), 'scp' if copy else 'ssh', *options]
        if copy:
            args += [str(command[0]), self.user + '@' + HOST + ':' + command[1]]
        else:
            args += [self.user + '@' + HOST, command]
        try:
            result = subprocess.run(args, input=payload, text=True, capture_output=True,
                                    pass_fds=(read_fd,), timeout=240)
        finally:
            os.close(read_fd)
        if result.stdout and not copy:
            print(result.stdout.strip(), flush=True)
        if result.returncode:
            # 远端脚本仅输出固定错误；不转发 SSH 的配置或底层认证信息。
            detail = result.stderr.strip() if not copy and result.stderr.startswith(('API ', '测试 ', '发布失败', '上传')) else ''
            raise RuntimeError(detail or '测试 SSH 操作未确认成功，请先检查状态')

    def remote(self, action, **values):
        self.run('python3 -c ' + shlex.quote(REMOTE), payload=json.dumps(dict(action=action, **values)))


def export_source(destination):
    # 只导出锁定提交，不切换开发工作区；部署配置与 application 文件不落入构建目录。
    archive = subprocess.check_output(['git', '-C', str(REPO), 'archive', COMMIT])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            parts = Path(member.name).parts
            if any(p in ('Doc', 'deploy', 'deployment', '.git') for p in parts):
                continue
            if re.fullmatch(r'application[^/]*\.(?:yml|yaml|properties)', Path(member.name).name):
                continue
            if Path(member.name).name.startswith('.env'):
                continue
            if Path(member.name).is_absolute() or '..' in parts:
                raise RuntimeError('源码归档路径无效')
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content, target.open('wb') as output:
                    shutil.copyfileobj(content, output)


@contextmanager
def build_api():
    if not (JAVA_HOME / 'bin/javac').is_file():
        raise RuntimeError('缺少项目要求的 JDK 8')
    maven = shutil.which('mvn') or '/usr/local/apache-maven-4.0.0/bin/mvn'
    if not os.access(maven, os.X_OK):
        raise RuntimeError('缺少 Maven，请先配置本机构建环境')
    with tempfile.TemporaryDirectory(prefix='m1x-test-build-') as directory:
        root = Path(directory)
        export_source(root)
        env = dict(os.environ, JAVA_HOME=str(JAVA_HOME), PATH=str(JAVA_HOME / 'bin') + os.pathsep + os.environ['PATH'])
        # 只执行受影响的定向测试，不运行整个仓库的测试。
        subprocess.run([maven, '-q', '-pl', 'train-web', '-am',
                        '-Dtest=AccountChannelServiceTest,AccountChannelContractTest,ReportWebviewServiceImplTest,TokenSigningIsolationTest',
                        '-Dsurefire.failIfNoSpecifiedTests=false', 'package'], cwd=root, env=env, check=True)
        jar = root / 'train-web/target/train-web-test-1.0.2.jar'
        validate_artifact(jar)
        yield jar


def validate_artifact(jar):
    with zipfile.ZipFile(jar) as archive:
        names = archive.namelist()
        if 'BOOT-INF/classes/com/ruishi/train/TrainApplication.class' not in names:
            raise RuntimeError('制品不是 M1X Spring Boot API')
        if any(re.fullmatch(r'BOOT-INF/classes/application[^/]*\.(?:yml|yaml|properties)', n) for n in names):
            raise RuntimeError('制品包含 application 配置，禁止上传')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'status', 'restart', 'deploy'))
    args = parser.parse_args()
    print('test_api=%s:18080 service=m1x-test-api commit=%s health=%s' % (HOST, COMMIT, PUBLIC_HEALTH), flush=True)
    if args.action == 'check':
        return
    connection = Connection()
    if args.action != 'deploy':
        connection.remote(args.action)
        return
    connection.remote('status')
    with build_api() as jar:
        import uuid
        stage = '/opt/m1x-test/releases/.upload-' + uuid.uuid4().hex + '.jar'
        sha = hashlib.sha256(jar.read_bytes()).hexdigest()
        try:
            connection.run((jar, stage), copy=True)
            connection.remote('deploy', stage=stage, sha256=sha)
        finally:
            connection.run('rm -f -- ' + shlex.quote(stage))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else '测试部署停止：' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)

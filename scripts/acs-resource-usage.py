#!/usr/bin/env python3
"""只读查看 ACS Deployment 的当前容器用量、资源配置与 Pod 状态。"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

PROFILE = 'ruishi-prod-acr'
REGION = 'cn-beijing'
ACCOUNT = '1442361567788059'
CLUSTER = 'cebc88343a44b4d759aa983a47b787835'


def call(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f'{args[0]} 查询失败；请检查登录、RBAC、OpenVPN 及 metrics-server。')
    return result.stdout


def cloud(product, action, *args):
    data = json.loads(call('aliyun', product, action, *args, '--profile', PROFILE, '--region', REGION))
    if data.get('Code') or data.get('code'):
        raise RuntimeError(f"阿里云 API 失败：{data.get('Code') or data.get('code')}")
    return data


def selector_text(selector):
    terms = [f'{k}={v}' for k, v in selector.get('matchLabels', {}).items()]
    for item in selector.get('matchExpressions', []):
        key, op = item['key'], item['operator']
        if op in ('In', 'NotIn'):
            terms.append(f"{key} {'in' if op == 'In' else 'notin'} ({','.join(item['values'])})")
        elif op in ('Exists', 'DoesNotExist'):
            terms.append(key if op == 'Exists' else f'!{key}')
        else:
            raise RuntimeError('无法识别 Deployment selector')
    if not terms:
        raise RuntimeError('Deployment selector 为空，已停止查询')
    return ','.join(terms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--deployment', required=True)
    args = parser.parse_args()
    for value in (args.namespace, args.deployment):
        if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', value):
            raise RuntimeError('目标名称格式无效')
    if str(cloud('sts', 'GetCallerIdentity').get('AccountId')) != ACCOUNT:
        raise RuntimeError('阿里云账号不匹配，已停止查询')
    response = cloud('cs', 'DescribeClusterUserKubeconfig', '--ClusterId', CLUSTER,
                     '--PrivateIpAddress', 'true', '--TemporaryDurationMinutes', '15')
    if not response.get('config'):
        raise RuntimeError('ACS 未返回临时访问配置')
    with tempfile.TemporaryDirectory(prefix='acs-resources-') as directory:
        config = os.path.join(directory, 'config')
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(response['config'])
        def kubectl(*params):
            return call('kubectl', '--kubeconfig', config, '--request-timeout=20s', '-n', args.namespace, *params)
        deployment = json.loads(kubectl('get', 'deployment', args.deployment, '-o', 'json'))
        print(f'目标：{args.namespace}/{args.deployment}；期望副本：{deployment["spec"].get("replicas", 1)}')
        print('\n容器资源配置（requests / limits）：')
        for container in deployment['spec']['template']['spec']['containers']:
            resources = container.get('resources', {})
            print(container['name'], json.dumps(resources, ensure_ascii=False))
        pods = json.loads(kubectl('get', 'pods', '-l', selector_text(deployment['spec']['selector']), '-o', 'json'))
        if not pods.get('items'):
            print('\n当前无 Pod，无实时资源用量。')
            return
        failed = False
        for pod in pods['items']:
            name = pod['metadata']['name']
            print(f'\nPod：{name}；IP：{pod["status"].get("podIP", "-")}；状态：{pod["status"].get("phase", "-")}')
            for container in pod['status'].get('containerStatuses', []):
                reason = container.get('lastState', {}).get('terminated', {}).get('reason', '-')
                print(f'{container["name"]} Ready={container["ready"]} 重启={container["restartCount"]} 上次退出原因={reason}')
            try:
                output = kubectl('top', 'pod', name, '--containers')
                # 部分 ACS 指标还含空容器名的汇总行，避免显示为虚假的 0 用量。
                print('\n'.join(line for line in output.splitlines() if len(line.split()) >= 4))
            except RuntimeError:
                failed = True
                print('实时指标不可用，不能按零用量解读；新 Pod 可能尚未产生采样。')
        print('\n单位：1000m CPU = 1 核；1024Mi = 1GiB。仅为近期采样，不代表历史峰值或 CPU 限流情况。')
        if failed:
            raise RuntimeError('部分 Pod 指标不可用')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'资源查询失败：{exc}', file=sys.stderr)
        sys.exit(1)

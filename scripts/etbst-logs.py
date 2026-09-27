#!/usr/bin/env python3
"""只读查看 ETBST ACS 应用日志和 Kubernetes 告警事件。"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
import tempfile


ACCOUNT = "1442361567788059"
PROFILE = "ruishi-prod-acr"
REGION = "cn-beijing"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
NAMESPACE = "etbst-api"
DEPLOYMENT = "etbst-api"
ERROR_PATTERN = re.compile(r"\b(ERROR|FATAL|Exception|Traceback|panic)\b|错误|异常", re.I)
WARNING_PATTERN = re.compile(r"\b(WARN|WARNING)\b|告警|警告", re.I)


def call(*args):
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} 查询失败（退出码 {result.returncode}）；请检查权限、登录状态及 OpenVPN 连接")
    return result.stdout


def cloud(product, action, *args):
    data = json.loads(call("aliyun", product, action, *args, "--profile", PROFILE, "--region", REGION))
    if data.get("Code") or data.get("code"):
        raise RuntimeError(f"阿里云 API 查询失败：{data.get('Code') or data.get('code')}")
    return data


def event_time(item):
    value = (item.get("eventTime") or item.get("lastTimestamp") or item.get("metadata", {}).get("creationTimestamp"))
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="all", choices=("all", "normal", "error", "warning", "events"))
    args = parser.parse_args()
    mode = args.mode

    identity = cloud("sts", "GetCallerIdentity")
    if str(identity.get("AccountId")) != ACCOUNT:
        raise RuntimeError("阿里云账号不匹配，已停止查询")
    response = cloud("cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
                     "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15")
    if not response.get("config"):
        raise RuntimeError("ACS 未返回临时访问配置")

    with tempfile.TemporaryDirectory(prefix="etbst-logs-") as directory:
        config = os.path.join(directory, "config")
        descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(response["config"])

        def kubectl(*params):
            return call("kubectl", "--kubeconfig", config, "-n", NAMESPACE, *params)

        if mode != "events":
            lines = kubectl("logs", f"deployment/{DEPLOYMENT}", "-c", DEPLOYMENT,
                            "--since=30m", "--tail=200", "--limit-bytes=1048576", "--timestamps=true").splitlines()
            if mode == "all":
                groups = (("普通日志", lines[-100:]),
                          ("错误日志", [line for line in lines if ERROR_PATTERN.search(line)][-50:]),
                          ("告警日志", [line for line in lines if WARNING_PATTERN.search(line)][-50:]))
                for title, selected in groups:
                    print(f"\n{title}（最近 30 分钟）：")
                    print("\n".join(selected) if selected else "无匹配日志。")
            else:
                pattern = ERROR_PATTERN if mode == "error" else WARNING_PATTERN if mode == "warning" else None
                selected = [line for line in lines if pattern is None or pattern.search(line)]
                print("\n".join(selected) if selected else "所选时间范围内无匹配的应用日志。")

        if mode in ("all", "warning", "events"):
            data = json.loads(kubectl("get", "events", "--field-selector=type=Warning", "-o", "json"))
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            selected = []
            for item in data.get("items", []):
                involved = item.get("involvedObject", {})
                name = involved.get("name", "")
                stamp = event_time(item)
                if not name.startswith(DEPLOYMENT) or stamp is None or stamp < cutoff:
                    continue
                selected.append(f"{stamp.isoformat()} {item.get('reason', '')}: {item.get('message', '')}")
            print("\nKubernetes 告警事件（最近 30 分钟，最多 50 条）：")
            print("\n".join(selected[-50:]) if selected else "无匹配事件。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"日志查询失败：{exc}", file=sys.stderr)
        sys.exit(1)

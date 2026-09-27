#!/usr/bin/env python3
"""为含进程内定时任务的 Java API 安装单副本 Recreate 原生准入。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


PROFILE = "ruishi-prod-acr"
ACCOUNT = "1442361567788059"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
POLICY = "ruishi-java-scheduler-singleton"
NAMESPACES = ("stopmp-api", "etbst-api", "ddmp-api", "yangu-api", "dgye-api", "vet-api")
SOURCE = Path(__file__).with_name("java-scheduler-singleton-guard.yaml")


def run(*args, data=None, check=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True, check=False, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} 失败：{result.stderr[:350]}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    identity = json.loads(run("aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE).stdout)
    if identity.get("AccountId") != ACCOUNT:
        raise RuntimeError("生产账号不匹配")
    response = json.loads(run("aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
                            "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
                            "--profile", PROFILE, "--region", "cn-beijing").stdout)
    if response.get("Code") or not response.get("config"):
        raise RuntimeError("ACS 临时访问材料为空")
    with tempfile.TemporaryDirectory(prefix="acs-java-guard-") as directory:
        path = os.path.join(directory, "config")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(response["config"])

        def kubectl(*cmd, data=None, check=True):
            return run("kubectl", "--kubeconfig", path, *cmd, data=data, check=check)

        policy_text = SOURCE.read_text(encoding="utf-8")
        policy_current = kubectl("get", "validatingadmissionpolicy", POLICY, "-o", "json", check=False)
        if policy_current.returncode != 0:
            kubectl("create", "--dry-run=server", "-f", "-", data=policy_text)
            print("规则服务端预检通过", flush=True)
            if args.execute:
                kubectl("create", "-f", "-", data=policy_text)
        elif json.loads(policy_current.stdout)["spec"]["validations"][0]["expression"].strip() != \
                " ".join(policy_text.split("expression: >-")[1].split("message:")[0].split()):
            # YAML 块标量在 API 内会折叠为空格；差异需要人工审查。
            raise RuntimeError("同名准入规则已存在且表达式不同")

        for namespace in NAMESPACES:
            dep = json.loads(kubectl("-n", namespace, "get", "deployment", namespace, "-o", "json").stdout)
            if dep["spec"].get("replicas", 1) > 1 or dep["spec"].get("strategy", {}).get("type") != "Recreate":
                raise RuntimeError(f"{namespace} 现有部署不符合单实例 Recreate")
            if not args.execute:
                continue
            name = f"ruishi-java-singleton-{namespace}"
            existing = kubectl("get", "validatingadmissionpolicybinding", name, "-o", "json", check=False)
            if existing.returncode == 0:
                binding = json.loads(existing.stdout)
                if binding["spec"].get("policyName") != POLICY:
                    raise RuntimeError(f"{name} 已存在且指向其他规则")
            else:
                binding = {
                    "apiVersion": "admissionregistration.k8s.io/v1",
                    "kind": "ValidatingAdmissionPolicyBinding",
                    "metadata": {"name": name},
                    "spec": {"policyName": POLICY, "validationActions": ["Deny"],
                             "matchResources": {"namespaceSelector": {
                                 "matchLabels": {"kubernetes.io/metadata.name": namespace}}}},
                }
                kubectl("create", "--dry-run=server", "-f", "-", data=json.dumps(binding))
                kubectl("create", "-f", "-", data=json.dumps(binding))
            for attempt in range(6):
                valid = kubectl("-n", namespace, "replace", "--dry-run=server", "-f", "-",
                                data=json.dumps(dep), check=False)
                invalid_dep = json.loads(json.dumps(dep))
                invalid_dep["spec"]["strategy"] = {"type": "RollingUpdate"}
                invalid = kubectl("-n", namespace, "replace", "--dry-run=server", "-f", "-",
                                  data=json.dumps(invalid_dep), check=False)
                if valid.returncode == 0 and invalid.returncode != 0 and POLICY in invalid.stderr:
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"{namespace} 准入实际拒绝用例未通过")
            print("准入通过", namespace, "正常更新允许、RollingUpdate 拒绝", flush=True)
        if not args.execute:
            print("只读预检通过；未安装准入规则", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"停止：{error}", file=sys.stderr)
        sys.exit(1)

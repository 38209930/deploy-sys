#!/usr/bin/env python3
"""已迁移 Namespace 加入 ACS 默认新选址和原生准入保护。"""

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import tempfile


ACCOUNT = "1442361567788059"
PROFILE = "ruishi-prod-acr"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
ANNOTATION = "network.alibabacloud.com/vswitch-ids"
SWITCHES = {"vsw-2zevd832gq3313j6gv5sj", "vsw-2zesy6off4gy39tqripzp"}
CIDRS = (ipaddress.ip_network("172.31.240.0/24"), ipaddress.ip_network("172.28.64.0/24"))
POLICIES = ("deployment", "pod")


def run(*args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} 失败：{result.stderr[:300]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace", choices=("new-retail", "agent-query", "stopmp-api", "etbst-api", "ddmp-api"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    identity = json.loads(run("aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE))
    if identity.get("AccountId") != ACCOUNT:
        raise RuntimeError("生产账号不匹配")
    response = json.loads(run("aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
                              "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
                              "--profile", PROFILE, "--region", "cn-beijing"))
    with tempfile.TemporaryDirectory(prefix="acs-egress-protect-") as directory:
        config = os.path.join(directory, "config")
        with open(config, "w", encoding="utf-8") as file:
            file.write(response["config"])
        os.chmod(config, 0o600)

        def kubectl(*params, data=None):
            return run("kubectl", "--kubeconfig", config, *params, data=data)

        def get(*params):
            return json.loads(kubectl("get", *params, "-o", "json"))

        deployments = get("deployments", "-n", args.namespace)["items"]
        pods = get("pods", "-n", args.namespace)["items"]
        if not deployments:
            raise RuntimeError("Namespace 无 Deployment")
        for dep in deployments:
            value = dep["spec"]["template"]["metadata"].get("annotations", {}).get(ANNOTATION, "")
            if set(value.split(",")) != SWITCHES or len(value.split(",")) != 2:
                raise RuntimeError(f"Deployment {dep['metadata']['name']} 未显式使用两个新 vSwitch")
            if dep["status"].get("readyReplicas", 0) != dep["spec"].get("replicas", 1):
                raise RuntimeError(f"Deployment {dep['metadata']['name']} 未全部 Ready")
        active = [pod for pod in pods if not pod["metadata"].get("deletionTimestamp")]
        if len(active) != sum(dep["spec"].get("replicas", 1) for dep in deployments):
            raise RuntimeError("Pod 数与期望副本不符")
        for pod in active:
            address = pod["status"].get("podIP")
            if not address or not any(ipaddress.ip_address(address) in cidr for cidr in CIDRS):
                raise RuntimeError(f"Pod {pod['metadata']['name']} 不在新网段")

        profile = get("configmap", "acs-profile", "-n", "kube-system")
        selectors = json.loads(profile["data"]["selectors"])
        if selectors[0].get("name") != "validated-egress-namespaces" or selectors[1].get("name") != "legacy-vswitch-default":
            raise RuntimeError("acs-profile selector 结构已变化")
        values = selectors[0]["namespaceSelector"]["matchExpressions"][0]["values"]
        if args.namespace in values:
            raise RuntimeError("Namespace 已有默认新选址，请检查是否部分完成")
        values.append(args.namespace)
        updated = json.loads(json.dumps(profile))
        updated["data"]["selectors"] = json.dumps(selectors, ensure_ascii=False, separators=(",", ":"))
        kubectl("replace", "--dry-run=server", "-f", "-", data=json.dumps(updated))

        bindings = []
        for kind in POLICIES:
            name = f"ruishi-egress-{kind}-{args.namespace}"
            result = subprocess.run(["kubectl", "--kubeconfig", config, "get", "validatingadmissionpolicybinding", name],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                raise RuntimeError(f"Binding {name} 已存在，请检查是否部分完成")
            source = get("validatingadmissionpolicybinding", f"ruishi-egress-{kind}-ai-study")
            binding = {"apiVersion": source["apiVersion"], "kind": source["kind"],
                       "metadata": {"name": name}, "spec": source["spec"]}
            binding["spec"]["matchResources"]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] = args.namespace
            kubectl("create", "--dry-run=server", "-f", "-", data=json.dumps(binding))
            bindings.append(binding)
        print("预检通过", args.namespace, "Deployment", len(deployments), "Pod", len(active),
              "profile RV", profile["metadata"]["resourceVersion"], flush=True)
        if not args.execute:
            print("只读模式；未修改生产对象", flush=True)
            return
        kubectl("replace", "-f", "-", data=json.dumps(updated))
        for binding in bindings:
            kubectl("create", "-f", "-", data=json.dumps(binding))
        actual = get("configmap", "acs-profile", "-n", "kube-system")
        actual_selectors = json.loads(actual["data"]["selectors"])
        if args.namespace not in actual_selectors[0]["namespaceSelector"]["matchExpressions"][0]["values"]:
            raise RuntimeError("默认选址读回不匹配")
        for kind in POLICIES:
            binding = get("validatingadmissionpolicybinding", f"ruishi-egress-{kind}-{args.namespace}")
            if binding["spec"]["matchResources"]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] != args.namespace:
                raise RuntimeError("Binding 读回不匹配")
        print("已读回默认选址和两条准入 Binding", args.namespace, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"停止：{error}", file=sys.stderr)
        sys.exit(1)

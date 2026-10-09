#!/usr/bin/env python3
"""一次仅迁移一个 ACS Deployment 的 Pod 选址；生产写入需先获授权。"""

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import time


PROFILE = "ruishi-prod-acr"
ACCOUNT = "1442361567788059"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
ANNOTATION = "network.alibabacloud.com/vswitch-ids"
NEW_SWITCHES = "vsw-2zevd832gq3313j6gv5sj,vsw-2zesy6off4gy39tqripzp"
NEW_CIDRS = (ipaddress.ip_network("172.31.240.0/24"), ipaddress.ip_network("172.28.64.0/24"))


def command(argv, *, data=None, required=True):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, check=False)
    if required and result.returncode:
        raise RuntimeError(f"{argv[0]} 失败：{result.stderr[:400]}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("deployment")
    parser.add_argument("--health-url", help="现有正式域名的 /health/ready 地址；API 必填")
    parser.add_argument("--expected-status", type=int, default=200,
                        help="正式入口变更前后应保持的 HTTP 状态，默认 200；认证保护的健康接口可用 401")
    parser.add_argument("--execute", action="store_true", help="只读预检通过后执行迁移")
    args = parser.parse_args()
    if not args.deployment.endswith("-worker") and not args.health_url:
        parser.error("API 必须提供 --health-url")
    if not 200 <= args.expected_status < 500:
        parser.error("--expected-status 必须为 200–499")

    identity = json.loads(command(["aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE]).stdout)
    if identity.get("AccountId") != ACCOUNT:
        raise RuntimeError("阿里云账号不匹配，停止")
    response = command([
        "aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
        "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
        "--profile", PROFILE, "--region", "cn-beijing",
    ])
    config = json.loads(response.stdout)["config"]
    with tempfile.TemporaryDirectory(prefix="acs-egress-") as directory:
        kubeconfig = os.path.join(directory, "config")
        with open(kubeconfig, "w", encoding="utf-8") as file:
            file.write(config)
        os.chmod(kubeconfig, 0o600)

        def kubectl(*parameters, data=None, required=True):
            return command(
                ["kubectl", "--kubeconfig", kubeconfig, "-n", args.namespace, *parameters],
                data=data, required=required,
            )

        def deployment():
            return json.loads(kubectl("get", "deployment", args.deployment, "-o", "json").stdout)

        def active_pods():
            items = json.loads(kubectl("get", "pods", "-o", "json").stdout)["items"]
            return [item for item in items if item["metadata"]["name"].startswith(args.deployment + "-")
                    and item["status"].get("phase") == "Running"
                    and not item["metadata"].get("deletionTimestamp")]

        def remaining_pods():
            items = json.loads(kubectl("get", "pods", "-o", "json").stdout)["items"]
            return [item for item in items if item["metadata"]["name"].startswith(args.deployment + "-")
                    and item["status"].get("phase") not in ("Succeeded", "Failed")]

        before = deployment()
        old_annotations = before["spec"]["template"]["metadata"].get("annotations", {})
        old_switches = old_annotations.get(ANNOTATION)
        if old_switches == NEW_SWITCHES:
            raise RuntimeError("Deployment 已指定新网段，停止重复迁移")
        if before["spec"].get("replicas") != 1 or before["status"].get("readyReplicas") != 1:
            raise RuntimeError("不是稳定的单副本，停止")
        if args.deployment.endswith("-worker") and before["spec"].get("strategy", {}).get("type") != "Recreate":
            raise RuntimeError("Worker 未采用 Recreate，停止")
        image = before["spec"]["template"]["spec"]["containers"][0]["image"]
        secrets = [v["secret"]["secretName"] for v in before["spec"]["template"]["spec"].get("volumes", []) if "secret" in v]
        print("预检", args.namespace, args.deployment, "resourceVersion", before["metadata"]["resourceVersion"],
              "原选址", old_switches or "默认", "镜像摘要", image.split("@")[-1][:20], flush=True)

        proposed = json.loads(json.dumps(before))
        proposed["spec"]["template"]["metadata"].setdefault("annotations", {})[ANNOTATION] = NEW_SWITCHES
        kubectl("replace", "--dry-run=server", "-f", "-", data=json.dumps(proposed))
        print("服务端预检通过", flush=True)
        if args.health_url:
            baseline = command(["curl", "-sS", "--connect-timeout", "3", "--max-time", "8",
                                "-o", "/dev/null", "-w", "%{http_code}", args.health_url], required=False)
            if baseline.returncode or baseline.stdout != str(args.expected_status):
                raise RuntimeError("正式入口变更前状态不符合预期，停止迁移")
            print("正式入口基线", baseline.stdout, flush=True)
        if not args.execute:
            print("只读模式；未修改生产对象", flush=True)
            return

        kubectl("replace", "-f", "-", data=json.dumps(proposed))
        changed = deployment()
        generation = changed["metadata"]["generation"]
        print("已提交选址变更；等待 Pod 及入口同步", flush=True)

        try:
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                current = deployment()
                pods = active_pods()
                ips = [pod["status"].get("podIP") for pod in pods]
                ready = (current["status"].get("observedGeneration", 0) >= generation
                         and current["status"].get("readyReplicas") == 1)
                correct = len(ips) == 1 and ips[0] and any(ipaddress.ip_address(ips[0]) in network for network in NEW_CIDRS)
                if args.deployment.endswith("-worker") and len(remaining_pods()) != 1:
                    correct = False
                if current["metadata"]["generation"] != generation:
                    raise RuntimeError("迁移期间有人修改了同一 Deployment，停止自动处理")
                if ready and correct:
                    break
                time.sleep(5)
            else:
                raise RuntimeError("新 Pod 在 300 秒内未于目标网段达到单副本 Ready")

            if args.health_url:
                deadline = time.monotonic() + 120
                successes = 0
                while time.monotonic() < deadline:
                    result = command(["curl", "-sS", "--connect-timeout", "3", "--max-time", "8",
                                      "-o", "/dev/null", "-w", "%{http_code}", args.health_url], required=False)
                    successes = successes + 1 if result.returncode == 0 and result.stdout == str(args.expected_status) else 0
                    if successes >= 3:
                        break
                    time.sleep(5)
                else:
                    raise RuntimeError("正式入口在 120 秒内未连续三次返回预期状态")

            final = deployment()
            final_secrets = [v["secret"]["secretName"] for v in final["spec"]["template"]["spec"].get("volumes", []) if "secret" in v]
            if final["spec"]["template"]["spec"]["containers"][0]["image"] != image or final_secrets != secrets or final["spec"].get("replicas") != 1:
                raise RuntimeError("镜像、Secret 引用或副本数发生变化")
            print("迁移通过", args.namespace, args.deployment, "Pod IP", ips[0], "Ready 1/1", flush=True)
        except Exception as error:
            print("验收失败", str(error), flush=True)
            latest = deployment()
            if latest["metadata"]["generation"] != generation:
                raise RuntimeError("存在并发变更，未自动回退，请人工核对") from error
            annotations = latest["spec"]["template"]["metadata"].setdefault("annotations", {})
            if old_switches is None:
                annotations.pop(ANNOTATION, None)
            else:
                annotations[ANNOTATION] = old_switches
            kubectl("replace", "-f", "-", data=json.dumps(latest))
            print("已提交本 Deployment 原选址回退；须继续核对回退 Pod 和入口", flush=True)
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)

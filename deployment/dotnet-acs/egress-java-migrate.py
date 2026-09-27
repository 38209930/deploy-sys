#!/usr/bin/env python3
"""Java 单副本定时任务 API 的有序 Pod 网络交接。默认只读预检。"""

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
SWITCHES = "vsw-2zevd832gq3313j6gv5sj,vsw-2zesy6off4gy39tqripzp"
NETWORKS = (ipaddress.ip_network("172.31.240.0/24"), ipaddress.ip_network("172.28.64.0/24"))
TARGETS = {
    "stopmp-api": ("stopmp-api", "https://stop-mp-api.svision100.com/actuator/health"),
    "etbst-api": ("etbst-api", "https://et-bst-api.svision100.com/actuator/health"),
    "ddmp-api": ("ddmp-api", "https://ddmpapi.svision100.com/actuator/health"),
}


def run(args, *, data=None, check=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True, check=False, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} 失败：{result.stderr[:300]}")
    return result


def wait_until(predicate, seconds, failure):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(4)
    raise RuntimeError(failure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace", choices=TARGETS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    name, url = TARGETS[args.namespace]
    identity = json.loads(run(["aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE]).stdout)
    if identity.get("AccountId") != ACCOUNT:
        raise RuntimeError("阿里云账号不匹配")
    response = json.loads(run([
        "aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
        "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
        "--profile", PROFILE, "--region", "cn-beijing",
    ]).stdout)
    if response.get("Code") or not response.get("config"):
        raise RuntimeError("ACS 临时访问材料为空")
    with tempfile.TemporaryDirectory(prefix="acs-java-egress-") as directory:
        config = os.path.join(directory, "config")
        descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(response["config"])

        def kubectl(*cmd, data=None):
            return run(["kubectl", "--kubeconfig", config, "-n", args.namespace, *cmd], data=data).stdout

        def dep():
            return json.loads(kubectl("get", "deployment", name, "-o", "json"))

        def pods():
            rows = json.loads(kubectl("get", "pods", "-o", "json"))["items"]
            return [row for row in rows if row["metadata"]["name"].startswith(name + "-")
                    and row["status"].get("phase") not in ("Succeeded", "Failed")]

        def healthy():
            result = run(["curl", "-sS", "--connect-timeout", "3", "--max-time", "8",
                          "-o", "/dev/null", "-w", "%{http_code}", url], check=False)
            return result.returncode == 0 and result.stdout == "401"

        before = dep()
        old_pods = pods()
        old_value = before["spec"]["template"]["metadata"].get("annotations", {}).get(ANNOTATION)
        if old_value == SWITCHES:
            raise RuntimeError("目标已在新网段，停止重复迁移")
        if before["spec"].get("replicas") != 1 or before["status"].get("readyReplicas") != 1:
            raise RuntimeError("目标不是稳定的单副本")
        if len(old_pods) != 1 or not old_pods[0]["status"].get("podIP"):
            raise RuntimeError("旧 Pod 数量或 IP 异常")
        if not healthy():
            raise RuntimeError("正式入口基线不是 401，停止")
        original_image = [container["image"] for container in before["spec"]["template"]["spec"]["containers"]]
        original_secrets = [volume["secret"]["secretName"] for volume in before["spec"]["template"]["spec"].get("volumes", []) if "secret" in volume]
        old_strategy = before["spec"].get("strategy", {})
        print("预检通过", args.namespace, "旧 Pod", old_pods[0]["metadata"]["name"],
              "旧 IP", old_pods[0]["status"]["podIP"], "入口 401", flush=True)
        if not args.execute:
            return

        stage = "停止旧副本"
        try:
            current = dep()
            if current["metadata"]["resourceVersion"] != before["metadata"]["resourceVersion"]:
                raise RuntimeError("预检后 Deployment 发生并发变更")
            current["spec"]["replicas"] = 0
            kubectl("replace", "-f", "-", data=json.dumps(current))
            wait_until(lambda: dep()["status"].get("observedGeneration", 0) >= before["metadata"]["generation"] + 1
                       and not pods(), 180, "旧 Pod 未完全退出")
            print("旧 Pod 已完全退出", flush=True)

            stage = "切换选址"
            current = dep()
            if current["spec"].get("replicas") != 0:
                raise RuntimeError("副本不为零，停止选址变更")
            current["spec"]["template"]["metadata"].setdefault("annotations", {})[ANNOTATION] = SWITCHES
            current["spec"]["strategy"] = {"type": "Recreate"}
            kubectl("replace", "--dry-run=server", "-f", "-", data=json.dumps(current))
            kubectl("replace", "-f", "-", data=json.dumps(current))

            stage = "启动新副本"
            current = dep()
            current["spec"]["replicas"] = 1
            kubectl("replace", "-f", "-", data=json.dumps(current))

            def new_ready():
                live = dep()
                found = pods()
                if len(found) != 1 or live["status"].get("readyReplicas") != 1:
                    return None
                ip = found[0]["status"].get("podIP")
                if not ip or not any(ipaddress.ip_address(ip) in network for network in NETWORKS):
                    return None
                if found[0]["metadata"].get("uid") == old_pods[0]["metadata"].get("uid"):
                    return None
                return ip

            address = wait_until(new_ready, 300, "新 Pod 未在新网段 Ready")
            wait_until(healthy, 120, "正式入口未恢复 401")
            final = dep()
            final_image = [container["image"] for container in final["spec"]["template"]["spec"]["containers"]]
            final_secrets = [volume["secret"]["secretName"] for volume in final["spec"]["template"]["spec"].get("volumes", []) if "secret" in volume]
            if final_image != original_image or final_secrets != original_secrets:
                raise RuntimeError("镜像或 Secret 引用改变")
            if final["spec"].get("strategy", {}).get("type") != "Recreate":
                raise RuntimeError("Recreate 未保持")
            print("迁移完成", args.namespace, "新 IP", address, "Ready 1/1", "入口 401", flush=True)
        except Exception as error:
            print("迁移失败", stage, str(error), "尝试单项目回退", file=sys.stderr, flush=True)
            current = dep()
            live_value = current["spec"]["template"]["metadata"].get("annotations", {}).get(ANNOTATION)
            if live_value not in (old_value, SWITCHES):
                raise RuntimeError("选址发生第三方变更，不自动回退") from error
            current["spec"]["replicas"] = 0
            kubectl("replace", "-f", "-", data=json.dumps(current))
            wait_until(lambda: not pods(), 180, "新 Pod 未完全退出，不能恢复旧副本")
            current = dep()
            annotations = current["spec"]["template"]["metadata"].setdefault("annotations", {})
            if old_value is None:
                annotations.pop(ANNOTATION, None)
            else:
                annotations[ANNOTATION] = old_value
            current["spec"]["strategy"] = old_strategy
            kubectl("replace", "-f", "-", data=json.dumps(current))
            current = dep()
            current["spec"]["replicas"] = 1
            kubectl("replace", "-f", "-", data=json.dumps(current))
            wait_until(lambda: dep()["status"].get("readyReplicas") == 1 and len(pods()) == 1,
                       300, "旧 Pod 未恢复 Ready")
            wait_until(healthy, 120, "旧正式入口未恢复 401")
            print("原单副本与入口已恢复", flush=True)
            raise RuntimeError("迁移未完成；已回退本 Deployment") from error


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)

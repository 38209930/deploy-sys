#!/usr/bin/env python3
"""无需重启地修正 Java 单实例任务应用的 Deployment 策略与零副本选址。"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


PROFILE = "ruishi-prod-acr"
ACCOUNT = "1442361567788059"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
ANNOTATION = "network.alibabacloud.com/vswitch-ids"
SWITCHES = "vsw-2zevd832gq3313j6gv5sj,vsw-2zesy6off4gy39tqripzp"
TARGETS = {"yangu-api": 1, "dgye-api": 0, "vet-api": 0}


def run(*args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, check=False, timeout=60)
    if result.returncode:
        raise RuntimeError(f"{args[0]} 失败：{result.stderr[:300]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace", choices=TARGETS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    identity = json.loads(run("aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE))
    if identity.get("AccountId") != ACCOUNT:
        raise RuntimeError("生产账号不匹配")
    config_response = json.loads(run("aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
                                     "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
                                     "--profile", PROFILE, "--region", "cn-beijing"))
    if config_response.get("Code") or not config_response.get("config"):
        raise RuntimeError("ACS 临时访问材料为空")
    with tempfile.TemporaryDirectory(prefix="acs-java-template-") as directory:
        path = os.path.join(directory, "config")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(config_response["config"])

        def kubectl(*cmd, data=None):
            return run("kubectl", "--kubeconfig", path, "-n", args.namespace, *cmd, data=data)

        def dep():
            return json.loads(kubectl("get", "deployment", args.namespace, "-o", "json"))

        def pods():
            items = json.loads(kubectl("get", "pods", "-o", "json"))["items"]
            return [item for item in items if item["metadata"]["name"].startswith(args.namespace + "-")
                    and item["status"].get("phase") not in ("Succeeded", "Failed")]

        before = dep()
        expected = TARGETS[args.namespace]
        if before["spec"].get("replicas") != expected or before["status"].get("readyReplicas", 0) != expected:
            raise RuntimeError("副本状态与目标不符")
        found = pods()
        if len(found) != expected:
            raise RuntimeError("活动 Pod 数与副本不符")
        old_value = before["spec"]["template"]["metadata"].get("annotations", {}).get(ANNOTATION)
        if expected == 1 and old_value != SWITCHES:
            raise RuntimeError("运行目标未在新网段")
        if expected == 0 and old_value == SWITCHES and before["spec"].get("strategy", {}).get("type") == "Recreate":
            raise RuntimeError("零副本模板已是目标状态")
        updated = json.loads(json.dumps(before))
        updated["spec"]["template"]["metadata"].setdefault("annotations", {})[ANNOTATION] = SWITCHES
        updated["spec"]["strategy"] = {"type": "Recreate"}
        kubectl("replace", "--dry-run=server", "-f", "-", data=json.dumps(updated))
        print("预检通过", args.namespace, "副本", expected, "原选址", old_value,
              "原策略", before["spec"].get("strategy", {}).get("type"), flush=True)
        if not args.execute:
            return
        kubectl("replace", "-f", "-", data=json.dumps(updated))
        final = dep()
        final_pods = pods()
        if final["spec"].get("replicas") != expected or len(final_pods) != expected:
            raise RuntimeError("读回副本或 Pod 数发生变化")
        if final["spec"].get("strategy", {}).get("type") != "Recreate":
            raise RuntimeError("Recreate 未保持")
        if final["spec"]["template"]["metadata"]["annotations"].get(ANNOTATION) != SWITCHES:
            raise RuntimeError("目标选址未保持")
        if expected and found[0]["metadata"]["uid"] != final_pods[0]["metadata"]["uid"]:
            raise RuntimeError("运行中的 Yangu Pod 被意外替换")
        print("已读回", args.namespace, "副本", expected, "策略 Recreate；Pod 未增加", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"停止：{error}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""更新指定 ACS Deployment 的固定 digest 镜像，或按现网镜像重新部署。"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


ACCOUNT = "1442361567788059"
CLUSTER = "cebc88343a44b4d759aa983a47b787835"
PROFILE = "ruishi-prod-acr"
REGION = "cn-beijing"
IMAGE_PATTERN = r"ruishi-prod-registry-vpc\.cn-beijing\.cr\.aliyuncs\.com/ruishi-(java|dotnet)-prod/[a-z0-9-]+@sha256:[0-9a-f]{64}"


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} 执行失败（退出码 {result.returncode}）：{result.stderr[:300]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--container", required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--image")
    operation.add_argument("--restart", action="store_true", help="保留现网镜像与副本数，重新创建 Pod")
    parser.add_argument("--expected-replicas", type=int, required=True)
    args = parser.parse_args()
    for value in (args.namespace, args.deployment, args.container):
        if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", value):
            raise RuntimeError("目标名称格式无效")
    if args.image and not re.fullmatch(IMAGE_PATTERN, args.image):
        raise RuntimeError("镜像必须属于指定 ACR 仓库且固定 digest")
    if args.expected_replicas < 0:
        raise RuntimeError("预期副本数无效")
    if args.namespace in ("dgye-api", "vet-api") and args.expected_replicas != 0:
        raise RuntimeError("DGYE/VET 必须保持 0 副本")
    if args.restart and args.expected_replicas == 0:
        raise RuntimeError("0 副本服务不能重新部署，不改变停用状态")
    identity = json.loads(run("aliyun", "sts", "GetCallerIdentity", "--profile", PROFILE, "--region", REGION))
    if str(identity.get("AccountId")) != ACCOUNT:
        raise RuntimeError("阿里云账号不匹配")
    response = json.loads(run("aliyun", "cs", "DescribeClusterUserKubeconfig", "--ClusterId", CLUSTER,
                              "--PrivateIpAddress", "true", "--TemporaryDurationMinutes", "15",
                              "--profile", PROFILE, "--region", REGION))
    if not response.get("config"):
        raise RuntimeError("ACS 未返回临时访问配置")
    with tempfile.TemporaryDirectory(prefix="acs-image-") as directory:
        config = os.path.join(directory, "config")
        descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(response["config"])

        def kubectl(*params):
            return run("kubectl", "--kubeconfig", config, "-n", args.namespace, *params)

        versions = json.loads(kubectl("version", "-o", "json"))
        client = int(re.match(r"\d+", str(versions["clientVersion"]["minor"])).group())
        server = int(re.match(r"\d+", str(versions["serverVersion"]["minor"])).group())
        if abs(client - server) > 1:
            raise RuntimeError("kubectl 与 ACS API Server 次版本不兼容")
        current = json.loads(kubectl("get", "deployment", args.deployment, "-o", "json"))
        spec = current["spec"]
        replicas = spec.get("replicas", 1)
        containers = spec["template"]["spec"]["containers"]
        if (current["metadata"].get("name", args.deployment) != args.deployment
                or current["metadata"]["namespace"] != args.namespace or replicas != args.expected_replicas
                or len(containers) != 1 or containers[0]["name"] != args.container):
            raise RuntimeError("Deployment、容器或副本数与预期不一致")
        if args.restart:
            if spec.get("paused"):
                raise RuntimeError("Deployment 已暂停，不能重新部署")
            args.image = containers[0]["image"]
            if not re.fullmatch(IMAGE_PATTERN, args.image):
                raise RuntimeError("现网镜像未固定 digest，不能保证重启版本不变")
            status = current.get("status", {})
            if (status.get("observedGeneration", 0) < current["metadata"]["generation"]
                    or any(status.get(key, 0) != replicas for key in
                           ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"))):
                raise RuntimeError("Deployment 尚未完成上线，请等待就绪后重新部署")
        old_repo = containers[0]["image"].split("@sha256:")[0].split(":")[0]
        new_repo = args.image.split("@sha256:")[0]
        if old_repo != new_repo:
            raise RuntimeError("拟发布镜像仓库与现网不一致")
        already_current = containers[0]["image"] == args.image
        patch = [
            {"op": "test", "path": "/metadata/resourceVersion", "value": current["metadata"]["resourceVersion"]},
            {"op": "test", "path": "/spec/replicas", "value": replicas},
            {"op": "test", "path": "/spec/template/spec/containers/0/name", "value": args.container},
            {"op": "replace", "path": "/spec/template/spec/containers/0/image", "value": args.image},
        ]
        restarted_at = None
        if args.restart:
            restarted_at = datetime.now(timezone.utc).isoformat()
            annotations = dict(spec["template"].get("metadata", {}).get("annotations") or {})
            annotations["kubectl.kubernetes.io/restartedAt"] = restarted_at
            # resourceVersion 防止与其他发布竞争；只修改 Pod 模板注解。
            patch[-1] = {"op": "test", "path": "/spec/template/spec/containers/0/image", "value": args.image}
            if "metadata" not in spec["template"]:
                patch.append({"op": "add", "path": "/spec/template/metadata", "value": {"annotations": annotations}})
            else:
                patch.append({"op": "add", "path": "/spec/template/metadata/annotations", "value": annotations})
            kubectl("patch", "deployment", args.deployment, "--type=json", "-p", json.dumps(patch))
        elif already_current:
            print("镜像 digest 已在现网，继续检查 rollout 和副本状态")
        else:
            kubectl("patch", "deployment", args.deployment, "--type=json", "-p", json.dumps(patch))
        if replicas:
            kubectl("rollout", "status", f"deployment/{args.deployment}", "--timeout=300s")
        updated = json.loads(kubectl("get", "deployment", args.deployment, "-o", "json"))
        if restarted_at and updated["spec"]["template"].get("metadata", {}).get("annotations", {}).get("kubectl.kubernetes.io/restartedAt") != restarted_at:
            raise RuntimeError("重新部署注解回读不一致，可能发生并发发布")
        if (updated["spec"].get("replicas", 1) != replicas
                or updated["spec"]["template"]["spec"]["containers"][0]["image"] != args.image):
            raise RuntimeError("上线后镜像或副本数回读不一致")
        status = updated.get("status", {})
        if replicas and (status.get("observedGeneration", 0) < updated["metadata"]["generation"]
                         or status.get("updatedReplicas", 0) != replicas
                         or status.get("readyReplicas", 0) != replicas
                         or status.get("availableReplicas", 0) != replicas):
            raise RuntimeError("上线后 Deployment 尚未全部更新并就绪")
        operation_name = "service_restarted" if args.restart else "image_updated"
        print(f"{operation_name} namespace={args.namespace} deployment={args.deployment} replicas={replicas} image={args.image}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        print(f"上线失败：{exc}", file=sys.stderr)
        sys.exit(1)

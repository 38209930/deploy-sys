#!/usr/bin/env python3
"""只读核对 ACS 出口和指定 Deployment 的发布网络条件。"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


INVENTORY = Path(__file__).with_name("egress-network-inventory.yaml")
PROFILE = "ruishi-prod-acr"
ANNOTATION = "network.alibabacloud.com/vswitch-ids"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"命令失败：{' '.join(args[:3])}，退出码 {result.returncode}；{result.stderr[:300]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"命令返回非 JSON：{' '.join(args[:3])}") from exc
    if isinstance(data, dict) and (data.get("Code") or data.get("code")):
        raise RuntimeError(f"接口业务失败：{data.get('Code') or data.get('code')}")
    return data


def cloud(product, operation, inventory, *options):
    return run("aliyun", product, operation, *options, "--profile", PROFILE,
               "--region", inventory["region"])


def kube(kubeconfig, *args):
    return run("kubectl", "--kubeconfig", kubeconfig, *args, "-o", "json")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("deployment")
    parser.add_argument("--image", help="拟发布的完整 @sha256 digest；指定后按发布前门槛检查")
    args = parser.parse_args()
    inventory = yaml.safe_load(INVENTORY.read_text())
    item = inventory["namespaces"].get(args.namespace)
    require(item is not None and args.deployment in item["deployments"], "目标不在统一网络清单")
    if args.image:
        require(bool(re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", args.image)), "镜像必须为完整 digest")
        require(item["state"] == "already-on-nat", "目标尚未完成出口迁移，不允许镜像发布")

    identity = cloud("sts", "GetCallerIdentity", inventory)
    require(str(identity.get("AccountId")) == inventory["accountId"], "生产账号不匹配")
    nat = cloud("vpc", "DescribeNatGateways", inventory, "--RegionId", inventory["region"],
                "--NatGatewayId", inventory["natGatewayId"])
    gateways = nat.get("NatGateways", {}).get("NatGateway", [])
    require(len(gateways) == 1 and gateways[0].get("Status") == "Available"
            and gateways[0].get("BusinessStatus") == "Normal"
            and gateways[0].get("VpcId") == inventory["vpcId"], "NAT 状态或 VPC 异常")
    eip = cloud("vpc", "DescribeEipAddresses", inventory, "--RegionId", inventory["region"],
                "--EipAddress", inventory["egressEip"])
    addresses = eip.get("EipAddresses", {}).get("EipAddress", [])
    require(len(addresses) == 1 and addresses[0].get("Status") == "InUse"
            and addresses[0].get("InstanceId") == inventory["natGatewayId"], "EIP 绑定异常")
    snat = cloud("vpc", "DescribeSnatTableEntries", inventory, "--RegionId", inventory["region"],
                 "--NatGatewayId", inventory["natGatewayId"], "--PageSize", "50")
    entries = snat.get("SnatTableEntries", {}).get("SnatTableEntry", [])
    for vswitch in inventory["vswitches"]:
        require(any(entry.get("SourceVSwitchId") == vswitch["id"]
                    and entry.get("SourceCIDR") == vswitch["cidr"]
                    and entry.get("SnatIp") == inventory["egressEip"]
                    and entry.get("Status") == "Available" for entry in entries),
                f"SNAT 缺失：{vswitch['id']}")
        switch = cloud("vpc", "DescribeVSwitches", inventory, "--RegionId", inventory["region"],
                       "--VSwitchId", vswitch["id"])
        switches = switch.get("VSwitches", {}).get("VSwitch", [])
        require(len(switches) == 1 and switches[0].get("Status") == "Available"
                and switches[0].get("VpcId") == inventory["vpcId"]
                and switches[0].get("CidrBlock") == vswitch["cidr"]
                and switches[0].get("RouteTable", {}).get("RouteTableId") == inventory["egressRouteTableId"]
                and switches[0].get("AvailableIpAddressCount", 0) > 0,
                f"vSwitch 网段、路由或可用 IP 异常：{vswitch['id']}")
    routes = cloud("vpc", "DescribeRouteEntryList", inventory, "--RegionId", inventory["region"],
                   "--RouteTableId", inventory["egressRouteTableId"],
                   "--DestinationCidrBlock", "0.0.0.0/0")
    require(any(route.get("Status") == "Available" and
                any(hop.get("NextHopId") == inventory["natGatewayId"]
                    for hop in route.get("NextHops", {}).get("NextHop", []))
                for route in routes.get("RouteEntrys", {}).get("RouteEntry", [])),
            "新网段默认路由未指向 NAT")
    mongo = inventory["mongoPrivateRoute"]
    mongo_routes = cloud("vpc", "DescribeRouteEntryList", inventory, "--RegionId", inventory["region"],
                         "--RouteTableId", inventory["egressRouteTableId"],
                         "--DestinationCidrBlock", mongo["cidr"])
    require(any(route.get("Status") == "Available" and
                any(hop.get("NextHopId") == mongo["nextHopId"] and hop.get("NextHopType") == "VpcPeer"
                    for hop in route.get("NextHops", {}).get("NextHop", []))
                for route in mongo_routes.get("RouteEntrys", {}).get("RouteEntry", [])),
            "MongoDB 私网对等连接路由异常")

    config = cloud("cs", "DescribeClusterUserKubeconfig", inventory,
                   "--ClusterId", inventory["clusterId"], "--PrivateIpAddress", "true",
                   "--TemporaryDurationMinutes", "15")
    require(bool(config.get("config")), "ACS 临时访问材料为空")
    with tempfile.TemporaryDirectory(prefix="acs-egress-check-") as directory:
        kubeconfig = str(Path(directory) / "config")
        descriptor = os.open(kubeconfig, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(config["config"])
        versions = kube(kubeconfig, "version")
        client_minor = int(re.match(r"\d+", str(versions["clientVersion"]["minor"])).group())
        server_minor = int(re.match(r"\d+", str(versions["serverVersion"]["minor"])).group())
        require(abs(client_minor - server_minor) <= 1, "kubectl 与 API Server 超出支持的次版本偏差")
        deployment = kube(kubeconfig, "get", "deployment", args.deployment, "-n", args.namespace)
        require(deployment["metadata"]["namespace"] == args.namespace, "Deployment Namespace 不匹配")
        template = deployment["spec"]["template"]
        if args.image:
            containers = template["spec"]["containers"]
            require(len(containers) == 1, "多容器 Deployment 需明确目标容器，当前脚本不自动放行")
            current_repository = containers[0]["image"].split("@sha256:")[0].split(":")[0]
            proposed_repository = args.image.split("@sha256:")[0]
            require(proposed_repository == current_repository, "拟发布镜像仓库与现网不一致")
        selected = template.get("metadata", {}).get("annotations", {}).get(ANNOTATION)
        expected = {row["id"] for row in inventory["vswitches"]}
        if item["state"] == "already-on-nat":
            require(selected is not None and len(selected.split(",")) == 2
                    and set(selected.split(",")) == expected, "现网模板选址偏离新网段")
            profile = kube(kubeconfig, "get", "configmap", "acs-profile", "-n", "kube-system")
            selectors = yaml.safe_load(profile["data"]["selectors"])
            require(any(any(expr.get("key") == "kubernetes.io/metadata.name"
                                and expr.get("operator") == "In"
                                and args.namespace in expr.get("values", [])
                                for expr in selector.get("namespaceSelector", {}).get("matchExpressions", []))
                        and set(str(selector.get("effect", {}).get("annotations", {}).get(ANNOTATION, "")).split(",")) == expected
                        for selector in selectors), "Namespace 默认选址未覆盖目标")
            for kind in ("deployment", "pod"):
                name = f"ruishi-egress-{kind}-{args.namespace}"
                binding = kube(kubeconfig, "get", "validatingadmissionpolicybinding", name)
                require(binding["spec"]["policyName"] == f"ruishi-egress-{kind}-vswitch",
                        f"准入 Binding 异常：{name}")
                selector = binding["spec"].get("matchResources", {}).get("namespaceSelector", {})
                require(selector.get("matchLabels", {}).get("kubernetes.io/metadata.name") == args.namespace,
                        f"准入 Binding 范围异常：{name}")
            pods = kube(kubeconfig, "get", "pods", "-n", args.namespace)["items"]
            target_pods = [pod for pod in pods if pod["metadata"]["name"].startswith(args.deployment + "-")]
            require(bool(target_pods), "目标没有运行 Pod；零副本需专项发布流程")
            networks = [ipaddress.ip_network(row["cidr"]) for row in inventory["vswitches"]]
            for pod in target_pods:
                ip = pod.get("status", {}).get("podIP")
                require(ip and any(ipaddress.ip_address(ip) in network for network in networks)
                        and pod.get("status", {}).get("phase") == "Running",
                        f"目标 Pod 网络或状态异常：{pod['metadata']['name']}")
        if args.image:
            require(deployment["status"].get("readyReplicas", 0) == deployment["spec"].get("replicas", 1),
                    "发布前副本未全部 Ready")
            require(deployment["spec"].get("replicas", 1) > 0, "目标为零副本")
        print(json.dumps({"result": "pass", "accountId": identity["AccountId"],
                          "clusterId": inventory["clusterId"], "namespace": args.namespace,
                          "deployment": args.deployment, "state": item["state"],
                          "templateVswitches": selected, "natId": inventory["natGatewayId"],
                          "eip": inventory["egressEip"],
                          "resourceVersion": deployment["metadata"]["resourceVersion"]},
                         ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)

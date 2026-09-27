#!/usr/bin/env python3
"""将已核实的 Flow 服务与流水线 ID 写入本机私有菜单。"""

from pathlib import Path
import shlex
import yaml


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/projects.local.yaml"
FLOW = ROOT / "deployment/flow"
PROJECTS = {
    "yangu": ("Yangu", "java"),
    "m1x": ("M1X", "java"),
    "ddmp": ("DDMP", "java"),
    "stopmp": ("STOPMP", "java"),
    "dgye": ("DGYE", "java"),
    "vet": ("VET", "java"),
    "new-retail": ("新零售商城", "dotnet"),
    "points-mall": ("积分商城", "dotnet"),
    "service-order": ("售后工单系统", "dotnet"),
    "ai-study": ("AI自习室", "dotnet"),
    "agent-query": ("授权经销商", "dotnet"),
}
EXISTING = {
    "stopmp": "stop", "points-mall": "jifen", "new-retail": "newsale", "ai-study": "ai-study-room",
}
REMOVE = {
    "stopmp": {"api-new", "api", "api-restart"},
    "vet": {"api-new", "api", "api-restart"},
    "dgye": {"api-new", "api", "api-restart"},
    "ddmp": {"api-new", "api", "api-restart"},
    "m1x": {"m1x-api-new", "m1x-worker-new"},
    "new-retail": {"api", "back", "worker", "api-restart", "back-restart", "worker-restart", "services-restart"},
}
DROP_PROD = {
    "points-mall": {"api-back", "worker"},
    "service-order": {"api-front", "api-back", "worker"},
    "ai-study": {"API-BACK", "work-service"},
}


def env(**values):
    return " ".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def entry(sid, name, kind, command, status=None):
    commands = {"run": [f"cd {ROOT}", command]}
    if status:
        commands["status_commands"] = [f"cd {ROOT}", status]
    return {"id": sid, "name": name, "type": kind,
            "targets": {"prod": {"shell": "bash", "commands": commands}}}


def main():
    services = yaml.safe_load((FLOW / "services.yaml").read_text(encoding="utf-8"))["services"]
    ids = yaml.safe_load((FLOW / "pipeline-ids.yaml").read_text(encoding="utf-8"))["pipelines"]
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    projects = data["projects"]
    lookup = {project["id"]: project for project in projects}
    by_group = {}
    for service in services:
        by_group.setdefault(service["group"], []).append(service)

    for group, rows in by_group.items():
        project_id = EXISTING.get(group, group)
        project = lookup.get(project_id)
        if project is None:
            label, kind = PROJECTS[group]
            project = {"id": project_id, "name": label, "type": kind, "platform": "mac", "services": []}
            projects.append(project)
            lookup[project_id] = project
        if group == "stopmp":
            project["name"] = "STOPMP"
        retained = []
        for old in project["services"]:
            if old["id"].startswith("flow-"):
                continue
            if old["id"] in REMOVE.get(group, set()):
                continue
            if old["id"] in DROP_PROD.get(group, set()):
                old["targets"].pop("prod", None)
                if not old["targets"]:
                    continue
            retained.append(old)
        flow_entries = []
        for row in rows:
            sid, branch = row["id"], row["branch"]
            build_id, confirm_id = ids[sid]["build"], ids[sid]["confirm"]
            image_repo = ("ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/"
                          f"ruishi-{'java' if row['kind'] == 'java' else 'dotnet'}-prod/{sid}")
            status = env(FLOW_PIPELINE_ID=build_id, FLOW_SERVICE=sid) + " bash scripts/flow-release.sh status"
            push = env(FLOW_PIPELINE_ID=build_id, FLOW_SERVICE=sid, FLOW_REPO_DIR=row["repo_dir"],
                       FLOW_RELEASE_BRANCH=branch) + " bash scripts/flow-release.sh push"
            build = env(FLOW_PIPELINE_ID=build_id, FLOW_DEPLOY_PIPELINE_ID=confirm_id,
                        FLOW_RELEASE_BRANCH=branch, FLOW_ACR_INSTANCE_ID="cri-73ffxebpi6ruw6sn",
                        FLOW_ACR_REPO_ID=row["acr_id"], FLOW_IMAGE_REPO=image_repo, FLOW_SERVICE=sid,
                        FLOW_DEPLOY_MODE="local") + " bash scripts/flow-release.sh build"
            deploy = env(FLOW_DEPLOY_PIPELINE_ID=confirm_id, FLOW_SERVICE=sid, FLOW_DEPLOY_MODE="local",
                         FLOW_ACR_INSTANCE_ID="cri-73ffxebpi6ruw6sn", FLOW_ACR_REPO_ID=row["acr_id"],
                         FLOW_IMAGE_REPO=image_repo, FLOW_NAMESPACE=row["namespace"],
                         FLOW_DEPLOYMENT=row["deployment"], FLOW_CONTAINER=row["container"],
                         FLOW_EXPECTED_REPLICAS=row["replicas"], FLOW_CONFIRM="yes") + " bash scripts/flow-release.sh deploy"
            logs = ("python3 scripts/etbst-logs.py " +
                    " ".join(f"--{key.replace('_', '-')} {shlex.quote(row[key])}"
                             for key in ("namespace", "deployment", "container")))
            prefix = f"flow-{sid}"
            flow_entries.extend((
                entry(f"{prefix}-push", f"{row['name']} Flow 推送 {branch}", row["kind"], push, status),
                entry(f"{prefix}-build", f"{row['name']} Flow 构建", row["kind"], build, status),
                entry(f"{prefix}-deploy", f"{row['name']} Flow 上线", row["kind"], deploy,
                      env(FLOW_PIPELINE_ID=confirm_id, FLOW_SERVICE=sid) + " bash scripts/flow-release.sh status"),
                entry(f"{prefix}-logs", f"{row['name']} ACS 查看日志", row["kind"], logs),
            ))
        project["services"] = flow_entries + retained

    etbst = lookup["etbst"]
    for item in etbst["services"]:
        command = item["targets"]["prod"]["commands"]["run"]
        if item["id"] == "api-flow-deploy":
            image_repo = "ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/etbst-api"
            command[-1] = (env(FLOW_DEPLOY_PIPELINE_ID=5300396, FLOW_SERVICE="etbst-api", FLOW_DEPLOY_MODE="local",
                               FLOW_ACR_INSTANCE_ID="cri-73ffxebpi6ruw6sn", FLOW_ACR_REPO_ID="crr-gkqkb2np05u435bf",
                               FLOW_IMAGE_REPO=image_repo, FLOW_NAMESPACE="etbst-api", FLOW_DEPLOYMENT="etbst-api",
                               FLOW_CONTAINER="etbst-api", FLOW_EXPECTED_REPLICAS=1, FLOW_CONFIRM="yes")
                           + " bash scripts/flow-release.sh deploy")
    etbst_build = next(item for item in etbst["services"] if item["id"] == "api-flow-build")
    build_cmd = etbst_build["targets"]["prod"]["commands"]["run"]
    if "FLOW_DEPLOY_MODE=local" not in build_cmd[-1]:
        build_cmd[-1] = build_cmd[-1].replace(" bash scripts/flow-release.sh build", " FLOW_DEPLOY_MODE=local bash scripts/flow-release.sh build")

    order = ["etbst", "yangu", "m1x", "ddmp", "stop", "dgye", "vet", "newsale", "jifen",
             "service-order", "ai-study-room", "agent-query"]
    data["projects"] = [lookup[key] for key in order] + [p for p in projects if p["id"] not in order]
    CONFIG.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"updated={CONFIG} services={len(services)} projects={len(data['projects'])}")


if __name__ == "__main__":
    main()

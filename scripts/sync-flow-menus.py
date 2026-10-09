#!/usr/bin/env python3
"""将已核实的 Flow 服务与流水线 ID 写入本机私有菜单。"""

from pathlib import Path
import shlex
import yaml


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/projects.local.yaml"
FLOW = ROOT / "deployment/flow"
PROJECTS = {
    "etbst": ("ETBST", "java"),
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
    "etbst": {"api-flow-push", "api-flow-build", "api-flow-deploy", "api-acs-resources"},
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
    command_lines = list(command) if isinstance(command, (list, tuple)) else [command]
    target = {"shell": "bash", "commands": {"run": [f"cd {ROOT}", *command_lines]}}
    if status:
        status_lines = list(status) if isinstance(status, (list, tuple)) else [status]
        target["status_commands"] = [f"cd {ROOT}", *status_lines]
    return {"id": sid, "name": name, "type": kind,
            "targets": {"prod": target}}


def flow_entries(row, pipeline_ids):
    """每个 ACS 服务只有发布入口，状态查询放在同一目标。"""
    sid, branch = row["id"], row["branch"]
    build_id, confirm_id = pipeline_ids["build"], pipeline_ids["confirm"]
    image_repo = ("ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/"
                  f"ruishi-{'java' if row['kind'] == 'java' else 'dotnet'}-prod/{sid}")
    flow_status = env(FLOW_PIPELINE_ID=build_id, FLOW_SERVICE=sid) + " bash scripts/flow-release.sh status"
    confirm_status = env(FLOW_PIPELINE_ID=confirm_id, FLOW_SERVICE=sid) + " bash scripts/flow-release.sh status"
    resources = ("python3 scripts/acs-resource-usage.py " +
                 f"--namespace {shlex.quote(row['namespace'])} " +
                 f"--deployment {shlex.quote(row['deployment'])}")
    status = [flow_status, confirm_status, resources]
    build_values = dict(FLOW_PIPELINE_ID=build_id, FLOW_DEPLOY_PIPELINE_ID=confirm_id,
                        FLOW_RELEASE_BRANCH=branch, FLOW_ACR_INSTANCE_ID="cri-73ffxebpi6ruw6sn",
                        FLOW_ACR_REPO_ID=row["acr_id"], FLOW_IMAGE_REPO=image_repo,
                        FLOW_SERVICE=sid, FLOW_DEPLOY_MODE="local")
    if row["kind"] == "java":
        # Java 多模块首次构建的依赖解析可能接近默认的一小时本地等待上限。
        build_values["FLOW_BUILD_TIMEOUT"] = 7200
    build_values.update(FLOW_REPO_DIR=row["repo_dir"], FLOW_NAMESPACE=row["namespace"],
                        FLOW_DEPLOYMENT=row["deployment"], FLOW_CONTAINER=row["container"],
                        FLOW_EXPECTED_REPLICAS=row["replicas"], FLOW_CONFIRM="yes")
    command = env(**build_values) + " bash scripts/flow-release.sh release"
    prefix = f"flow-{sid}"
    item = entry(f"{prefix}-release", f"{row['name']} 发布", row["kind"], command, status)
    item['targets']['prod'].update(release_repos=[row['repo_dir']], release_required=True)
    return [item]


def update_menu(data, services, ids):
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
        generated_entries = []
        for row in rows:
            generated_entries.extend(flow_entries(row, ids[row["id"]]))
        project["services"] = generated_entries + retained

    order = ["etbst", "yangu", "m1x", "ddmp", "stop", "dgye", "vet", "newsale", "jifen",
             "service-order", "ai-study-room", "agent-query"]
    data["projects"] = [lookup[key] for key in order] + [p for p in projects if p["id"] not in order]
    configure_sources(data)
    return data


def configure_sources(data):
    """父目录包装脚本的源码目录须明确登记，避免在错误仓库切换分支。"""
    apollo = "/Volumes/SSD/work/mall/apollo/prod"
    sms = "/Volumes/SSD/work/mall/smscore"
    study = "/Volumes/SSD/work/mall/ai自习室/prod@aliyun"
    sources = {
        ('apollo', 'api-front'): [apollo + '/api.netcore-net10'],
        ('apollo', 'api-back'): [apollo + '/api.netcore-net10'],
        ('apollo', 'worker'): [apollo + '/api.netcore-net10'],
        ('apollo', 'admin-pc'): [apollo + '/pc'],
        ('sms-core', 'api-public'): [sms + '/sms-api'],
        ('sms-core', 'api-back'): [sms + '/sms-api'],
        ('sms-core', 'worker'): [sms + '/sms-api'],
        ('sms-core', 'admin-pc'): [sms + '/sms-admin'],
        ('ai-study-room', 'admin-oss'): [study + '/ai-study-store-admin'],
    }
    for project in data['projects']:
        for service in project.get('services', []):
            target = service.get('targets', {}).get('prod')
            if not target:
                continue
            key = (project['id'], service['id'])
            if key in sources:
                target.update(release_repos=sources[key], release_required=True)
            if key[0] == 'ai-study-room' and key[1] in ('API-front', 'admin-oss'):
                target['commands']['run'] = [line.replace(study + '/ai-study-api/RuishiStore', study + '/ai-study-api')
                                              for line in target['commands']['run']]
            if key == ('ai-study-room', 'admin-oss'):
                lines = target['commands']['run']
                if not any('AI_STUDY_ADMIN_ROOT=' in line for line in lines):
                    lines[-1] = env(AI_STUDY_ADMIN_ROOT=sources[key][0]) + ' ' + lines[-1]


def main():
    services = yaml.safe_load((FLOW / "services.yaml").read_text(encoding="utf-8"))["services"]
    ids = yaml.safe_load((FLOW / "pipeline-ids.yaml").read_text(encoding="utf-8"))["pipelines"]
    data = update_menu(yaml.safe_load(CONFIG.read_text(encoding="utf-8")), services, ids)
    CONFIG.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"updated={CONFIG} services={len(services)} projects={len(data['projects'])}")


if __name__ == "__main__":
    main()

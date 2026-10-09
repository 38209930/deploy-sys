#!/usr/bin/env python3
"""按 ACS 服务清单生成云效手动构建与人工确认流水线。"""

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "deployment/flow/services.yaml"
OUTPUT = ROOT / "deployment/flow/services"
ORG = "659a5cefd64a2eb2dceb72f3"
CODEUP = "xdghn746erjk8hdo"
ACR = "lhjkwns3zhj879ic"


def main():
    services = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]
    OUTPUT.mkdir(exist_ok=True)
    for service in services:
        sid = service["id"]
        dockerfile = service["dockerfile"]
        # Flow 默认以 Dockerfile 所在目录为构建上下文；多项目 .NET Dockerfile
        # 需要从仓库根目录 COPY 同级项目。
        context_path = "              contextPath: .\n" if "/" in dockerfile else ""
        namespace = "ruishi-java-prod" if service["kind"] == "java" else "ruishi-dotnet-prod"
        prep = ""
        if service["kind"] == "java":
            prep = f"""          prepare_public_dockerfile:
            name: 为公网构建机准备Dockerfile
            step: Command
            with:
              run: |
                set -eu
                test \"$(grep -c 'ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com' {dockerfile})\" -eq 2
                sed 's#ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com#ruishi-prod-registry.cn-beijing.cr.aliyuncs.com#g' {dockerfile} > Dockerfile.flow
                test \"$(grep -c 'ruishi-prod-registry.cn-beijing.cr.aliyuncs.com' Dockerfile.flow)\" -eq 2
"""
            # 构建源码必须自带并使用阿里云 Maven 设置；Flow 仅检查，不改 Maven 命令。
            prep += """                test -f maven-settings.xml
                grep -Eq '<mirrorOf>[[:space:]]*central[[:space:]]*</mirrorOf>' maven-settings.xml
                grep -Eq '<url>[[:space:]]*https://maven[.]aliyun[.]com/repository/public/?[[:space:]]*</url>' maven-settings.xml
                test "$(grep -c '^COPY maven-settings[.]xml maven-settings[.]xml' Dockerfile.flow)" -eq 1
                test "$(grep -c '^RUN mvn .* -s /build/maven-settings[.]xml ' Dockerfile.flow)" -eq 1
                echo 'maven_mirror_verified=aliyun-public source=dockerfile'
"""
            dockerfile = "Dockerfile.flow"
        build = f"""# pipeline-name: {sid}-手动构建
# 仅手动触发；push 不自动构建。
sources:
  source_repo:
    type: codeup
    name: {sid}
    endpoint: https://codeup.aliyun.com/{ORG}/{service['repo']}
    branch: {service['branch']}
    triggerEvents: []
    certificate:
      type: serviceConnection
      serviceConnection: {CODEUP}

stages:
  build_stage:
    name: 构建并推送镜像
    jobs:
      build_job:
        name: {sid}-镜像
        runsOn: public/cn-beijing
        steps:
{prep}          acr_push:
            name: 构建镜像并推送ACR企业版
            step: ACREEDockerBuild
            with:
              serviceConnection: {ACR}
              region: cn-beijing
              artifact: {sid.replace('-', '_')}_image
              instance: ruishi-prod
              namespace: {namespace}
              dockerRegistry: {sid}
              dockerTag: "${{DATETIME}}-${{CI_COMMIT_ID}}"
{context_path}              dockerfilePath: {dockerfile}
"""
        deploy = f"""# pipeline-name: {sid}-固定digest人工确认
# Flow 的 kubectl 1.27.9 不适配 ACS 1.36.1；确认后由本机 kubectl 执行镜像更新。
variables:
  - key: IMAGE_DIGEST_REF
    value: ""
  - key: SOURCE_COMMIT
    value: ""

stages:
  preflight_stage:
    name: 校验发布输入
    jobs:
      preflight_job:
        name: 校验镜像digest
        runsOn: public/cn-beijing
        steps:
          verify_digest:
            name: 校验目标镜像与源码提交
            step: Command
            with:
              run: |
                set -eu
                printf '%s' "$IMAGE_DIGEST_REF" | grep -Eq '^ruishi-prod-registry-vpc[.]cn-beijing[.]cr[.]aliyuncs[.]com/{namespace}/{sid}@sha256:[0-9a-f]{{64}}$'
                printf '%s' "$SOURCE_COMMIT" | grep -Eq '^[0-9a-f]{{40}}$'
                printf 'source_commit=%s\\nimage_digest_ref=%s\\n' "$SOURCE_COMMIT" "$IMAGE_DIGEST_REF"

  confirm_stage:
    name: 人工确认
    jobs:
      confirm_job:
        name: 上线前确认
        component: ManualValidate
        with:
          validatorType: users
          validateMethod: and
          validators:
            - 203420990220401362
"""
        (OUTPUT / f"pipeline-{sid}.yaml").write_text(build, encoding="utf-8")
        (OUTPUT / f"pipeline-{sid}-confirm.yaml").write_text(deploy, encoding="utf-8")
    print(f"generated={len(services)} build+confirm pairs")


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail

# 云效 Flow 远程发布命令：本地触发/跟踪 api、worker 服务的 ACS 发布流水线。
#
# 用法（环境变量参数化，仿 deploy-*-systemd.sh）：
#   FLOW_PIPELINE_ID=12345 bash scripts/flow-release.sh push    # 推送配置的源分支到 Codeup
#   FLOW_PIPELINE_ID=12345 FLOW_DEPLOY_PIPELINE_ID=67890 bash scripts/flow-release.sh build
#   FLOW_DEPLOY_PIPELINE_ID=67890 FLOW_CONFIRM=yes bash scripts/flow-release.sh deploy
#   FLOW_PIPELINE_ID=12345 bash scripts/flow-release.sh status  # 只读：最近运行状态
#   bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml    # 按 YAML 创建/更新流水线
#
# 认证：阿里云 CLI，显式 FLOW_PROFILE（默认 ruishi-prod-acr）。凭据失效时执行：
#   aliyun configure --profile ruishi-prod-acr
# 详细说明见 deployment/flow-release-commands.md。

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FLOW_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

FLOW_PROFILE="${FLOW_PROFILE:-ruishi-prod-acr}"
FLOW_REGION="${FLOW_REGION:-cn-beijing}"
FLOW_ENDPOINT="${FLOW_ENDPOINT:-devops.cn-hangzhou.aliyuncs.com}"
FLOW_ORG_ID="${FLOW_ORG_ID:-659a5cefd64a2eb2dceb72f3}"
FLOW_ACCOUNT_ID="${FLOW_ACCOUNT_ID:-1442361567788059}"
FLOW_RELEASE_BRANCH="${FLOW_RELEASE_BRANCH:-release}"
FLOW_BUILD_TIMEOUT="${FLOW_BUILD_TIMEOUT:-3600}"
FLOW_POLL_INTERVAL="${FLOW_POLL_INTERVAL:-15}"
FLOW_STATE_DIR="${FLOW_STATE_DIR:-$FLOW_ROOT/data/flow-state}"
FLOW_SERVICE="${FLOW_SERVICE:-service}"
FLOW_REPO_DIR="${FLOW_REPO_DIR:-}"
FLOW_DEPLOY_PIPELINE_ID="${FLOW_DEPLOY_PIPELINE_ID:-}"
FLOW_ACR_INSTANCE_ID="${FLOW_ACR_INSTANCE_ID:-}"
FLOW_ACR_REPO_ID="${FLOW_ACR_REPO_ID:-}"
FLOW_IMAGE_REPO="${FLOW_IMAGE_REPO:-}"
FLOW_DEPLOY_MODE="${FLOW_DEPLOY_MODE:-local}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

json_get() {
  # json_get <json字符串> <python表达式>，表达式返回字符串
  python3 -c '
import json, sys
data = json.loads(sys.argv[1])
expr = sys.argv[2]
value = eval(expr, {"__builtins__": {}}, {"d": data})
if value is None:
    value = ""
print(value)
' "$1" "$2"
}

check_prereqs() {
  command -v aliyun >/dev/null 2>&1 || fail "未安装 aliyun CLI（brew install aliyun-cli）"
  command -v python3 >/dev/null 2>&1 || fail "未安装 python3"
  command -v git >/dev/null 2>&1 || fail "未安装 git"
  aliyun configure list 2>/dev/null | awk '{print $1}' | grep -qx "$FLOW_PROFILE" \
    || fail "aliyun CLI 未配置 Profile $FLOW_PROFILE，执行: aliyun configure --profile $FLOW_PROFILE"
}

check_identity() {
  local resp account_id
  resp="$(aliyun sts GetCallerIdentity --profile "$FLOW_PROFILE" --region "$FLOW_REGION")" \
    || fail "STS 调用失败，Profile $FLOW_PROFILE 凭据可能失效，执行: aliyun configure --profile $FLOW_PROFILE"
  account_id="$(json_get "$resp" "d['AccountId']")"
  [ "$account_id" = "$FLOW_ACCOUNT_ID" ] \
    || fail "当前身份 AccountId=$account_id 不是 ${FLOW_ACCOUNT_ID}，禁止操作（检查 FLOW_PROFILE）"
  echo "identity_ok account=$account_id profile=$FLOW_PROFILE"
}

require_pipeline() {
  [[ "${FLOW_PIPELINE_ID:-}" =~ ^[0-9]+$ ]] \
    || fail "FLOW_PIPELINE_ID 未设置或不是数字（当前值: '${FLOW_PIPELINE_ID:-}'）。先按 deployment/flow-release-commands.md 清单创建流水线，再把流水线 ID 填入 config/projects.local.yaml 或环境变量"
}

flow() {
  aliyun devops "$@" --organizationId "$FLOW_ORG_ID" --endpoint "$FLOW_ENDPOINT" \
    --profile "$FLOW_PROFILE" --region "$FLOW_REGION"
}

write_state() {
  # write_state <key=value>...
  mkdir -p "$FLOW_STATE_DIR"
  local tmp
  tmp="$(mktemp "$FLOW_STATE_DIR/$FLOW_SERVICE.env.tmp.XXXXXX")"
  {
    echo "service=$FLOW_SERVICE"
    echo "pipeline_id=$FLOW_PIPELINE_ID"
    echo "updated_at=$(date '+%F %T')"
    for kv in "$@"; do echo "$kv"; done
  } >"$tmp"
  mv "$tmp" "$FLOW_STATE_DIR/$FLOW_SERVICE.env"
  echo "state_file=$FLOW_STATE_DIR/$FLOW_SERVICE.env"
}

pipeline_url() {
  echo "https://flow.aliyun.com/pipelines/$FLOW_PIPELINE_ID/builds?organizationId=$FLOW_ORG_ID"
}

# 轮询一次运行状态，输出 run_status <runId> <pipelineRun.status> <等待卡点jobId或空>
run_snapshot() {
  local run_id="$1" resp job_id job_status
  resp="$(flow GetPipelineRun --pipelineId "$FLOW_PIPELINE_ID" --pipelineRunId "$run_id")" || return 1
  local overall
  overall="$(json_get "$resp" "d['pipelineRun']['status']")"
  echo "$overall"
  if [ "$overall" = "RUNNING" ] || [ "$overall" = "WAITING" ]; then
    # 找等待人工确认的 job（状态含 WAIT/VALIDATE）
    job_info="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
for stage in d["pipelineRun"]["stages"]:
    for job in stage["stageInfo"]["jobs"]:
        status = str(job.get("status", ""))
        if "WAIT" in status.upper() or "VALIDATE" in status.upper():
            print("{} {} {}".format(job["id"], status, job["name"]))
' "$resp")"
    if [ -n "$job_info" ]; then
      echo "WAITING_JOB $job_info"
    fi
  fi
}

wait_run() {
  local run_id="$1" elapsed=0 snap overall waiting
  while :; do
    snap="$(run_snapshot "$run_id")" || fail "读取流水线运行 $run_id 状态失败"
    overall="$(printf '%s\n' "$snap" | head -1)"
    waiting="$(printf '%s\n' "$snap" | grep '^WAITING_JOB ' | head -1 || true)"
    if [ -n "$waiting" ]; then
      echo "等待人工确认：${waiting#WAITING_JOB }"
      echo "在云效控制台确认，或执行: FLOW_PIPELINE_ID=$FLOW_PIPELINE_ID FLOW_RUN_ID=$run_id FLOW_CONFIRM=yes bash scripts/flow-release.sh deploy"
      return 2
    fi
    case "$overall" in
      SUCCESS)
        echo "run_result=SUCCESS run_id=$run_id"
        return 0
        ;;
      FAIL|FAILED|CANCELED|CANCELLED)
        echo "run_result=$overall run_id=$run_id"
        return 1
        ;;
    esac
    if [ "$elapsed" -ge "$FLOW_BUILD_TIMEOUT" ]; then
      echo "run_result=TIMEOUT run_id=$run_id"
      return 1
    fi
    sleep "$FLOW_POLL_INTERVAL"
    elapsed=$((elapsed + FLOW_POLL_INTERVAL))
    echo "run_status=$overall elapsed=${elapsed}s"
  done
}

cmd_push() {
  [ -n "$FLOW_REPO_DIR" ] || fail "push 需要设置 FLOW_REPO_DIR（etbst 本地为 /Volumes/SSD/work/ddmp/prod/stopmp/etbst/etbst-api）"
  [ -d "$FLOW_REPO_DIR/.git" ] || fail "不是 git 仓库: $FLOW_REPO_DIR"
  # 仅推送已提交的目标分支 ref；工作区未提交文件不会进入本次推送。

  git -C "$FLOW_REPO_DIR" fetch origin "$FLOW_RELEASE_BRANCH" >/dev/null 2>&1 \
    || fail "git fetch origin $FLOW_RELEASE_BRANCH 失败，检查网络/凭据"
  local local_head remote_head
  local_head="$(git -C "$FLOW_REPO_DIR" rev-parse "refs/heads/$FLOW_RELEASE_BRANCH" 2>/dev/null)" \
    || fail "本地不存在 $FLOW_RELEASE_BRANCH 分支"
  remote_head="$(git -C "$FLOW_REPO_DIR" rev-parse "origin/$FLOW_RELEASE_BRANCH")"
  if [ "$local_head" != "$remote_head" ]; then
    git -C "$FLOW_REPO_DIR" merge-base --is-ancestor "$remote_head" "$local_head" \
      || fail "本地 $FLOW_RELEASE_BRANCH 不是 origin/$FLOW_RELEASE_BRANCH 的后代（远端有未合并提交），先合并"
  fi
  echo "push_target=origin/$FLOW_RELEASE_BRANCH commit=$local_head"
  if [ "$local_head" = "$remote_head" ]; then
    echo "本地与远端一致，无需推送"
  else
    git -C "$FLOW_REPO_DIR" push origin "$FLOW_RELEASE_BRANCH"
  fi
  write_state "pushed_commit=$local_head" "branch=$FLOW_RELEASE_BRANCH"
}

cmd_build() {
  check_identity
  require_pipeline
  local resp run_id
  if [ -n "${FLOW_BUILD_RUN_ID:-}" ]; then
    [[ "$FLOW_BUILD_RUN_ID" =~ ^[0-9]+$ ]] || fail "FLOW_BUILD_RUN_ID 不是数字"
    run_id="$FLOW_BUILD_RUN_ID"
    echo "build_resuming pipeline_id=$FLOW_PIPELINE_ID run_id=$run_id"
  else
    resp="$(flow StartPipelineRun --pipelineId "$FLOW_PIPELINE_ID" --body '{}')" \
      || fail "触发流水线失败（检查流水线 ID 与权限）"
    run_id="$(json_get "$resp" "d['pipelineRunId']")"
    [ -n "$run_id" ] || fail "未取到 pipelineRunId: $resp"
    echo "build_triggered pipeline_id=$FLOW_PIPELINE_ID run_id=$run_id"
  fi
  echo "pipeline_url=$(pipeline_url)"
  local rc=0
  wait_run "$run_id" || rc=$?
  if [ "$rc" -eq 2 ]; then
    # 卡在人工确认：保留状态后正常返回，由用户决定何时确认
    write_state "last_run_id=$run_id" "last_status=WAITING_CONFIRM"
    exit 0
  fi
  [ "$rc" -eq 0 ] || exit "$rc"
  if [ -z "$FLOW_DEPLOY_PIPELINE_ID" ]; then
    write_state "last_run_id=$run_id" "last_status=BUILD_SUCCESS"
    return
  fi
  [[ "$FLOW_DEPLOY_PIPELINE_ID" =~ ^[0-9]+$ ]] || fail "FLOW_DEPLOY_PIPELINE_ID 不是数字"
  [ -n "$FLOW_ACR_INSTANCE_ID" ] && [ -n "$FLOW_ACR_REPO_ID" ] && [ -n "$FLOW_IMAGE_REPO" ] \
    || fail "启动部署流水线需要 FLOW_ACR_INSTANCE_ID、FLOW_ACR_REPO_ID、FLOW_IMAGE_REPO"
  local run_detail tags evidence source_commit tag digest image_ref deploy_params deploy_resp deploy_run_id
  run_detail="$(flow GetPipelineRun --pipelineId "$FLOW_PIPELINE_ID" --pipelineRunId "$run_id")"
  tags="$(aliyun cr list-repo-tag --instance-id "$FLOW_ACR_INSTANCE_ID" --repo-id "$FLOW_ACR_REPO_ID" \
    --page-size 100 --page-no 1 --region "$FLOW_REGION" --profile "$FLOW_PROFILE")"
  evidence="$(python3 "$SCRIPT_DIR/flow-build-evidence.py" "$run_detail" "$tags" "$FLOW_RELEASE_BRANCH")" \
    || fail "无法唯一关联本次构建与 ACR 镜像"
  read -r source_commit tag digest <<<"$evidence"
  resp="$(aliyun cr get-repo-tag --instance-id "$FLOW_ACR_INSTANCE_ID" --repo-id "$FLOW_ACR_REPO_ID" \
    --tag "$tag" --region "$FLOW_REGION" --profile "$FLOW_PROFILE")"
  [ "$(json_get "$resp" "d['Digest']")" = "$digest" ] \
    && [ "$(json_get "$resp" "d['IsSuccess']")" = "True" ] \
    && [ "$(json_get "$resp" "d['Status']")" = "NORMAL" ] \
    || fail "ACR tag 回读失败、状态异常或 digest 不一致"
  image_ref="$FLOW_IMAGE_REPO@sha256:$digest"
  deploy_params="$(python3 - "$image_ref" "$source_commit" <<'PY'
import json, sys
print(json.dumps({"envs": {"IMAGE_DIGEST_REF": sys.argv[1], "SOURCE_COMMIT": sys.argv[2]}}))
PY
)"
  deploy_resp="$(flow StartPipelineRun --pipelineId "$FLOW_DEPLOY_PIPELINE_ID" --params "$deploy_params")" \
    || fail "镜像已构建，但启动部署流水线失败：tag=$tag digest=$digest"
  deploy_run_id="$(json_get "$deploy_resp" "d['pipelineRunId']")"
  [ -n "$deploy_run_id" ] || fail "未取得部署运行 ID"
  echo "image_verified commit=$source_commit tag=$tag digest=$digest"
  echo "deploy_triggered pipeline_id=$FLOW_DEPLOY_PIPELINE_ID run_id=$deploy_run_id"
  local build_pipeline_id="$FLOW_PIPELINE_ID"
  FLOW_PIPELINE_ID="$FLOW_DEPLOY_PIPELINE_ID"
  rc=0
  wait_run "$deploy_run_id" || rc=$?
  [ "$rc" -eq 2 ] || fail "部署流水线未停在人工确认卡点（状态码 $rc），请检查运行 $deploy_run_id"
  FLOW_PIPELINE_ID="$build_pipeline_id"
  write_state "last_run_id=$run_id" "last_status=WAITING_CONFIRM" \
    "deploy_pipeline_id=$FLOW_DEPLOY_PIPELINE_ID" "deploy_run_id=$deploy_run_id" \
    "source_commit=$source_commit" "image_tag=$tag" "image_ref=$image_ref"
}

cmd_deploy() {
  check_identity
  if [ -n "$FLOW_DEPLOY_PIPELINE_ID" ]; then FLOW_PIPELINE_ID="$FLOW_DEPLOY_PIPELINE_ID"; fi
  require_pipeline
  [ "${FLOW_CONFIRM:-no}" = "yes" ] || {
    echo "拒绝执行：deploy 会通过人工确认卡点并上线生产。"
    echo "确认无误后执行: FLOW_PIPELINE_ID=$FLOW_PIPELINE_ID FLOW_RUN_ID=<运行ID> FLOW_CONFIRM=yes bash scripts/flow-release.sh deploy"
    exit 1
  }
  [ "$FLOW_DEPLOY_MODE" = "local" ] || fail "上线必须使用本机兼容 kubectl 更新镜像"
  local run_id local_image_ref="" local_image_tag="" local_state_status="" local_source_commit=""
  if [ "$FLOW_DEPLOY_MODE" = "local" ]; then
    [ -n "$FLOW_IMAGE_REPO" ] && [ -n "$FLOW_ACR_INSTANCE_ID" ] && [ -n "$FLOW_ACR_REPO_ID" ] \
      && [ -n "${FLOW_NAMESPACE:-}" ] && [ -n "${FLOW_DEPLOYMENT:-}" ] && [ -n "${FLOW_CONTAINER:-}" ] \
      || fail "本机上线需要 ACR、镜像仓库及 ACS 目标参数"
    [ -f "$FLOW_STATE_DIR/$FLOW_SERVICE.env" ] || fail "没有本地待确认镜像记录"
    read -r local_state_status local_image_ref local_image_tag local_source_commit < <(python3 - "$FLOW_STATE_DIR/$FLOW_SERVICE.env" "$FLOW_PIPELINE_ID" "$FLOW_IMAGE_REPO" <<'PY'
import re, sys
data = dict(line.rstrip("\n").split("=", 1) for line in open(sys.argv[1]) if "=" in line)
status, image, tag = data.get("last_status", ""), data.get("image_ref", ""), data.get("image_tag", "")
if (data.get("deploy_pipeline_id") != sys.argv[2]
        or status not in ("WAITING_CONFIRM", "APPROVED_PENDING_DEPLOY")
        or not re.fullmatch(re.escape(sys.argv[3]) + r"@sha256:[0-9a-f]{64}", image)
        or not re.fullmatch(r"[A-Za-z0-9._-]+", tag)):
    raise SystemExit("本地待确认状态或镜像 digest 不匹配")
print(status, image, tag, data.get("source_commit", ""))
PY
) || fail "本地部署状态核验失败"
    [ -n "$local_image_ref" ] && [ -n "$local_image_tag" ] || fail "本地部署状态核验失败"
    local tag_detail
    tag_detail="$(aliyun cr get-repo-tag --instance-id "$FLOW_ACR_INSTANCE_ID" --repo-id "$FLOW_ACR_REPO_ID" \
      --tag "$local_image_tag" --region "$FLOW_REGION" --profile "$FLOW_PROFILE")" || fail "ACR tag 回读失败"
    [ "$(json_get "$tag_detail" "d['Digest']")" = "${local_image_ref##*@sha256:}" ] \
      && [ "$(json_get "$tag_detail" "d['IsSuccess']")" = "True" ] \
      && [ "$(json_get "$tag_detail" "d['Status']")" = "NORMAL" ] \
      || fail "ACR tag 与本地 digest 不匹配或状态异常"
  fi
  if [ -n "${FLOW_RUN_ID:-}" ]; then
    run_id="$FLOW_RUN_ID"
  elif [ -f "$FLOW_STATE_DIR/$FLOW_SERVICE.env" ]; then
    run_id="$(python3 - "$FLOW_STATE_DIR/$FLOW_SERVICE.env" "$FLOW_PIPELINE_ID" <<'PY'
import sys
data = dict(line.rstrip("\n").split("=", 1) for line in open(sys.argv[1]) if "=" in line)
if data.get("deploy_pipeline_id") != sys.argv[2] or data.get("last_status") not in ("WAITING_CONFIRM", "APPROVED_PENDING_DEPLOY"):
    raise SystemExit("本地状态没有对应的待确认部署运行")
print(data["deploy_run_id"])
PY
)" || fail "本地状态与部署流水线不匹配，需显式指定 FLOW_RUN_ID"
  else
    fail "没有本地待确认运行记录，需显式指定 FLOW_RUN_ID"
  fi
  [[ "$run_id" =~ ^[0-9]+$ ]] || fail "FLOW_RUN_ID 不是数字"
  if [ "$FLOW_DEPLOY_MODE" = "local" ]; then
    grep -qx "deploy_run_id=$run_id" "$FLOW_STATE_DIR/$FLOW_SERVICE.env" \
      || fail "指定运行 ID 与本地待确认状态不匹配"
  fi
  if [ "$local_state_status" != "APPROVED_PENDING_DEPLOY" ]; then
    local snap waiting job_id
    snap="$(run_snapshot "$run_id")"
    waiting="$(printf '%s\n' "$snap" | grep '^WAITING_JOB ' | head -1 || true)"
    [ -n "$waiting" ] || fail "运行 $run_id 当前没有等待确认的任务。用 bash scripts/flow-release.sh status 查看"
    job_id="$(printf '%s' "$waiting" | awk '{print $2}')"
    echo "approving run_id=$run_id job_id=$job_id"
    flow PassPipelineValidate --pipelineId "$FLOW_PIPELINE_ID" --pipelineRunId "$run_id" --jobId "$job_id" --body '{}' >/dev/null \
      || fail "通过确认卡点失败"
    if [ "$FLOW_DEPLOY_MODE" = "local" ]; then
      write_state "last_run_id=$run_id" "last_status=APPROVED_PENDING_DEPLOY" \
        "deploy_pipeline_id=$FLOW_PIPELINE_ID" "deploy_run_id=$run_id" \
        "image_ref=$local_image_ref" "image_tag=$local_image_tag" "source_commit=$local_source_commit"
    fi
    local rc=0
    wait_run "$run_id" || rc=$?
    [ "$rc" -eq 0 ] || exit "$rc"
  elif [ "$(run_snapshot "$run_id" | head -1)" != "SUCCESS" ]; then
    fail "确认流水线尚未成功，不能更新 ACS 镜像"
  fi
  if [ "$FLOW_DEPLOY_MODE" = "local" ]; then
    python3 "$SCRIPT_DIR/acs-image-deploy.py" \
      --namespace "$FLOW_NAMESPACE" --deployment "$FLOW_DEPLOYMENT" \
      --container "$FLOW_CONTAINER" --image "$local_image_ref" \
      --expected-replicas "${FLOW_EXPECTED_REPLICAS:-1}"
  fi
  write_state "last_run_id=$run_id" "last_status=DEPLOY_SUCCESS" "source_commit=$local_source_commit"
}

cmd_status() {
  check_identity
  require_pipeline
  echo "pipeline_id=$FLOW_PIPELINE_ID url=$(pipeline_url)"
  local resp
  resp="$(flow ListPipelineRuns --pipelineId "$FLOW_PIPELINE_ID" --maxResults 5)"
  python3 -c '
import json, sys
from datetime import datetime
d = json.loads(sys.argv[1])
runs = d.get("pipelineRuns") or []
if not runs:
    print("（该流水线还没有运行记录）")
for r in runs:
    ts = datetime.fromtimestamp(r["startTime"] / 1000).strftime("%F %T")
    print("run={} status={} trigger={} time={}".format(r["pipelineRunId"], r["status"], r.get("triggerMode", ""), ts))
' "$resp"
  if [ -f "$FLOW_STATE_DIR/$FLOW_SERVICE.env" ]; then
    echo "--- 本地状态 ---"
    cat "$FLOW_STATE_DIR/$FLOW_SERVICE.env"
  fi
}

cmd_apply() {
  check_identity
  local yaml_file="${1:-}"
  [ -n "$yaml_file" ] || fail "apply 需要流水线 YAML 文件路径，例如: bash scripts/flow-release.sh apply deployment/flow/pipeline-etbst-api.yaml"
  [ -f "$yaml_file" ] || fail "文件不存在: $yaml_file"
  local name content body resp
  name="$(grep -m1 '^# pipeline-name:' "$yaml_file" | sed 's/^# pipeline-name:[[:space:]]*//')"
  [ -n "$name" ] || fail "YAML 第一屏需包含 '# pipeline-name: <流水线名>'"
  if python3 - "$yaml_file" <<'PY'
import re
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text().splitlines():
    if re.search(r"<[A-Z][A-Z0-9_]*>", line.split("#", 1)[0]):
        sys.exit(0)
sys.exit(1)
PY
  then
    fail "YAML 仍有待替换占位符，先完成服务连接和步骤配置后再 apply"
  fi
  content="$(cat "$yaml_file")"
  body="$(python3 -c '
import json, sys
print(json.dumps({"name": sys.argv[1], "content": sys.argv[2]}))
' "$name" "$content")"
  if [ -n "${FLOW_PIPELINE_ID:-}" ] && [ "$FLOW_PIPELINE_ID" != "0" ]; then
    body="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1]); d["pipelineId"] = int(sys.argv[2]); print(json.dumps(d))
' "$body" "$FLOW_PIPELINE_ID")"
    resp="$(flow UpdatePipeline --body "$body")" || fail "更新流水线失败"
    echo "pipeline_updated id=$FLOW_PIPELINE_ID"
  else
    resp="$(flow CreatePipeline --body "$body")" || fail "创建流水线失败（常见原因：YAML 中的服务连接 ID 无效或无权限）"
    local new_id
    new_id="$(json_get "$resp" "d['pipelinId'] or d['pipelineId']")"
    echo "pipeline_created id=$new_id"
    echo "下一步：把该 ID 写入 config/projects.local.yaml 的 FLOW_PIPELINE_ID"
  fi
}

case "${1:-}" in
  push) shift; cmd_push "$@" ;;
  build) shift; cmd_build "$@" ;;
  deploy) shift; cmd_deploy "$@" ;;
  status) shift; cmd_status "$@" ;;
  apply) shift; cmd_apply "$@" ;;
  *)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac

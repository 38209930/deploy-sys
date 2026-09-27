#!/usr/bin/env bash
set -euo pipefail

# 云效 Flow 远程发布命令：本地触发/跟踪 api、worker 服务的 ACS 发布流水线。
#
# 用法（环境变量参数化，仿 deploy-*-systemd.sh）：
#   FLOW_PIPELINE_ID=12345 bash scripts/flow-release.sh push    # 推送本地 release 分支到 Codeup
#   FLOW_PIPELINE_ID=12345 bash scripts/flow-release.sh build   # 触发流水线构建并等待结束（不推送）
#   FLOW_PIPELINE_ID=12345 FLOW_CONFIRM=yes bash scripts/flow-release.sh deploy   # 通过人工卡点并等待部署结束
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
FLOW_ORG_ID="${FLOW_ORG_ID:-658d5b8ae7f9ce3ec8199dc0}"
FLOW_ACCOUNT_ID="${FLOW_ACCOUNT_ID:-1442361567788059}"
FLOW_RELEASE_BRANCH="${FLOW_RELEASE_BRANCH:-release}"
FLOW_BUILD_TIMEOUT="${FLOW_BUILD_TIMEOUT:-3600}"
FLOW_POLL_INTERVAL="${FLOW_POLL_INTERVAL:-15}"
FLOW_STATE_DIR="${FLOW_STATE_DIR:-$FLOW_ROOT/data/flow-state}"
FLOW_SERVICE="${FLOW_SERVICE:-service}"
FLOW_REPO_DIR="${FLOW_REPO_DIR:-}"

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
    || fail "当前身份 AccountId=$account_id 不是 $FLOW_ACCOUNT_ID，禁止操作（检查 FLOW_PROFILE）"
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
  if [ "$overall" = "RUNNING" ]; then
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
      FAILED|CANCELED)
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
  [ -z "$(git -C "$FLOW_REPO_DIR" status --porcelain)" ] || fail "工作区有未提交修改，先处理: $FLOW_REPO_DIR"

  git -C "$FLOW_REPO_DIR" fetch origin "$FLOW_RELEASE_BRANCH" >/dev/null 2>&1 \
    || fail "git fetch origin $FLOW_RELEASE_BRANCH 失败，检查网络/凭据"
  local local_head remote_head
  local_head="$(git -C "$FLOW_REPO_DIR" rev-parse "refs/heads/$FLOW_RELEASE_BRANCH" 2>/dev/null)" \
    || fail "本地不存在 $FLOW_RELEASE_BRANCH 分支"
  remote_head="$(git -C "$FLOW_REPO_DIR" rev-parse "origin/$FLOW_RELEASE_BRANCH")"
  if [ "$local_head" != "$remote_head" ]; then
    git -C "$FLOW_REPO_DIR" merge-base --is-ancestor "$remote_head" "$local_head" \
      || fail "本地 $FLOW_RELEASE_BRANCH 不是 origin/$FLOW_RELEASE_BRANCH 的后代（远端有未合并提交），先合并或确认 FLOW_FORCE_PUSH=1"
  fi
  echo "push_target=origin/$FLOW_RELEASE_BRANCH commit=$local_head"
  if [ "$local_head" = "$remote_head" ]; then
    echo "本地与远端一致，无需推送"
  else
    if [ "${FLOW_FORCE_PUSH:-0}" = "1" ]; then
      git -C "$FLOW_REPO_DIR" push origin "$FLOW_RELEASE_BRANCH" --force-with-lease
    else
      git -C "$FLOW_REPO_DIR" push origin "$FLOW_RELEASE_BRANCH"
    fi
  fi
  write_state "pushed_commit=$local_head" "branch=$FLOW_RELEASE_BRANCH"
}

cmd_build() {
  check_identity
  require_pipeline
  local resp run_id
  resp="$(flow StartPipelineRun --pipelineId "$FLOW_PIPELINE_ID" --body '{}')" \
    || fail "触发流水线失败（检查流水线 ID 与权限）"
  run_id="$(json_get "$resp" "d['pipelineRunId']")"
  [ -n "$run_id" ] || fail "未取到 pipelineRunId: $resp"
  echo "build_triggered pipeline_id=$FLOW_PIPELINE_ID run_id=$run_id"
  echo "pipeline_url=$(pipeline_url)"
  local rc=0
  wait_run "$run_id" || rc=$?
  if [ "$rc" -eq 2 ]; then
    # 卡在人工确认：保留状态后正常返回，由用户决定何时确认
    write_state "last_run_id=$run_id" "last_status=WAITING_CONFIRM"
    exit 0
  fi
  [ "$rc" -eq 0 ] || exit "$rc"
  write_state "last_run_id=$run_id" "last_status=SUCCESS"
}

cmd_deploy() {
  check_identity
  require_pipeline
  [ "${FLOW_CONFIRM:-no}" = "yes" ] || {
    echo "拒绝执行：deploy 会通过人工确认卡点并上线生产。"
    echo "确认无误后执行: FLOW_PIPELINE_ID=$FLOW_PIPELINE_ID FLOW_RUN_ID=<运行ID> FLOW_CONFIRM=yes bash scripts/flow-release.sh deploy"
    exit 1
  }
  local run_id
  if [ -n "${FLOW_RUN_ID:-}" ]; then
    run_id="$FLOW_RUN_ID"
  else
    run_id="$(latest_running_run)" || fail "未找到等待确认的运行，可用 FLOW_RUN_ID 显式指定"
  fi
  local snap waiting job_id
  snap="$(run_snapshot "$run_id")"
  waiting="$(printf '%s\n' "$snap" | grep '^WAITING_JOB ' | head -1 || true)"
  [ -n "$waiting" ] || fail "运行 $run_id 当前没有等待确认的任务。用 bash scripts/flow-release.sh status 查看"
  job_id="$(printf '%s' "$waiting" | awk '{print $2}')"
  echo "approving run_id=$run_id job_id=$job_id"
  flow PassPipelineValidate --pipelineId "$FLOW_PIPELINE_ID" --pipelineRunId "$run_id" --jobId "$job_id" --body '{}' >/dev/null \
    || fail "通过确认卡点失败"
  local rc=0
  wait_run "$run_id" || rc=$?
  [ "$rc" -eq 0 ] || exit "$rc"
  write_state "last_run_id=$run_id" "last_status=DEPLOY_SUCCESS"
}

latest_running_run() {
  local resp run_id status
  resp="$(flow ListPipelineRuns --pipelineId "$FLOW_PIPELINE_ID" --pageNumber 1 --pageSize 10)"
  run_id="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
for r in d.get("pipelineRunList") or []:
    if str(r.get("status", "")).upper() == "RUNNING":
        print(r["pipelineRunId"]); break
' "$resp")"
  [ -n "$run_id" ] || return 1
  echo "$run_id"
}

cmd_status() {
  check_identity
  require_pipeline
  echo "pipeline_id=$FLOW_PIPELINE_ID url=$(pipeline_url)"
  local resp
  resp="$(flow ListPipelineRuns --pipelineId "$FLOW_PIPELINE_ID" --pageNumber 1 --pageSize 5)"
  python3 -c '
import json, sys
from datetime import datetime
d = json.loads(sys.argv[1])
runs = d.get("pipelineRunList") or []
if not runs:
    print("（该流水线还没有运行记录）")
for r in runs:
    ts = datetime.fromtimestamp(r["createTime"] / 1000).strftime("%F %T")
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
    if re.search(r"<[^<>]+>", line.split("#", 1)[0]):
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

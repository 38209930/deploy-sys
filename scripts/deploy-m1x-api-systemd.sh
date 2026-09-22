#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
REPO_DIR="${M1X_REPO_DIR:-}"
DEPLOY_HOST="${M1X_DEPLOY_HOST:-}"
DEPLOY_USER="${M1X_DEPLOY_USER:-deploy}"
SSH_KEY="${M1X_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}"
KNOWN_HOSTS="${M1X_KNOWN_HOSTS:-}"
BRANCH="${M1X_BRANCH:-feature/api-worker-separation}"
EXPECTED_COMMIT="${M1X_EXPECTED_COMMIT:-}"
JAVA8_HOME="${M1X_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
REMOTE_JAR="${M1X_REMOTE_JAR:-/home/api/app/m1x-api.jar}"
REMOTE_CONFIG="${M1X_REMOTE_CONFIG:-/home/api/config/application-prod.yml}"
API_SERVICE="${M1X_API_SERVICE:-m1x-api.service}"
WORKER_SERVICE="${M1X_WORKER_SERVICE:-m1x-worker.service}"
HEALTH_PORT="${M1X_HEALTH_PORT:-8080}"
HEALTH_PATH="${M1X_HEALTH_PATH:-/actuator/health}"
READY_ATTEMPTS="${M1X_READY_ATTEMPTS:-30}"

usage() {
  echo "Usage: M1X_REPO_DIR=... M1X_DEPLOY_HOST=... M1X_KNOWN_HOSTS=... $0 <deploy|status>" >&2
  exit 2
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_value() {
  local name="$1"
  local value="$2"
  [ -n "$value" ] || fail "missing environment variable: $name"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

init_connection() {
  require_value M1X_DEPLOY_HOST "$DEPLOY_HOST"
  require_value M1X_KNOWN_HOSTS "$KNOWN_HOSTS"
  [ -r "$SSH_KEY" ] || fail "SSH key is not readable: $SSH_KEY"
  [ -r "$KNOWN_HOSTS" ] || fail "known-hosts file is not readable: $KNOWN_HOSTS"
  require_command ssh
  require_command scp

  SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
  SSH_OPTIONS=(
    -i "$SSH_KEY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="$KNOWN_HOSTS"
    -o GlobalKnownHostsFile=/dev/null
    -o HostKeyAlgorithms=ssh-ed25519
    -o ConnectTimeout=10
    -o LogLevel=ERROR
  )
}

remote_status() {
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- \
    "$API_SERVICE" "$WORKER_SERVICE" "$REMOTE_JAR" "$HEALTH_PORT" "$HEALTH_PATH" <<'REMOTE'
set -euo pipefail
api_service="$1"
worker_service="$2"
remote_jar="$3"
health_port="$4"
health_path="$5"

api_enabled="$(systemctl is-enabled "$api_service" 2>/dev/null || true)"
api_active="$(systemctl is-active "$api_service" 2>/dev/null || true)"
worker_enabled="$(systemctl is-enabled "$worker_service" 2>/dev/null || true)"
worker_active="$(systemctl is-active "$worker_service" 2>/dev/null || true)"

echo "api_enabled=$api_enabled"
echo "api_active=$api_active"
echo "worker_enabled=$worker_enabled"
echo "worker_active=$worker_active"

[ "$api_active" = "active" ] || exit 1
health_body="$(curl -fsS --max-time 10 "http://127.0.0.1:${health_port}${health_path}")" || {
  echo "ERROR: API health check failed" >&2
  exit 1
}
printf '%s' "$health_body" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"UP"' || {
  echo "ERROR: API health is not UP" >&2
  exit 1
}

pid="$(systemctl show "$api_service" -p MainPID --value)"
[ "$pid" -gt 0 ] 2>/dev/null || {
  echo "ERROR: API MainPID is invalid" >&2
  exit 1
}
listener="$(sudo ss -lntp | grep -E ":${health_port}[[:space:]]" || true)"
printf '%s\n' "$listener" | grep -q "pid=${pid}," || {
  echo "ERROR: port ${health_port} is not owned by API pid ${pid}" >&2
  exit 1
}

scheduler_matches="$({ sudo grep -ERic 'ScheduledAnnotationBeanPostProcessor|定时任务|scheduled task|worker scheduling enabled|注册.*任务' /home/api/logs 2>/dev/null || true; } | awk -F: '{s+=$NF} END{print s+0}')"
[ "$scheduler_matches" -eq 0 ] || {
  echo "ERROR: scheduler markers found in API logs: $scheduler_matches" >&2
  exit 1
}

jar_sha="$(sudo sha256sum "$remote_jar" | awk '{print $1}')"
echo 'health={"status":"UP"}'
echo "pid=$pid"
echo "port=$health_port"
echo "jar_sha256=$jar_sha"
echo "scheduler_matches=$scheduler_matches"
REMOTE
}

build_api() {
  require_value M1X_REPO_DIR "$REPO_DIR"
  require_command git
  git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "M1X repository/worktree not found: $REPO_DIR"
  [ -x "$JAVA8_HOME/bin/java" ] || fail "JDK 8 not found: $JAVA8_HOME"
  require_command mvn
  require_command sha256sum

  [ -z "$(git -C "$REPO_DIR" status --porcelain)" ] || fail "repository is dirty: $REPO_DIR"
  current_branch="$(git -C "$REPO_DIR" symbolic-ref --short HEAD)"
  [ "$current_branch" = "$BRANCH" ] || fail "expected branch $BRANCH, found $current_branch"

  git -C "$REPO_DIR" fetch origin "$BRANCH"
  local_head="$(git -C "$REPO_DIR" rev-parse HEAD)"
  remote_head="$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")"
  [ "$local_head" = "$remote_head" ] || fail "local HEAD does not match origin/$BRANCH"
  if [ -n "$EXPECTED_COMMIT" ]; then
    [ "$local_head" = "$EXPECTED_COMMIT" ] || fail "HEAD does not match M1X_EXPECTED_COMMIT"
  fi

  java_version="$("$JAVA8_HOME/bin/java" -version 2>&1 | head -n 1)"
  printf '%s\n' "$java_version" | grep -q '1\.8' || fail "M1X_JAVA_HOME is not JDK 8"

  (
    cd "$REPO_DIR"
    JAVA_HOME="$JAVA8_HOME" PATH="$JAVA8_HOME/bin:$PATH" mvn -B -Dstyle.color=never clean verify
  )

  LOCAL_JAR="$REPO_DIR/train-web/target/train-web-test-1.0.2.jar"
  [ -f "$LOCAL_JAR" ] || fail "API artifact not found: $LOCAL_JAR"
  LOCAL_SHA="$(sha256sum "$LOCAL_JAR" | awk '{print $1}')"
  RELEASE_ID="$(date +%Y%m%d-%H%M%S)-$(git -C "$REPO_DIR" rev-parse --short HEAD)"
  REMOTE_STAGE="/home/deploy/m1x-api.${RELEASE_ID}.jar.upload"
}

remote_deploy() {
  scp "${SSH_OPTIONS[@]}" "$LOCAL_JAR" "$SSH_TARGET:$REMOTE_STAGE"

  if ! ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- \
    "$API_SERVICE" "$WORKER_SERVICE" "$REMOTE_JAR" "$REMOTE_CONFIG" \
    "$REMOTE_STAGE" "$LOCAL_SHA" "$RELEASE_ID" "$HEALTH_PORT" "$HEALTH_PATH" "$READY_ATTEMPTS" <<'REMOTE'
set -euo pipefail
api_service="$1"
worker_service="$2"
remote_jar="$3"
remote_config="$4"
remote_stage="$5"
expected_sha="$6"
release_id="$7"
health_port="$8"
health_path="$9"
ready_attempts="${10}"
backup_dir="$(dirname "$remote_jar")/backups"
backup="$backup_dir/$(basename "$remote_jar").${release_id}.bak"

cleanup_stage() {
  [ ! -e "$remote_stage" ] || unlink "$remote_stage"
}
trap cleanup_stage EXIT

sudo test -f "$remote_config" || { echo "ERROR: production config is missing" >&2; exit 1; }
[ -f "$remote_stage" ] || { echo "ERROR: staged jar is missing" >&2; exit 1; }
stage_sha="$(sha256sum "$remote_stage" | awk '{print $1}')"
[ "$stage_sha" = "$expected_sha" ] || { echo "ERROR: staged jar SHA-256 mismatch" >&2; exit 1; }
sudo test -f "$remote_jar" || { echo "ERROR: current API jar is missing" >&2; exit 1; }

sudo mkdir -p "$backup_dir"
sudo cp -p "$remote_jar" "$backup"
sudo systemctl stop "$api_service"
sudo install -o root -g m1x-api -m 0640 "$remote_stage" "$remote_jar"

rollback() {
  echo "API validation failed; restoring previous jar" >&2
  sudo systemctl stop "$api_service" || true
  sudo cp -p "$backup" "$remote_jar"
  sudo systemctl start "$api_service"
}

sudo systemctl start "$api_service"
ready=no
for _ in $(seq 1 "$ready_attempts"); do
  if ! systemctl is-active --quiet "$api_service"; then break; fi
  body="$(curl -fsS --max-time 3 "http://127.0.0.1:${health_port}${health_path}" 2>/dev/null || true)"
  if printf '%s' "$body" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"UP"'; then
    ready=yes
    break
  fi
  sleep 2
done

if [ "$ready" != yes ]; then
  rollback
  exit 1
fi

running_sha="$(sudo sha256sum "$remote_jar" | awk '{print $1}')"
if [ "$running_sha" != "$expected_sha" ]; then
  rollback
  echo "ERROR: running API jar SHA-256 mismatch" >&2
  exit 1
fi

scheduler_matches="$({ sudo grep -ERic 'ScheduledAnnotationBeanPostProcessor|定时任务|scheduled task|worker scheduling enabled|注册.*任务' /home/api/logs 2>/dev/null || true; } | awk -F: '{s+=$NF} END{print s+0}')"
if [ "$scheduler_matches" -ne 0 ]; then
  rollback
  echo "ERROR: scheduler markers found in API logs" >&2
  exit 1
fi

sudo systemctl enable "$api_service" >/dev/null
echo "release_id=$release_id"
echo "backup=$backup"
echo "jar_sha256=$running_sha"
REMOTE
  then
    fail "M1X API deployment failed; inspect server state before retrying"
  fi
}

case "$ACTION" in
  status)
    init_connection
    remote_status
    ;;
  deploy)
    init_connection
    build_api
    remote_deploy
    remote_status
    ;;
  *)
    usage
    ;;
esac

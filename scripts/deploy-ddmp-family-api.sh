#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
REPO_DIR="${DEPLOY_API_REPO:-}"
AUTH_JS="${DEPLOY_AUTH_JS:-}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/workspace/disthub/ruishi-api-test}"
REMOTE_JAR="${DEPLOY_REMOTE_JAR:-train-web-test-1.0.2.jar}"
PROFILE="${DEPLOY_PROFILE:-prod}"
PORT="${DEPLOY_PORT:-8080}"
HEALTH_URL="${DEPLOY_HEALTH_URL:-}"
JAVA8_HOME="${DEPLOY_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
BRANCH="${DEPLOY_BRANCH:-release}"
STOP_TIMEOUT="${DEPLOY_STOP_TIMEOUT:-30}"

usage() {
  echo "Usage: DEPLOY_API_REPO=... DEPLOY_AUTH_JS=... $0 <deploy|status>" >&2
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

read_auth_field() {
  local field="$1"
  node - "$AUTH_JS" "$field" <<'NODE'
const fs = require('fs')
const [configPath, field] = process.argv.slice(2)
const source = fs.readFileSync(configPath, 'utf8')
const patterns = {
  host: /host:\s*['"]([^'"]+)['"]/,
  username: /username:\s*['"]([^'"]+)['"]/,
  password: /password:\s*['"]([^'"]+)['"]/,
}
const match = source.match(patterns[field])
if (!match) process.exit(1)
process.stdout.write(match[1])
NODE
}

init_connection() {
  require_value DEPLOY_AUTH_JS "$AUTH_JS"
  [ -f "$AUTH_JS" ] || fail "auth config not found: $AUTH_JS"
  require_command node
  require_command sshpass
  require_command ssh
  require_command scp

  DEPLOY_HOST="$(read_auth_field host)" || fail "host not found in auth config"
  DEPLOY_USER="$(read_auth_field username)" || fail "username not found in auth config"
  DEPLOY_PASS="$(read_auth_field password)" || fail "password not found in auth config"
  export SSHPASS="$DEPLOY_PASS"
  SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
  SSH_OPTIONS=(-o StrictHostKeyChecking=no -o ConnectTimeout=10)
}

remote_status() {
  sshpass -e ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- \
    "$REMOTE_DIR" "$REMOTE_JAR" "$PROFILE" "$PORT" "$HEALTH_URL" <<'REMOTE'
set -euo pipefail
remote_dir="$1"
remote_jar="$2"
profile="$3"
port="$4"
health_url="$5"

pattern="[j]ava -jar ${remote_jar} --spring.profiles.active=${profile}"
pids="$(pgrep -f "$pattern" || true)"
count="$(printf '%s\n' "$pids" | awk 'NF {n++} END {print n+0}')"
[ "$count" -eq 1 ] || {
  echo "ERROR: expected exactly one target process, found $count" >&2
  exit 1
}
pid="$(printf '%s\n' "$pids" | awk 'NF {print; exit}')"

port_line="$(ss -lntp 2>/dev/null | grep -E ":${port}[[:space:]]" || true)"
[ -n "$port_line" ] || {
  echo "ERROR: port $port is not listening" >&2
  exit 1
}
printf '%s\n' "$port_line" | grep -q "pid=${pid}," || {
  echo "ERROR: port $port is not owned by target pid $pid" >&2
  exit 1
}

jar_path="${remote_dir}/${remote_jar}"
[ -f "$jar_path" ] || {
  echo "ERROR: running jar is missing: $jar_path" >&2
  exit 1
}
jar_sha="$(sha256sum "$jar_path" | awk '{print $1}')"
http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${port}/" || true)"
[ "$http_code" != "000" ] && [ -n "$http_code" ] || {
  echo "ERROR: local HTTP probe failed" >&2
  exit 1
}

if [ -n "$health_url" ]; then
  public_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$health_url" || true)"
  [ "$public_code" != "000" ] && [ -n "$public_code" ] || {
    echo "ERROR: public HTTP probe failed" >&2
    exit 1
  }
  echo "public_http=$public_code"
fi

echo "pid=$pid"
echo "port=$port"
echo "profile=$profile"
echo "jar_sha256=$jar_sha"
echo "local_http=$http_code"
REMOTE
}

build_release() {
  require_value DEPLOY_API_REPO "$REPO_DIR"
  [ -d "$REPO_DIR/.git" ] || fail "API repository not found: $REPO_DIR"
  [ -x "$JAVA8_HOME/bin/java" ] || fail "JDK 8 not found: $JAVA8_HOME"
  require_command git
  require_command mvn
  require_command sha256sum

  [ -z "$(git -C "$REPO_DIR" status --porcelain)" ] || fail "repository is dirty: $REPO_DIR"
  current_branch="$(git -C "$REPO_DIR" symbolic-ref --short HEAD)"
  [ "$current_branch" = "$BRANCH" ] || fail "expected branch $BRANCH, found $current_branch"

  git -C "$REPO_DIR" fetch origin "$BRANCH"
  local_head="$(git -C "$REPO_DIR" rev-parse HEAD)"
  remote_head="$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")"
  [ "$local_head" = "$remote_head" ] || fail "local HEAD does not match origin/$BRANCH"

  java_version="$("$JAVA8_HOME/bin/java" -version 2>&1 | head -n 1)"
  printf '%s\n' "$java_version" | grep -q '1\.8' || fail "DEPLOY_JAVA_HOME is not JDK 8"

  (
    cd "$REPO_DIR"
    JAVA_HOME="$JAVA8_HOME" PATH="$JAVA8_HOME/bin:$PATH" mvn clean package
  )

  LOCAL_JAR="$REPO_DIR/train-web/target/$REMOTE_JAR"
  [ -f "$LOCAL_JAR" ] || fail "build artifact not found: $LOCAL_JAR"
  LOCAL_SHA="$(sha256sum "$LOCAL_JAR" | awk '{print $1}')"
  RELEASE_ID="$(date +%Y%m%d-%H%M%S)-$(git -C "$REPO_DIR" rev-parse --short HEAD)"
  REMOTE_STAGE="${REMOTE_DIR}/${REMOTE_JAR}.${RELEASE_ID}.new"
}

remote_deploy() {
  sshpass -e scp "${SSH_OPTIONS[@]}" "$LOCAL_JAR" "$SSH_TARGET:$REMOTE_STAGE"

  sshpass -e ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- \
    "$REMOTE_DIR" "$REMOTE_JAR" "$REMOTE_STAGE" "$PROFILE" "$PORT" \
    "$LOCAL_SHA" "$RELEASE_ID" "$STOP_TIMEOUT" <<'REMOTE'
set -euo pipefail
remote_dir="$1"
remote_jar="$2"
stage="$3"
profile="$4"
port="$5"
expected_sha="$6"
release_id="$7"
stop_timeout="$8"
target="${remote_dir}/${remote_jar}"
backup_dir="${remote_dir}/backups"
backup="${backup_dir}/${remote_jar}.bak-${release_id}"
pattern="[j]ava -jar ${remote_jar} --spring.profiles.active=${profile}"

target_pids() {
  pgrep -f "$pattern" || true
}

target_count() {
  target_pids | awk 'NF {n++} END {print n+0}'
}

wait_stopped() {
  local pid="$1"
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$stop_timeout" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  ! kill -0 "$pid" 2>/dev/null
}

wait_ready() {
  local attempts=0
  while [ "$attempts" -lt 30 ]; do
    pids="$(target_pids)"
    count="$(printf '%s\n' "$pids" | awk 'NF {n++} END {print n+0}')"
    if [ "$count" -eq 1 ]; then
      pid="$(printf '%s\n' "$pids" | awk 'NF {print; exit}')"
      port_line="$(ss -lntp 2>/dev/null | grep -E ":${port}[[:space:]]" || true)"
      http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${port}/" || true)"
      if printf '%s\n' "$port_line" | grep -q "pid=${pid}," && [ "$http_code" != "000" ] && [ -n "$http_code" ]; then
        return 0
      fi
    fi
    sleep 2
    attempts=$((attempts + 1))
  done
  return 1
}

start_target() {
  (
    cd "$remote_dir"
    nohup java -jar "$remote_jar" --spring.profiles.active="$profile" >> train-web.log 2>&1 &
  )
}

rollback() {
  echo "New release failed validation; rolling back" >&2
  rollback_pids="$(target_pids)"
  for rollback_pid in $rollback_pids; do
    kill -TERM "$rollback_pid" 2>/dev/null || true
  done
  for rollback_pid in $rollback_pids; do
    wait_stopped "$rollback_pid" || {
      echo "ERROR: cannot stop failed process; manual recovery required" >&2
      return 1
    }
  done
  cp -p "$backup" "$target"
  start_target
  wait_ready || {
    echo "ERROR: rollback process did not become ready" >&2
    return 1
  }
  echo "Rollback completed" >&2
}

[ -f "$stage" ] || {
  echo "ERROR: staged jar not found: $stage" >&2
  exit 1
}
stage_sha="$(sha256sum "$stage" | awk '{print $1}')"
[ "$stage_sha" = "$expected_sha" ] || {
  echo "ERROR: staged jar SHA-256 mismatch" >&2
  exit 1
}
[ -f "$target" ] || {
  echo "ERROR: current jar not found: $target" >&2
  exit 1
}

count="$(target_count)"
[ "$count" -le 1 ] || {
  echo "ERROR: refusing deployment because $count target processes are running" >&2
  exit 1
}
current_pid="$(target_pids | awk 'NF {print; exit}')"
port_line="$(ss -lntp 2>/dev/null | grep -E ":${port}[[:space:]]" || true)"
if [ -n "$port_line" ]; then
  [ -n "$current_pid" ] && printf '%s\n' "$port_line" | grep -q "pid=${current_pid}," || {
    echo "ERROR: port $port is occupied by another process" >&2
    exit 1
  }
fi

mkdir -p "$backup_dir"
cp -p "$target" "$backup"

if [ -n "$current_pid" ]; then
  kill -TERM "$current_pid"
  wait_stopped "$current_pid" || {
    echo "ERROR: old process did not stop after ${stop_timeout}s; no files replaced" >&2
    exit 1
  }
fi

mv "$stage" "$target"
start_target
if ! wait_ready; then
  rollback
  exit 1
fi

running_sha="$(sha256sum "$target" | awk '{print $1}')"
[ "$running_sha" = "$expected_sha" ] || {
  rollback
  echo "ERROR: running jar SHA-256 mismatch" >&2
  exit 1
}

echo "release_id=$release_id"
echo "backup=$backup"
echo "jar_sha256=$running_sha"
REMOTE
}

case "$ACTION" in
  status)
    init_connection
    remote_status
    ;;
  deploy)
    init_connection
    build_release
    remote_deploy
    remote_status
    ;;
  *)
    usage
    ;;
esac

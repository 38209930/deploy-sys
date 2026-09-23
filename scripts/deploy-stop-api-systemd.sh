#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/git-release-source.sh"

ACTION="${1:-}"
REPO_DIR="${STOP_REPO_DIR:-}"
DEPLOY_HOST="${STOP_DEPLOY_HOST:-}"
DEPLOY_USER="${STOP_DEPLOY_USER:-deploy}"
SSH_KEY="${STOP_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}"
KNOWN_HOSTS="${STOP_KNOWN_HOSTS:-}"
BRANCH="${STOP_BRANCH:-release}"
EXPECTED_COMMIT="${STOP_EXPECTED_COMMIT:-}"
JAVA8_HOME="${STOP_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
REMOTE_JAR="${STOP_REMOTE_JAR:-/home/stop-api/app/stop-api.jar}"
REMOTE_GROUP="${STOP_REMOTE_GROUP:-stop-api}"
API_SERVICE="${STOP_API_SERVICE:-stop-api.service}"
HEALTH_PORT="${STOP_HEALTH_PORT:-8070}"
READY_ATTEMPTS="${STOP_READY_ATTEMPTS:-30}"

fail() { echo "ERROR: $*" >&2; exit 1; }
require_value() { [ -n "$2" ] || fail "missing environment variable: $1"; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }

init_connection() {
  require_value STOP_DEPLOY_HOST "$DEPLOY_HOST"
  require_value STOP_KNOWN_HOSTS "$KNOWN_HOSTS"
  [ -r "$SSH_KEY" ] || fail "SSH key is not readable: $SSH_KEY"
  [ -r "$KNOWN_HOSTS" ] || fail "known-hosts file is not readable: $KNOWN_HOSTS"
  require_command ssh
  require_command scp
  SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
  SSH_OPTIONS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="$KNOWN_HOSTS" -o GlobalKnownHostsFile=/dev/null
    -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=10 -o LogLevel=ERROR)
}

remote_status() {
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- "$API_SERVICE" "$REMOTE_JAR" "$HEALTH_PORT" <<'REMOTE'
set -euo pipefail
service="$1"; jar="$2"; port="$3"
active="$(systemctl is-active "$service" 2>/dev/null || true)"
enabled="$(systemctl is-enabled "$service" 2>/dev/null || true)"
echo "api_active=$active"
echo "api_enabled=$enabled"
[ "$active" = active ] || exit 1
pid="$(systemctl show "$service" -p MainPID --value)"
[ "$pid" -gt 0 ] 2>/dev/null || { echo "ERROR: invalid MainPID" >&2; exit 1; }
listener="$(sudo ss -lntpH "sport = :$port" 2>/dev/null || true)"
printf '%s\n' "$listener" | grep -q "pid=${pid}," || { echo "ERROR: port $port is not owned by pid $pid" >&2; exit 1; }
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${port}/" || true)"
[ -n "$code" ] && [ "$code" != 000 ] || { echo "ERROR: HTTP probe failed" >&2; exit 1; }
sha="$(sudo sha256sum "$jar" | awk '{print $1}')"
echo "pid=$pid"
echo "port=$port"
echo "local_http=$code"
echo "jar_sha256=$sha"
REMOTE
}

build_api() {
  require_value STOP_REPO_DIR "$REPO_DIR"
  require_command git; require_command mvn; require_command sha256sum; require_command tar
  git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "STOP repository not found: $REPO_DIR"
  [ -x "$JAVA8_HOME/bin/java" ] || fail "JDK 8 not found: $JAVA8_HOME"
  "$JAVA8_HOME/bin/java" -version 2>&1 | head -n 1 | grep -q '1\.8' || fail "STOP_JAVA_HOME is not JDK 8"
  prepare_isolated_git_source "$REPO_DIR" "$BRANCH" stop-family-api-build "$EXPECTED_COMMIT"
  trap 'cleanup_isolated_git_source stop-family-api-build' EXIT
  (cd "$DEPLOY_BUILD_DIR" && JAVA_HOME="$JAVA8_HOME" PATH="$JAVA8_HOME/bin:$PATH" mvn -B -Dstyle.color=never -pl train-web -am clean verify)
  LOCAL_JAR="$DEPLOY_BUILD_DIR/train-web/target/train-web-test-1.0.2.jar"
  [ -f "$LOCAL_JAR" ] || fail "API artifact not found: $LOCAL_JAR"
  LOCAL_SHA="$(sha256sum "$LOCAL_JAR" | awk '{print $1}')"
  RELEASE_ID="$(date +%Y%m%d-%H%M%S)-$(git -C "$REPO_DIR" rev-parse --short "$DEPLOY_SELECTED_HEAD")"
  REMOTE_STAGE="/home/deploy/stop-api.${RELEASE_ID}.jar.upload"
}

remote_deploy() {
  scp "${SSH_OPTIONS[@]}" "$LOCAL_JAR" "$SSH_TARGET:$REMOTE_STAGE"
  if ! ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- "$API_SERVICE" "$REMOTE_JAR" "$REMOTE_GROUP" "$REMOTE_STAGE" "$LOCAL_SHA" "$RELEASE_ID" "$HEALTH_PORT" "$READY_ATTEMPTS" <<'REMOTE'
set -euo pipefail
service="$1"; jar="$2"; group="$3"; stage="$4"; expected_sha="$5"; release_id="$6"; port="$7"; attempts="$8"
backup_dir="$(dirname "$jar")/backups"; backup="$backup_dir/$(basename "$jar").${release_id}.bak"
trap '[ ! -e "$stage" ] || unlink "$stage"' EXIT
[ "$(sha256sum "$stage" | awk '{print $1}')" = "$expected_sha" ] || { echo "ERROR: staged jar SHA-256 mismatch" >&2; exit 1; }
sudo test -f "$jar" || { echo "ERROR: current API jar is missing" >&2; exit 1; }
sudo install -d -o root -g "$group" -m 0750 "$backup_dir"
sudo cp -p "$jar" "$backup"
sudo systemctl stop "$service"
sudo install -o root -g "$group" -m 0640 "$stage" "$jar"
rollback() { echo "API validation failed; restoring previous jar" >&2; sudo systemctl stop "$service" || true; sudo cp -p "$backup" "$jar"; sudo systemctl start "$service"; }
sudo systemctl start "$service"
ready=no
for _ in $(seq 1 "$attempts"); do
  systemctl is-active --quiet "$service" || break
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${port}/" 2>/dev/null || true)"
  if [ -n "$code" ] && [ "$code" != 000 ]; then ready=yes; break; fi
  sleep 2
done
[ "$ready" = yes ] || { rollback; exit 1; }
[ "$(sudo sha256sum "$jar" | awk '{print $1}')" = "$expected_sha" ] || { rollback; echo "ERROR: running jar SHA-256 mismatch" >&2; exit 1; }
sudo systemctl enable "$service" >/dev/null
echo "release_id=$release_id"
echo "backup=$backup"
echo "jar_sha256=$expected_sha"
REMOTE
  then
    fail "STOP API deployment failed; inspect server state before retrying"
  fi
}

case "$ACTION" in
  status) init_connection; remote_status ;;
  deploy) init_connection; build_api; remote_deploy; remote_status ;;
  *) echo "Usage: STOP_REPO_DIR=... STOP_DEPLOY_HOST=... STOP_KNOWN_HOSTS=... $0 <deploy|status>" >&2; exit 2 ;;
esac

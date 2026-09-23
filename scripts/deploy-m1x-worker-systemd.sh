#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
REPO_DIR="${M1X_REPO_DIR:-}"
DEPLOY_HOST="${M1X_DEPLOY_HOST:-}"
DEPLOY_USER="${M1X_DEPLOY_USER:-deploy}"
SSH_KEY="${M1X_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}"
KNOWN_HOSTS="${M1X_KNOWN_HOSTS:-}"
BRANCH="${M1X_BRANCH:-release}"
EXPECTED_COMMIT="${M1X_EXPECTED_COMMIT:-}"
JAVA8_HOME="${M1X_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
REMOTE_JAR="${M1X_WORKER_REMOTE_JAR:-/home/worker/app/m1x-worker.jar}"
REMOTE_CONFIG="${M1X_WORKER_REMOTE_CONFIG:-/home/worker/config/application-prod.yml}"
WORKER_SERVICE="${M1X_WORKER_SERVICE:-m1x-worker.service}"
READY_ATTEMPTS="${M1X_WORKER_READY_ATTEMPTS:-30}"

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
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- "$WORKER_SERVICE" "$REMOTE_JAR" <<'REMOTE'
set -euo pipefail
worker_service="$1"
remote_jar="$2"
worker_enabled="$(systemctl is-enabled "$worker_service" 2>/dev/null || true)"
worker_active="$(systemctl is-active "$worker_service" 2>/dev/null || true)"
echo "worker_enabled=$worker_enabled"
echo "worker_active=$worker_active"
[ "$worker_enabled" = "enabled" ] || { echo "ERROR: Worker must be enabled" >&2; exit 1; }
[ "$worker_active" = "active" ] || { echo "ERROR: Worker must be active" >&2; exit 1; }
sudo test -f "$remote_jar" || { echo "ERROR: Worker jar is missing" >&2; exit 1; }
pid="$(systemctl show "$worker_service" -p MainPID --value)"
[ "$pid" -gt 0 ] 2>/dev/null || { echo "ERROR: Worker MainPID is invalid" >&2; exit 1; }
listener_count="$(sudo ss -lntpH | grep -c "pid=${pid}," || true)"
[ "$listener_count" -eq 0 ] || { echo "ERROR: Worker unexpectedly owns a listening port" >&2; exit 1; }
echo "pid=$pid"
echo "http_listeners=$listener_count"
echo "jar_sha256=$(sudo sha256sum "$remote_jar" | awk '{print $1}')"
REMOTE
}

build_worker() {
  require_value M1X_REPO_DIR "$REPO_DIR"
  require_command git
  git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "M1X repository/worktree not found: $REPO_DIR"
  [ -x "$JAVA8_HOME/bin/java" ] || fail "JDK 8 not found: $JAVA8_HOME"
  require_command mvn
  require_command sha256sum
  require_command tar

  [ -z "$(git -C "$REPO_DIR" status --porcelain)" ] || fail "repository is dirty: $REPO_DIR"
  current_branch="$(git -C "$REPO_DIR" symbolic-ref --short HEAD)"
  git -C "$REPO_DIR" fetch origin "$current_branch" "$BRANCH"
  current_head="$(git -C "$REPO_DIR" rev-parse HEAD)"
  remote_current_head="$(git -C "$REPO_DIR" rev-parse "origin/$current_branch")"
  release_head="$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")"
  [ "$current_head" = "$remote_current_head" ] \
    || fail "current branch HEAD does not match origin/$current_branch"

  if [ "$current_head" = "$release_head" ]; then
    selected_head="$current_head"
    selected_source="$current_branch (same commit as $BRANCH)"
  elif git -C "$REPO_DIR" merge-base --is-ancestor "$release_head" "$current_head"; then
    selected_head="$current_head"
    selected_source="$current_branch"
  elif git -C "$REPO_DIR" merge-base --is-ancestor "$current_head" "$release_head"; then
    selected_head="$release_head"
    selected_source="$BRANCH"
  else
    fail "current branch $current_branch and $BRANCH have diverged; merge before deployment"
  fi
  if [ -n "$EXPECTED_COMMIT" ]; then
    [ "$selected_head" = "$EXPECTED_COMMIT" ] || fail "selected commit does not match M1X_EXPECTED_COMMIT"
  fi

  echo "current_branch=$current_branch"
  echo "release_branch=$BRANCH"
  echo "selected_source=$selected_source"
  echo "selected_commit=$selected_head"

  "$JAVA8_HOME/bin/java" -version 2>&1 | head -n 1 | grep -q '1\.8' || fail "M1X_JAVA_HOME is not JDK 8"

  BUILD_DIR="$(mktemp -d /tmp/m1x-worker-build.XXXXXX)"
  cleanup_build_dir() {
    case "$BUILD_DIR" in
      /tmp/m1x-worker-build.*) rm -rf -- "$BUILD_DIR" ;;
      *) echo "WARNING: refusing to remove unexpected build directory: $BUILD_DIR" >&2 ;;
    esac
  }
  trap cleanup_build_dir EXIT
  git -C "$REPO_DIR" archive "$selected_head" | tar -x -C "$BUILD_DIR"

  (
    cd "$BUILD_DIR"
    JAVA_HOME="$JAVA8_HOME" PATH="$JAVA8_HOME/bin:$PATH" mvn -B -Dstyle.color=never -pl train-worker -am clean verify
  )
  LOCAL_JAR="$BUILD_DIR/train-worker/target/train-worker-1.0.2.jar"
  [ -f "$LOCAL_JAR" ] || fail "Worker artifact not found: $LOCAL_JAR"
  LOCAL_SHA="$(sha256sum "$LOCAL_JAR" | awk '{print $1}')"
  RELEASE_ID="$(date +%Y%m%d-%H%M%S)-$(git -C "$REPO_DIR" rev-parse --short "$selected_head")"
  REMOTE_STAGE="/home/deploy/m1x-worker.${RELEASE_ID}.jar.upload"
}

remote_deploy() {
  scp "${SSH_OPTIONS[@]}" "$LOCAL_JAR" "$SSH_TARGET:$REMOTE_STAGE"
  if ! ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- \
    "$WORKER_SERVICE" "$REMOTE_JAR" "$REMOTE_CONFIG" "$REMOTE_STAGE" "$LOCAL_SHA" "$RELEASE_ID" "$READY_ATTEMPTS" <<'REMOTE'
set -euo pipefail
worker_service="$1"
remote_jar="$2"
remote_config="$3"
remote_stage="$4"
expected_sha="$5"
release_id="$6"
ready_attempts="$7"
backup_dir="$(dirname "$remote_jar")/backups"
backup="$backup_dir/$(basename "$remote_jar").${release_id}.bak"
cleanup_stage() { [ ! -e "$remote_stage" ] || unlink "$remote_stage"; }
trap cleanup_stage EXIT

worker_enabled="$(systemctl is-enabled "$worker_service" 2>/dev/null || true)"
worker_active="$(systemctl is-active "$worker_service" 2>/dev/null || true)"
[ "$worker_enabled" = "enabled" ] || { echo "ERROR: Worker must be enabled before deployment" >&2; exit 1; }
[ "$worker_active" = "active" ] || { echo "ERROR: Worker must be active before deployment" >&2; exit 1; }
sudo test -f "$remote_config" || { echo "ERROR: Worker production config is missing" >&2; exit 1; }
[ -f "$remote_stage" ] || { echo "ERROR: staged Worker jar is missing" >&2; exit 1; }
stage_sha="$(sha256sum "$remote_stage" | awk '{print $1}')"
[ "$stage_sha" = "$expected_sha" ] || { echo "ERROR: staged Worker jar SHA-256 mismatch" >&2; exit 1; }
sudo test -f "$remote_jar" || { echo "ERROR: current Worker jar is missing" >&2; exit 1; }

sudo mkdir -p "$backup_dir"
sudo cp -p "$remote_jar" "$backup"
sudo systemctl stop "$worker_service"
sudo install -o root -g m1x-worker -m 0640 "$remote_stage" "$remote_jar"

rollback() {
  echo "Worker validation failed; restoring previous jar" >&2
  sudo systemctl stop "$worker_service" || true
  sudo cp -p "$backup" "$remote_jar"
  sudo systemctl start "$worker_service"
}

sudo systemctl start "$worker_service"
ready=no
for _ in $(seq 1 "$ready_attempts"); do
  if systemctl is-active --quiet "$worker_service"; then
    pid="$(systemctl show "$worker_service" -p MainPID --value)"
    if [ "$pid" -gt 0 ] 2>/dev/null; then
      ready=yes
      break
    fi
  fi
  sleep 2
done
[ "$ready" = yes ] || { rollback; exit 1; }
running_sha="$(sudo sha256sum "$remote_jar" | awk '{print $1}')"
[ "$running_sha" = "$expected_sha" ] || {
  rollback
  echo "ERROR: running Worker jar SHA-256 mismatch" >&2
  exit 1
}
listener_count="$(sudo ss -lntpH | grep -c "pid=${pid}," || true)"
[ "$listener_count" -eq 0 ] || { rollback; echo "ERROR: Worker unexpectedly owns a listening port" >&2; exit 1; }
echo "release_id=$release_id"
echo "backup=$backup"
echo "jar_sha256=$running_sha"
echo "worker_enabled=$worker_enabled"
echo "worker_active=active"
echo "http_listeners=$listener_count"
REMOTE
  then
    fail "M1X Worker deployment failed; inspect server state before retrying"
  fi
}

case "$ACTION" in
  status)
    init_connection
    remote_status
    ;;
  deploy)
    init_connection
    build_worker
    remote_deploy
    remote_status
    ;;
  *)
    usage
    ;;
esac

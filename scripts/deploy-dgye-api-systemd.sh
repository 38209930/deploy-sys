#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export STOP_REPO_DIR="${DGYE_REPO_DIR:-${STOP_REPO_DIR:-}}"
export STOP_DEPLOY_HOST="${DGYE_DEPLOY_HOST:-${STOP_DEPLOY_HOST:-}}"
export STOP_DEPLOY_USER="${DGYE_DEPLOY_USER:-${STOP_DEPLOY_USER:-deploy}}"
export STOP_SSH_KEY="${DGYE_SSH_KEY:-${STOP_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}}"
export STOP_KNOWN_HOSTS="${DGYE_KNOWN_HOSTS:-${STOP_KNOWN_HOSTS:-}}"
export STOP_BRANCH="${DGYE_BRANCH:-release}"
export STOP_EXPECTED_COMMIT="${DGYE_EXPECTED_COMMIT:-}"
export STOP_JAVA_HOME="${DGYE_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
export STOP_REMOTE_JAR="${DGYE_REMOTE_JAR:-/home/dgye-api/app/dgye-api.jar}"
export STOP_REMOTE_GROUP="${DGYE_REMOTE_GROUP:-dgye-api}"
export STOP_API_SERVICE="${DGYE_API_SERVICE:-dgye-api.service}"
export STOP_HEALTH_PORT="${DGYE_HEALTH_PORT:-8030}"
export STOP_READY_ATTEMPTS="${DGYE_READY_ATTEMPTS:-30}"

exec bash "$SCRIPT_DIR/deploy-stop-api-systemd.sh" "$@"

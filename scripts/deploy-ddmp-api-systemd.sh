#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export STOP_REPO_DIR="${DDMP_REPO_DIR:-${STOP_REPO_DIR:-}}"
export STOP_DEPLOY_HOST="${DDMP_DEPLOY_HOST:-${STOP_DEPLOY_HOST:-}}"
export STOP_DEPLOY_USER="${DDMP_DEPLOY_USER:-${STOP_DEPLOY_USER:-deploy}}"
export STOP_SSH_KEY="${DDMP_SSH_KEY:-${STOP_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}}"
export STOP_KNOWN_HOSTS="${DDMP_KNOWN_HOSTS:-${STOP_KNOWN_HOSTS:-}}"
export STOP_BRANCH="${DDMP_BRANCH:-release}"
export STOP_EXPECTED_COMMIT="${DDMP_EXPECTED_COMMIT:-}"
export STOP_JAVA_HOME="${DDMP_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
export STOP_REMOTE_JAR="${DDMP_REMOTE_JAR:-/home/ddmp-api/app/ddmp-api.jar}"
export STOP_REMOTE_GROUP="${DDMP_REMOTE_GROUP:-ddmp-api}"
export STOP_API_SERVICE="${DDMP_API_SERVICE:-ddmp-api.service}"
export STOP_HEALTH_PORT="${DDMP_HEALTH_PORT:-8050}"
export STOP_READY_ATTEMPTS="${DDMP_READY_ATTEMPTS:-30}"

exec bash "$SCRIPT_DIR/deploy-stop-api-systemd.sh" "$@"

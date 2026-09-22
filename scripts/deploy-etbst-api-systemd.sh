#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export STOP_REPO_DIR="${ETBST_REPO_DIR:-${STOP_REPO_DIR:-}}"
export STOP_DEPLOY_HOST="${ETBST_DEPLOY_HOST:-${STOP_DEPLOY_HOST:-}}"
export STOP_DEPLOY_USER="${ETBST_DEPLOY_USER:-${STOP_DEPLOY_USER:-deploy}}"
export STOP_SSH_KEY="${ETBST_SSH_KEY:-${STOP_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}}"
export STOP_KNOWN_HOSTS="${ETBST_KNOWN_HOSTS:-${STOP_KNOWN_HOSTS:-}}"
export STOP_BRANCH="${ETBST_BRANCH:-release}"
export STOP_EXPECTED_COMMIT="${ETBST_EXPECTED_COMMIT:-}"
export STOP_JAVA_HOME="${ETBST_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
export STOP_REMOTE_JAR="${ETBST_REMOTE_JAR:-/home/etbst-api/app/etbst-api.jar}"
export STOP_REMOTE_GROUP="${ETBST_REMOTE_GROUP:-etbst-api}"
export STOP_API_SERVICE="${ETBST_API_SERVICE:-etbst-api.service}"
export STOP_HEALTH_PORT="${ETBST_HEALTH_PORT:-8060}"
export STOP_READY_ATTEMPTS="${ETBST_READY_ATTEMPTS:-30}"

exec bash "$SCRIPT_DIR/deploy-stop-api-systemd.sh" "$@"

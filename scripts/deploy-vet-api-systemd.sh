#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export STOP_REPO_DIR="${VET_REPO_DIR:-${STOP_REPO_DIR:-}}"
export STOP_DEPLOY_HOST="${VET_DEPLOY_HOST:-${STOP_DEPLOY_HOST:-}}"
export STOP_DEPLOY_USER="${VET_DEPLOY_USER:-${STOP_DEPLOY_USER:-deploy}}"
export STOP_SSH_KEY="${VET_SSH_KEY:-${STOP_SSH_KEY:-$HOME/.ssh/smscore_deploy_ed25519}}"
export STOP_KNOWN_HOSTS="${VET_KNOWN_HOSTS:-${STOP_KNOWN_HOSTS:-}}"
export STOP_BRANCH="${VET_BRANCH:-release}"
export STOP_EXPECTED_COMMIT="${VET_EXPECTED_COMMIT:-}"
export STOP_JAVA_HOME="${VET_JAVA_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
export STOP_REMOTE_JAR="${VET_REMOTE_JAR:-/home/vet-api/app/vet-api.jar}"
export STOP_REMOTE_GROUP="${VET_REMOTE_GROUP:-vet-api}"
export STOP_API_SERVICE="${VET_API_SERVICE:-vet-api.service}"
export STOP_HEALTH_PORT="${VET_HEALTH_PORT:-8040}"
export STOP_READY_ATTEMPTS="${VET_READY_ATTEMPTS:-30}"

exec bash "$SCRIPT_DIR/deploy-stop-api-systemd.sh" "$@"

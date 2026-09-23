#!/usr/bin/env bash

# Select the newer pushed commit between the current branch and the release
# branch, then export that commit into an isolated build directory. Callers
# keep their development worktree and branch untouched.
prepare_isolated_git_source() {
  local repo_dir="$1"
  local release_branch="$2"
  local temp_prefix="$3"
  local expected_commit="${4:-}"
  local current_branch current_head remote_current_head release_head

  git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "Git repository/worktree not found: $repo_dir"
  [ -z "$(git -C "$repo_dir" status --porcelain)" ] \
    || fail "repository is dirty: $repo_dir"

  current_branch="$(git -C "$repo_dir" symbolic-ref --quiet --short HEAD)" \
    || fail "repository is in detached HEAD state: $repo_dir"
  git -C "$repo_dir" fetch origin "$current_branch" "$release_branch"
  current_head="$(git -C "$repo_dir" rev-parse HEAD)"
  remote_current_head="$(git -C "$repo_dir" rev-parse "origin/$current_branch")"
  release_head="$(git -C "$repo_dir" rev-parse "origin/$release_branch")"
  [ "$current_head" = "$remote_current_head" ] \
    || fail "current branch HEAD does not match origin/$current_branch"

  if [ "$current_head" = "$release_head" ]; then
    DEPLOY_SELECTED_HEAD="$current_head"
    DEPLOY_SELECTED_SOURCE="$current_branch (same commit as $release_branch)"
  elif git -C "$repo_dir" merge-base --is-ancestor "$release_head" "$current_head"; then
    DEPLOY_SELECTED_HEAD="$current_head"
    DEPLOY_SELECTED_SOURCE="$current_branch"
  elif git -C "$repo_dir" merge-base --is-ancestor "$current_head" "$release_head"; then
    DEPLOY_SELECTED_HEAD="$release_head"
    DEPLOY_SELECTED_SOURCE="$release_branch"
  else
    fail "current branch $current_branch and $release_branch have diverged; merge before deployment"
  fi

  if [ -n "$expected_commit" ]; then
    [ "$DEPLOY_SELECTED_HEAD" = "$expected_commit" ] \
      || fail "selected commit does not match expected commit"
  fi

  case "$temp_prefix" in
    *[!A-Za-z0-9._-]*|'') fail "invalid isolated build prefix: $temp_prefix" ;;
  esac
  DEPLOY_BUILD_DIR="$(mktemp -d "/tmp/${temp_prefix}.XXXXXX")"
  git -C "$repo_dir" archive "$DEPLOY_SELECTED_HEAD" | tar -x -C "$DEPLOY_BUILD_DIR"

  DEPLOY_CURRENT_BRANCH="$current_branch"
  echo "current_branch=$DEPLOY_CURRENT_BRANCH"
  echo "release_branch=$release_branch"
  echo "selected_source=$DEPLOY_SELECTED_SOURCE"
  echo "selected_commit=$DEPLOY_SELECTED_HEAD"
  echo "isolated_build_dir=$DEPLOY_BUILD_DIR"
}

cleanup_isolated_git_source() {
  local expected_prefix="$1"
  [ -n "${DEPLOY_BUILD_DIR:-}" ] || return 0
  case "$DEPLOY_BUILD_DIR" in
    "/tmp/${expected_prefix}."*) rm -rf -- "$DEPLOY_BUILD_DIR" ;;
    *) echo "WARNING: refusing to remove unexpected build directory: $DEPLOY_BUILD_DIR" >&2 ;;
  esac
}

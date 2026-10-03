#!/usr/bin/env python3
"""售后工单部署菜单：切换已合并分支，保留现有部署命令。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


class DeployError(RuntimeError):
    pass


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if result.returncode:
        # 不回显远端URL、凭据或完整命令输出。
        raise DeployError("Git操作失败：" + " ".join(args[:2]))
    return result.stdout.strip()


def ancestor(repo, older, newer):
    result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer], capture_output=True)
    if result.returncode not in (0, 1):
        raise DeployError("无法核验Git祖先关系")
    return result.returncode == 0


def local_ref(repo, branch):
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "refs/heads/" + branch], text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def require_clean(repo):
    if git(repo, "status", "--porcelain"):
        raise DeployError("工作树有未提交或未跟踪文件，停止部署；不自动stash或丢弃")
    if not git(repo, "branch", "--show-current"):
        raise DeployError("当前为detached HEAD，停止部署")


def prepare(repo, environment, action):
    require_clean(repo)
    branch = "dev" if environment == "test" else "release"
    refs = ["dev"] if environment == "test" else ["dev", "release", "master"]
    git(repo, "fetch", "--quiet", "origin", *[f"refs/heads/{r}:refs/remotes/origin/{r}" for r in refs])
    remote = git(repo, "rev-parse", "refs/remotes/origin/" + branch)
    local = local_ref(repo, branch)
    if local and not ancestor(repo, local, remote):
        if not (environment == "prod" and action == "push" and ancestor(repo, remote, local)):
            raise DeployError(branch + "存在未推送提交或分叉，请先处理，不自动覆盖")
    selected = local if local and environment == "prod" and action == "push" and ancestor(repo, remote, local) else remote
    if environment == "prod":
        dev = local_ref(repo, "dev")
        if dev and not ancestor(repo, dev, "origin/dev"):
            raise DeployError("本地dev存在未推送提交或分叉，须先处理开发交付")
        if not ancestor(repo, "origin/dev", selected):
            raise DeployError("release尚未包含最新origin/dev，须先将dev合入release")
        if not ancestor(repo, "origin/master", selected):
            raise DeployError("master与release不能快进收口，请先将主干变更合入dev/release")
        master = local_ref(repo, "master")
        if master and not ancestor(repo, master, "origin/master"):
            raise DeployError("本地master含未推送变更，停止部署")
    if local:
        git(repo, "switch", branch)
        if selected == remote:
            git(repo, "merge", "--ff-only", "origin/" + branch)
    else:
        git(repo, "switch", "--track", "-c", branch, "origin/" + branch)
    head = git(repo, "rev-parse", "HEAD")
    if head != selected:
        raise DeployError("分支切换后的提交与核验结果不符")
    print(f"deploy_source={branch} commit={head}", flush=True)
    return head


def read_state(path):
    if not path.is_file():
        raise DeployError("缺少Flow待发布状态，先执行构建")
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def verify_flow_state(path, expected, service):
    state = read_state(path)
    if state.get("service") != service or state.get("last_status") not in ("WAITING_CONFIRM", "APPROVED_PENDING_DEPLOY"):
        raise DeployError("Flow状态不属于本次服务或不是待发布状态")
    if state.get("source_commit") != expected:
        raise DeployError("待发布镜像源码提交与当前release不一致，须重新构建")


def finish_master(repo, expected):
    require_clean(repo)
    git(repo, "fetch", "--quiet", "origin", *[f"refs/heads/{r}:refs/remotes/origin/{r}" for r in ["dev", "release", "master"]])
    if git(repo, "rev-parse", "origin/release") != expected or git(repo, "rev-parse", "HEAD") != expected:
        raise DeployError("发布期间release变化，已发布产物需人工核对，master未收口")
    if not ancestor(repo, "origin/dev", expected) or not ancestor(repo, "origin/master", expected):
        raise DeployError("发布期间dev/master变化，master不能自动收口")
    master = local_ref(repo, "master")
    if master and not ancestor(repo, master, "origin/master"):
        raise DeployError("发布完成，但本地master含未推送提交，未自动收口")
    if master:
        git(repo, "switch", "master")
        git(repo, "merge", "--ff-only", "origin/master")
    else:
        git(repo, "switch", "--track", "-c", "master", "origin/master")
    try:
        git(repo, "merge", "--ff-only", expected)
        git(repo, "push", "origin", "master")
        git(repo, "fetch", "--quiet", "origin", "refs/heads/master:refs/remotes/origin/master")
        if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "origin/master"):
            raise DeployError("master推送后未与远端一致")
        print(f"master_closed={expected} ahead=0 behind=0", flush=True)
    finally:
        git(repo, "switch", "release")


def execute(repo, environment, action, command, flow_service=None):
    head = prepare(repo, environment, action)
    state_path = Path(os.environ.get("FLOW_STATE_DIR", str(Path(__file__).resolve().parent.parent / "data/flow-state"))) / f"{flow_service}.env"
    if environment == "prod" and action == "deploy" and flow_service:
        verify_flow_state(state_path, head, flow_service)
    result = subprocess.run(command)
    if result.returncode:
        return result.returncode
    if environment == "prod" and action == "deploy":
        if flow_service and read_state(state_path).get("last_status") != "DEPLOY_SUCCESS":
            raise DeployError("流水线未完成真实发布，不合入master")
        if flow_service:
            pending = []
            for service in ("service-order-front", "service-order-back", "service-order-worker"):
                path = state_path.parent / f"{service}.env"
                state = read_state(path) if path.is_file() else {}
                if state.get("service") != service or state.get("last_status") != "DEPLOY_SUCCESS" or state.get("source_commit") != head:
                    pending.append(service)
            if pending:
                print("本服务已发布；等待配套服务同一提交完成，master未收口：" + ",".join(pending), flush=True)
                return 0
        finish_master(repo, head)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=["test", "prod"])
    parser.add_argument("repo", type=Path)
    parser.add_argument("action", choices=["push", "build", "deploy"])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("缺少原部署命令")
    try:
        return execute(args.repo, args.environment, args.action, command, os.environ.get("FLOW_SERVICE"))
    except DeployError as error:
        print("停止：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

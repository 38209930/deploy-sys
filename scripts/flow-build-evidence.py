#!/usr/bin/env python3
"""将唯一源码提交与本次 ACR 构建 tag/digest 关联。"""

import json
import re
import sys


def verify(run_detail, tags, branch):
    run = run_detail["pipelineRun"]
    images = tags.get("Images") or []
    sources = run.get("sources") or []
    if len(sources) != 1 or sources[0].get("data", {}).get("branch") != branch:
        raise ValueError("构建源码不是唯一的目标分支源")
    commits = json.loads(sources[0]["data"]["commint"])
    if not commits:
        raise ValueError("流水线没有源码提交")
    # 云效对较长分支返回最近多条提交；首条是本次检出的 HEAD。
    # 镜像 tag 必须与首条提交匹配，不能匹配历史中的其他提交。
    commit = commits[0]["commitId"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("源码提交格式无效")
    matches = [image for image in images
               if image.get("Tag", "").endswith("-" + commit[:8])
               and run["createTime"] <= image.get("ImageCreate", 0) <= run["updateTime"] + 120000]
    if len(matches) != 1:
        raise ValueError(f"本次构建匹配的 ACR tag 数量为 {len(matches)}")
    tag, digest = matches[0]["Tag"], matches[0]["Digest"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("ACR digest 格式无效")
    return commit, tag, digest


if __name__ == "__main__":
    try:
        print(*verify(json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]))
    except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"构建证据无效：{exc}", file=sys.stderr)
        sys.exit(1)

#!/bin/sh
# ACS 只读资源采样；KUBECONFIG 必须指向已授权的临时配置。
set -eu
INTERVAL="${1:-60}"
case "$INTERVAL" in ''|*[!0-9]*) echo '间隔必须是非负整数秒' >&2; exit 1;; esac
[ -n "${KUBECONFIG:-}" ] || { echo '需要 KUBECONFIG 环境变量' >&2; exit 1; }
TMPDIR_ACS=$(mktemp -d "${TMPDIR:-/tmp}/acs-res.XXXXXXXX")
trap 'rm -rf "$TMPDIR_ACS"' EXIT
trap 'exit 1' HUP INT TERM
sample() {
  kubectl get pods -A -o json | python3 -c '
import json, subprocess, sys, time
for p in json.load(sys.stdin)["items"]:
    if p["status"].get("phase") != "Running": continue
    for c in p["spec"]["containers"]:
        ns, pod, container = p["metadata"]["namespace"], p["metadata"]["name"], c["name"]
        lim = c.get("resources", {}).get("limits", {})
        cmd = """if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
 echo v2; cat /sys/fs/cgroup/memory.current; grep ^usage_usec /sys/fs/cgroup/cpu.stat; grep ^anon /sys/fs/cgroup/memory.stat
else
 echo v1; cat /sys/fs/cgroup/memory/memory.usage_in_bytes; cat /sys/fs/cgroup/cpu/cpuacct.usage; grep ^rss /sys/fs/cgroup/memory/memory.stat
fi"""
        result = subprocess.run(["kubectl","exec","-n",ns,pod,"-c",container,"--","sh","-c",cmd],capture_output=True,text=True)
        lines = result.stdout.splitlines()
        try:
            version = lines[0]
            assert version in ("v1", "v2") and result.returncode == 0
            mem = int(lines[1]); cpu = int(lines[2].split()[-1])
            key, resident = lines[3].split()
            assert key == ("anon" if version == "v2" else "rss")
            resident = int(resident)
        except (IndexError, ValueError, AssertionError):
            print(f"采样失败: {ns}/{pod}/{container}", file=sys.stderr); sys.exit(1)
        print(json.dumps(dict(ns=ns,pod=pod,container=container,ts=time.time(),cpu_limit=lim.get("cpu",""),mem_limit=lim.get("memory",""),version=version,mem=mem,cpu=cpu,resident=resident)))
'
}
sample > "$TMPDIR_ACS/first.jsonl"
sleep "$INTERVAL"
sample > "$TMPDIR_ACS/second.jsonl"
python3 - "$TMPDIR_ACS/first.jsonl" "$TMPDIR_ACS/second.jsonl" <<'PY'
import json, sys

def quantity(value):
    if not value: return 0.0
    for suffix, factor in [('Gi', 1<<30), ('Mi', 1<<20), ('Ki', 1<<10), ('G', 10**9), ('M', 10**6), ('K', 10**3), ('m', .001)]:
        if value.endswith(suffix): return float(value[:-len(suffix)]) * factor
    return float(value)

def read(path):
    with open(path) as f:
        return {(r['ns'], r['pod'], r['container']): r for r in map(json.loads, f)}
first, second = read(sys.argv[1]), read(sys.argv[2])
print(f"{'namespace/pod/container':<55} {'memory MiB':>11} {'mem %':>8} {'rss/anon MiB':>14} {'resident %':>11} {'cpu % limit':>12}")
for key, b in second.items():
    a = first.get(key)
    if not a or a['version'] != b['version'] or b['ts'] <= a['ts'] or b['cpu'] < a['cpu']:
        print('/'.join(key), '采样不连续'); continue
    mem_limit = quantity(b['mem_limit']); cpu_limit = quantity(b['cpu_limit'])
    elapsed = b['ts'] - a['ts']
    cpu_seconds = (b['cpu'] - a['cpu']) / (1e6 if b['version'] == 'v2' else 1e9)
    pct = lambda n, d: f'{n/d*100:.1f}' if d else '-'
    print(f"{'/'.join(key):<55} {b['mem']/(1<<20):>11.1f} {pct(b['mem'],mem_limit):>8} {b['resident']/(1<<20):>14.1f} {pct(b['resident'],mem_limit):>11} {pct(cpu_seconds/elapsed,cpu_limit):>12}")
PY

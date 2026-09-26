#!/bin/sh
# ACS 工作负载资源采样：两次读取容器 cgroup（v1/v2 自适应），间隔默认 60 秒，
# 输出每个运行中 Pod 的内存用量/RSS、CPU 近似占用率，并与 limits 对照。
# 用法：KUBECONFIG=<临时kubeconfig路径> sh resource-snapshot.sh [采样间隔秒，默认60]
# 只读操作；不读取 Secret、不修改任何对象。
set -eu

INTERVAL="${1:-60}"
[ -n "${KUBECONFIG:-}" ] || { echo "需要 KUBECONFIG 环境变量"; exit 1; }

SNAP='if [ -f /sys/fs/cgroup/memory.current ]; then
  cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/cpu.stat 2>/dev/null
elif [ -f /sys/fs/cgroup/memory/memory.usage_in_bytes ]; then
  cat /sys/fs/cgroup/memory/memory.usage_in_bytes /sys/fs/cgroup/cpu/cpuacct.usage /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null
  grep "^rss " /sys/fs/cgroup/memory/memory.stat 2>/dev/null
fi'
export SNAP

sample() {
  kubectl get pods -A -o json | SNAP="$SNAP" python3 -c '
import json, os, subprocess, sys, time
pods = []
for p in json.load(sys.stdin)["items"]:
    if p["status"].get("phase") != "Running":
        continue
    c = p["spec"]["containers"][0]
    lim = c.get("resources", {}).get("limits", {})
    pods.append((p["metadata"]["namespace"], p["metadata"]["name"],
                 lim.get("cpu",""), lim.get("memory",""), time.time()))
for ns, name, lcpu, lmem, ts in pods:
    out = subprocess.run(["kubectl","exec","-n",ns,name,"--","sh","-c",os.environ["SNAP"]],
                         capture_output=True, text=True)
    vals = [x for x in out.stdout.split() if x.isdigit()]
    print(json.dumps({"ns":ns,"pod":name,"ts":ts,"cpu":lcpu,"mem":lmem,"vals":vals}))
'
}

sample > /tmp/acs-res-s1.json
sleep "$INTERVAL"
sample > /tmp/acs-res-s2.json

python3 - <<'PY'
import json

def to_cores(c):
    c = c or '0'
    return float(c[:-1])/1000 if c.endswith('m') else float(c or 0)

def to_bytes(m):
    m = m or '0'
    for suf, mult in (('Gi',1<<30),('Mi',1<<20),('Ki',1<<10)):
        if m.endswith(suf): return float(m[:-2])*mult
    return float(m or 0)

s1 = {f"{x['ns']}/{x['pod']}": x for x in map(json.loads, open('/tmp/acs-res-s1.json'))}
s2 = {f"{x['ns']}/{x['pod']}": x for x in map(json.loads, open('/tmp/acs-res-s2.json'))}
print(f"{'namespace/pod':<42}{'limit':<12}{'mem使用':>9}{'mem占比':>8}{'RSS':>9}{'RSS占比':>8}{'CPU占比':>8}")
for k, b in s2.items():
    a = s1.get(k)
    if not a or not b['vals']:
        print(f"{k:<42}{b['cpu']+'/'+b['mem']:<12}{'-':>9}{'-':>8}{'-':>9}{'-':>8}{'-':>8}")
        continue
    mem_lim = to_bytes(b['mem'])
    # cgroup v1: [usage, cpuacct, limit, rss]；v2: [memory.current, cpu.stat 首字段]
    mem1, cpu1 = int(a['vals'][0]), int(a['vals'][1])
    mem2, cpu2 = int(b['vals'][0]), int(b['vals'][1])
    rss = int(b['vals'][3]) if len(b['vals']) >= 4 else None
    dt = b['ts'] - a['ts']
    cpu_pct = (cpu2-cpu1)/1e9/dt/to_cores(b['cpu'])*100 if dt > 0 else 0
    mem_pct = mem2/mem_lim*100 if mem_lim else 0
    rss_pct = rss/mem_lim*100 if rss and mem_lim else 0
    print(f"{k:<42}{b['cpu']+'/'+b['mem']:<12}{mem2>>20:>8}M{mem_pct:>7.1f}%"
          f"{(str(rss>>20)+'M') if rss else '-':>9}{rss_pct:>7.1f}%{cpu_pct:>7.1f}%")
PY
rm -f /tmp/acs-res-s1.json /tmp/acs-res-s2.json

#!/usr/bin/env python3
"""deploy-sys 本地 Web 客户端。

原 Tk 客户端在部分 macOS/Python/Tk 组合下会出现输入框或下拉框假死。
这个客户端只使用 Python 标准库启动本地 HTTP 服务，并在系统浏览器中操作。
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import deploysys


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SESSIONS: dict[str, dict[str, Any]] = {}
SESSIONS_LOCK = threading.Lock()


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>deploy-sys</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f5f6f8; color: #1f2933; }
    header { height: 52px; display: flex; align-items: center; justify-content: space-between; padding: 0 18px; background: #111827; color: white; }
    main { display: grid; grid-template-columns: 260px 300px minmax(420px, 1fr); gap: 12px; padding: 12px; height: calc(100vh - 76px); box-sizing: border-box; }
    section { background: white; border: 1px solid #d8dee7; border-radius: 8px; padding: 12px; overflow: hidden; display: flex; flex-direction: column; min-height: 0; }
    h2 { margin: 0 0 10px; font-size: 15px; }
    button { border: 1px solid #c9d2df; background: #fff; border-radius: 6px; padding: 7px 10px; cursor: pointer; }
    button.primary { background: #2563eb; color: white; border-color: #2563eb; }
    button.danger { color: #b42318; border-color: #f1b8b2; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
    .list { overflow: auto; border: 1px solid #d8dee7; border-radius: 6px; min-height: 0; flex: 1; }
    .item { padding: 9px 10px; border-bottom: 1px solid #edf0f4; cursor: pointer; }
    .item:hover { background: #f4f7fb; }
    .item.active { background: #dbeafe; }
    .muted { color: #64748b; font-size: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 10px; }
    textarea, input { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; font: 13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    textarea { min-height: 130px; resize: vertical; }
    label { display: block; margin: 8px 0 5px; font-size: 12px; color: #475569; }
    #log { flex: 1; min-height: 180px; background: #0f172a; color: #dbeafe; border-radius: 6px; padding: 10px; overflow: auto; white-space: pre-wrap; font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    dialog { border: 0; border-radius: 10px; padding: 0; width: min(760px, calc(100vw - 28px)); box-shadow: 0 20px 60px rgba(15,23,42,.28); }
    dialog form { padding: 16px; }
    dialog h3 { margin: 0 0 10px; }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .status { font-size: 12px; color: #cbd5e1; }
  </style>
</head>
<body>
  <header>
    <strong>deploy-sys</strong>
    <span class="status" id="configPath"></span>
  </header>
  <main>
    <section>
      <div class="toolbar">
        <button onclick="reload()">刷新</button>
        <button onclick="showProjectDialog()">新增项目</button>
        <button class="danger" onclick="deleteSelected('project')">删除项目</button>
      </div>
      <h2>项目</h2>
      <div id="projects" class="list"></div>
    </section>
    <section>
      <div class="toolbar">
        <button onclick="showServiceDialog()">新增服务</button>
        <button class="danger" onclick="deleteSelected('service')">删除服务</button>
      </div>
      <h2>服务</h2>
      <div id="services" class="list"></div>
    </section>
    <section>
      <div class="toolbar">
        <button onclick="showTargetDialog()">新增执行目标</button>
        <button class="danger" onclick="deleteSelected('target')">删除执行目标</button>
      </div>
      <div class="grid">
        <div>
          <h2>执行目标</h2>
          <div id="targets" class="list" style="height: 120px; flex: none;"></div>
        </div>
        <div>
          <h2>动作</h2>
          <div id="actions" class="list" style="height: 120px; flex: none;"></div>
        </div>
      </div>
      <label>命令预览/编辑</label>
      <textarea id="commands" spellcheck="false"></textarea>
      <div class="toolbar">
        <button onclick="saveCommands()">保存命令</button>
        <button class="primary" id="executeBtn" onclick="execute()">执行</button>
        <button onclick="statusCheck()">状态检查</button>
        <button onclick="clearLog()">清空日志</button>
      </div>
      <div id="log"></div>
    </section>
  </main>

  <dialog id="projectDialog">
    <form method="dialog" onsubmit="event.preventDefault(); createProject();">
      <h3>新增项目</h3>
      <label>项目 ID</label><input id="projectId" required />
      <label>项目名称</label><input id="projectName" required />
      <label>项目类型</label><input id="projectType" value="other" />
      <div class="toolbar" style="justify-content:flex-end;margin-top:14px;">
        <button type="button" onclick="$('projectDialog').close()">取消</button>
        <button class="primary">保存</button>
      </div>
    </form>
  </dialog>

  <dialog id="serviceDialog">
    <form method="dialog" onsubmit="event.preventDefault(); createService();">
      <h3>新增服务</h3>
      <div class="split">
        <div><label>服务 ID</label><input id="serviceId" required /></div>
        <div><label>服务名称</label><input id="serviceName" /></div>
      </div>
      <div class="split">
        <div><label>服务类型</label><input id="serviceType" value="other" /></div>
        <div><label>执行目标</label><input id="serviceTarget" value="默认" required /></div>
      </div>
      <label>执行命令，可直接粘贴多行</label><textarea id="serviceCommands" spellcheck="false"></textarea>
      <div class="toolbar" style="justify-content:flex-end;margin-top:14px;">
        <button type="button" onclick="$('serviceDialog').close()">取消</button>
        <button class="primary">保存</button>
      </div>
    </form>
  </dialog>

  <dialog id="targetDialog">
    <form method="dialog" onsubmit="event.preventDefault(); createTarget();">
      <h3>新增执行目标</h3>
      <label>执行目标</label><input id="targetName" value="默认" required />
      <label>执行命令，可直接粘贴多行</label><textarea id="targetCommands" spellcheck="false"></textarea>
      <div class="toolbar" style="justify-content:flex-end;margin-top:14px;">
        <button type="button" onclick="$('targetDialog').close()">取消</button>
        <button class="primary">保存</button>
      </div>
    </form>
  </dialog>

  <script>
    let state = { projects: [] };
    let selected = { project: null, service: null, target: null, action: null };
    let activeSession = null;
    const $ = id => document.getElementById(id);
    const lines = text => text.split(/\r?\n/).map(x => x.trimEnd()).filter(x => x.trim());

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      return data;
    }

    function item(label, sub, active, onclick) {
      const div = document.createElement("div");
      div.className = "item" + (active ? " active" : "");
      div.onclick = onclick;
      div.innerHTML = `<div>${escapeHtml(label || "")}</div>${sub ? `<div class="muted">${escapeHtml(sub)}</div>` : ""}`;
      return div;
    }

    function escapeHtml(text) {
      return String(text).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }

    async function reload(keep = true) {
      const prev = keep ? { ...selected } : {};
      state = await api("/api/state");
      $("configPath").textContent = state.config_path;
      if (prev.project && !findProject(prev.project)) selected.project = null;
      if (!selected.project && state.projects.length) selected.project = state.projects[0].id;
      if (prev.service && !findService(prev.service)) selected.service = null;
      if (!selected.service && services().length) selected.service = services()[0].id;
      if (prev.target && !targets()[prev.target]) selected.target = null;
      if (!selected.target && Object.keys(targets()).length) selected.target = Object.keys(targets())[0];
      const actionKeys = actions();
      if (prev.action && !actionKeys.includes(prev.action)) selected.action = null;
      if (!selected.action && actionKeys.length) selected.action = actionKeys[0];
      render();
    }

    function findProject(id) { return state.projects.find(p => p.id === id); }
    function services() { return (findProject(selected.project)?.services || []); }
    function findService(id) { return services().find(s => s.id === id); }
    function targets() { const s = findService(selected.service); return s ? (s.targets || s.environments || {}) : {}; }
    function targetCfg() { return targets()[selected.target] || {}; }
    function actions() { return Object.keys(targetCfg().commands || {}).filter(k => (targetCfg().commands[k] || []).length); }
    function commandList() { return ((targetCfg().commands || {})[selected.action] || []); }

    function render() {
      const pbox = $("projects"); pbox.innerHTML = "";
      for (const p of state.projects) pbox.appendChild(item(p.name, p.id, p.id === selected.project, () => {
        selected.project = p.id; selected.service = null; selected.target = null; selected.action = null; reload();
      }));

      const sbox = $("services"); sbox.innerHTML = "";
      for (const s of services()) sbox.appendChild(item(s.name || s.id, s.id, s.id === selected.service, () => {
        selected.service = s.id; selected.target = null; selected.action = null; reload();
      }));

      const tbox = $("targets"); tbox.innerHTML = "";
      for (const name of Object.keys(targets())) tbox.appendChild(item(name, "", name === selected.target, () => {
        selected.target = name; selected.action = null; reload();
      }));

      const abox = $("actions"); abox.innerHTML = "";
      for (const action of actions()) abox.appendChild(item(action === "run" ? "执行" : action, action, action === selected.action, () => {
        selected.action = action; render();
      }));
      $("commands").value = commandList().join("\n");
    }

    function showProjectDialog() { $("projectId").value = ""; $("projectName").value = ""; $("projectType").value = "other"; $("projectDialog").showModal(); }
    function showServiceDialog() {
      if (!selected.project) return alert("请先选择项目。");
      $("serviceId").value = ""; $("serviceName").value = ""; $("serviceType").value = "other"; $("serviceTarget").value = "默认"; $("serviceCommands").value = "";
      $("serviceDialog").showModal();
    }
    function showTargetDialog() {
      if (!selected.project || !selected.service) return alert("请先选择服务。");
      $("targetName").value = "默认"; $("targetCommands").value = ""; $("targetDialog").showModal();
    }

    async function createProject() {
      await api("/api/project", { method: "POST", body: JSON.stringify({ id: $("projectId").value, name: $("projectName").value, type: $("projectType").value }) });
      selected.project = $("projectId").value.trim(); selected.service = null; selected.target = null; selected.action = null;
      $("projectDialog").close(); await reload();
    }
    async function createService() {
      await api("/api/service", { method: "POST", body: JSON.stringify({
        project_id: selected.project, id: $("serviceId").value, name: $("serviceName").value, type: $("serviceType").value,
        target_name: $("serviceTarget").value, commands: lines($("serviceCommands").value)
      }) });
      selected.service = $("serviceId").value.trim(); selected.target = $("serviceTarget").value.trim(); selected.action = "run";
      $("serviceDialog").close(); await reload();
    }
    async function createTarget() {
      await api("/api/target", { method: "POST", body: JSON.stringify({
        project_id: selected.project, service_id: selected.service, target_name: $("targetName").value, commands: lines($("targetCommands").value)
      }) });
      selected.target = $("targetName").value.trim(); selected.action = "run";
      $("targetDialog").close(); await reload();
    }
    async function saveCommands() {
      if (!selected.project || !selected.service || !selected.target) return alert("请先选择项目、服务、执行目标。");
      await api("/api/commands", { method: "POST", body: JSON.stringify({
        project_id: selected.project, service_id: selected.service, target_name: selected.target, action: selected.action || "run", commands: lines($("commands").value)
      }) });
      await reload();
      appendLog("已保存命令。\n");
    }
    async function deleteSelected(kind) {
      if (!confirm("确认删除？")) return;
      await api("/api/delete", { method: "POST", body: JSON.stringify({ kind, ...selected }) });
      if (kind === "project") selected = { project: null, service: null, target: null, action: null };
      if (kind === "service") { selected.service = null; selected.target = null; selected.action = null; }
      if (kind === "target") { selected.target = null; selected.action = null; }
      await reload();
    }
    async function execute() {
      if (!selected.project || !selected.service || !selected.target || !selected.action) return alert("请选择完整的项目、服务、执行目标和动作。");
      const data = await api("/api/execute", { method: "POST", body: JSON.stringify(selected) });
      activeSession = data.session_id; $("executeBtn").disabled = true; appendLog(`\n==== ${selected.project}/${selected.service} ${selected.target} ====\n`); poll();
    }
    async function statusCheck() {
      if (!selected.project || !selected.service || !selected.target) return alert("请选择完整的项目、服务、执行目标。");
      let cfg = targetCfg();
      if (!(cfg.status_commands || []).length) {
        const text = prompt("请输入状态检查命令，可粘贴多行：", "");
        if (!text) return;
        await api("/api/status-commands", { method: "POST", body: JSON.stringify({ project_id: selected.project, service_id: selected.service, target_name: selected.target, commands: lines(text) }) });
        await reload();
      }
      const data = await api("/api/status", { method: "POST", body: JSON.stringify(selected) });
      activeSession = data.session_id; appendLog(`\n==== ${selected.project}/${selected.service} ${selected.target} 状态检查 ====\n`); poll();
    }
    async function poll() {
      if (!activeSession) return;
      const data = await api(`/api/session?id=${encodeURIComponent(activeSession)}`);
      if (data.output) appendLog(data.output);
      if (data.done) { $("executeBtn").disabled = false; activeSession = null; return; }
      setTimeout(poll, 500);
    }
    function appendLog(text) {
      const log = $("log"); log.textContent += text;
      const lines = log.textContent.split("\n");
      if (lines.length > 1200) log.textContent = lines.slice(-1200).join("\n");
      log.scrollTop = log.scrollHeight;
    }
    function clearLog() { $("log").textContent = ""; }
    window.addEventListener("load", () => reload(false).catch(err => alert(err.message)));
  </script>
</body>
</html>
"""


class OutputBuffer:
    def __init__(self, session: dict[str, Any]) -> None:
        self.session = session

    def write(self, text: str) -> None:
        if not text:
            return
        self.session["queue"].put(text)


class Handler(BaseHTTPRequestHandler):
    server_version = "DeploySysWeb/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(INDEX_HTML)
        elif parsed.path == "/api/state":
            self.send_json(build_state())
        elif parsed.path == "/api/session":
            params = parse_qs(parsed.query)
            self.send_json(read_session(params.get("id", [""])[0]))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            if self.path == "/api/project":
                data = create_project(body)
            elif self.path == "/api/service":
                data = create_service(body)
            elif self.path == "/api/target":
                data = create_target(body)
            elif self.path == "/api/commands":
                data = save_commands(body)
            elif self.path == "/api/status-commands":
                data = save_status_commands(body)
            elif self.path == "/api/delete":
                data = delete_item(body)
            elif self.path == "/api/execute":
                data = start_execution(body, status=False)
            elif self.path == "/api/status":
                data = start_execution(body, status=True)
            else:
                self.send_error(404)
                return
            self.send_json(data)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, status=400)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("请求内容必须是 JSON 对象。")
        return data

    def send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def build_state() -> dict[str, Any]:
    deploysys.ensure_base_files()
    return {
        "config_path": str(deploysys.active_projects_file()),
        "projects": deploysys.load_projects().get("projects") or [],
    }


def load_projects() -> dict[str, Any]:
    deploysys.ensure_base_files()
    return deploysys.load_projects()


def required(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"缺少 {key}")
    return value


def command_lines(data: dict[str, Any]) -> list[str]:
    raw = data.get("commands") or []
    if not isinstance(raw, list):
        raise ValueError("commands 必须是数组。")
    return [str(item).rstrip() for item in raw if str(item).strip()]


def locate(projects: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    project = deploysys.find_project(projects, required(data, "project_id") if "project_id" in data else required(data, "project"))
    if not project:
        raise ValueError("项目不存在。")
    service = deploysys.find_service(project, required(data, "service_id") if "service_id" in data else required(data, "service"))
    if not service:
        raise ValueError("服务不存在。")
    target_name = required(data, "target_name") if "target_name" in data else required(data, "target")
    target = deploysys.service_targets(service).get(target_name)
    if not target:
        raise ValueError("执行目标不存在。")
    return project, service, target_name, target


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    project_id = required(data, "id")
    if deploysys.find_project(projects, project_id):
        raise ValueError("项目 ID 已存在。")
    projects.setdefault("projects", []).append(
        {
            "id": project_id,
            "name": required(data, "name"),
            "type": str(data.get("type") or "other").strip() or "other",
            "platform": deploysys.detect_platform() or deploysys.PLATFORM_MAC,
            "services": [],
        }
    )
    deploysys.save_projects(projects)
    return {"ok": True}


def create_service(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    project = deploysys.find_project(projects, required(data, "project_id"))
    if not project:
        raise ValueError("项目不存在。")
    service_id = required(data, "id")
    if deploysys.find_service(project, service_id):
        raise ValueError("服务 ID 已存在。")
    target_name = required(data, "target_name")
    project.setdefault("services", []).append(
        {
            "id": service_id,
            "name": str(data.get("name") or service_id).strip() or service_id,
            "type": str(data.get("type") or "other").strip() or "other",
            "targets": {target_name: {"commands": {deploysys.COMMAND_KEY: command_lines(data)}}},
        }
    )
    deploysys.save_projects(projects)
    return {"ok": True}


def create_target(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    project = deploysys.find_project(projects, required(data, "project_id"))
    if not project:
        raise ValueError("项目不存在。")
    service = deploysys.find_service(project, required(data, "service_id"))
    if not service:
        raise ValueError("服务不存在。")
    target_name = required(data, "target_name")
    targets = service.setdefault("targets", {})
    if target_name in targets:
        raise ValueError("执行目标已存在。")
    targets[target_name] = {"commands": {deploysys.COMMAND_KEY: command_lines(data)}}
    deploysys.save_projects(projects)
    return {"ok": True}


def save_commands(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    _project, _service, _target_name, target = locate(projects, data)
    action = str(data.get("action") or deploysys.COMMAND_KEY).strip() or deploysys.COMMAND_KEY
    target.setdefault("commands", {})[action] = command_lines(data)
    deploysys.save_projects(projects)
    return {"ok": True}


def save_status_commands(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    _project, _service, _target_name, target = locate(projects, data)
    target["status_commands"] = command_lines(data)
    deploysys.save_projects(projects)
    return {"ok": True}


def delete_item(data: dict[str, Any]) -> dict[str, Any]:
    projects = load_projects()
    kind = required(data, "kind")
    if kind == "project":
        project_id = required(data, "project")
        projects["projects"] = [item for item in projects.get("projects", []) if item.get("id") != project_id]
    elif kind == "service":
        project = deploysys.find_project(projects, required(data, "project"))
        if project:
            service_id = required(data, "service")
            project["services"] = [item for item in project.get("services", []) if item.get("id") != service_id]
    elif kind == "target":
        _project, service, target_name, _target = locate(projects, data)
        deploysys.service_targets(service).pop(target_name, None)
        if "targets" in service:
            service["targets"].pop(target_name, None)
    else:
        raise ValueError("删除类型不支持。")
    deploysys.save_projects(projects)
    return {"ok": True}


def start_execution(data: dict[str, Any], status: bool) -> dict[str, Any]:
    projects = load_projects()
    project, service, target_name, target = locate(projects, data)
    action = "状态检查" if status else str(data.get("action") or deploysys.COMMAND_KEY)
    commands = target.get("status_commands") if status else ((target.get("commands") or {}).get(action) or [])
    if not commands:
        raise ValueError("没有可执行命令。")
    settings = deploysys.load_yaml(deploysys.SETTINGS_FILE, deploysys.DEFAULT_SETTINGS)
    session_id = uuid.uuid4().hex
    session = {"queue": queue.Queue(), "done": False}
    with SESSIONS_LOCK:
        SESSIONS[session_id] = session

    def worker() -> None:
        try:
            deploysys.run_action_commands(
                project,
                service,
                target_name,
                target,
                action if status else deploysys.action_label(action),
                commands,
                settings,
                OutputBuffer(session).write,
            )
        except Exception as exc:  # noqa: BLE001
            session["queue"].put(f"\n错误: {exc}\n")
        finally:
            session["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "session_id": session_id}


def read_session(session_id: str) -> dict[str, Any]:
    with SESSIONS_LOCK:
        session = SESSIONS.get(session_id)
    if not session:
        return {"error": "执行会话不存在。"}
    chunks: list[str] = []
    while True:
        try:
            chunks.append(session["queue"].get_nowait())
        except queue.Empty:
            break
    done = bool(session["done"]) and not chunks
    if done:
        with SESSIONS_LOCK:
            SESSIONS.pop(session_id, None)
    return {"ok": True, "output": "".join(chunks), "done": done}


def find_free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("没有可用端口。")


def main() -> None:
    port = find_free_port()
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"deploy-sys 客户端已启动: {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

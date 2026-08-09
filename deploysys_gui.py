#!/usr/bin/env python3
"""deploy-sys 本地浏览器客户端。"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import deploysys
from deploysys_store import ConfigConflict, ConfigError


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_SCAN_COUNT = 30
MAX_BODY_BYTES = 1_000_000
APP_VERSION = "2.0.0"
WEB_DIR = Path(__file__).resolve().parent / "web"
REQUEST_TOKEN = secrets.token_urlsafe(32)


@dataclass
class Execution:
    id: str
    project_id: str
    service_id: str
    target_name: str
    action: str
    cancellation: deploysys.CancellationToken = field(default_factory=deploysys.CancellationToken)
    status: str = "running"
    exit_code: int | None = None
    log_path: str = ""
    output: str = ""
    output_base: int = 0
    output_end: int = 0
    done: bool = False


class ExecutionManager:
    """全局单任务执行器，页面刷新后仍可继续读取同一任务日志。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executions: dict[str, Execution] = {}
        self._active_id: str | None = None

    def start(
        self,
        project: dict[str, Any],
        service: dict[str, Any],
        target_name: str,
        target: dict[str, Any],
        action: str,
        commands: list[str],
    ) -> Execution:
        with self._lock:
            if self._active_id and not self._executions[self._active_id].done:
                raise ConfigError("已有任务正在执行，请等待完成或先取消当前任务。")
            execution = Execution(uuid.uuid4().hex, project["id"], service["id"], target_name, action)
            self._executions[execution.id] = execution
            self._active_id = execution.id
        settings = deploysys.load_yaml(deploysys.SETTINGS_FILE, deploysys.DEFAULT_SETTINGS)

        def emit(text: str) -> None:
            self._append_output(execution.id, text)

        def worker() -> None:
            try:
                results, log_path = deploysys.run_action_commands(
                    project,
                    service,
                    target_name,
                    target,
                    "状态检查" if action == "status" else "执行",
                    commands,
                    settings,
                    emit,
                    execution.cancellation,
                )
                result = results[-1] if results else None
                with self._lock:
                    execution.exit_code = result.exit_code if result else None
                    execution.log_path = str(log_path)
                    execution.status = deploysys.execution_status(
                        execution.exit_code if execution.exit_code is not None else 1,
                        execution.cancellation.cancelled(),
                        execution.exit_code == deploysys.COMMAND_IDLE_TIMEOUT_EXIT_CODE,
                    )
            except Exception as exc:  # noqa: BLE001
                self._append_output(execution.id, f"\n错误: {exc}\n")
                with self._lock:
                    execution.status = "failed"
            finally:
                with self._lock:
                    execution.done = True
                    if self._active_id == execution.id:
                        self._active_id = None

        threading.Thread(target=worker, name=f"deploysys-{execution.id[:8]}", daemon=True).start()
        return execution

    def cancel(self, execution_id: str) -> Execution:
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution:
                raise ConfigError("执行任务不存在。")
            if execution.done:
                raise ConfigError("执行任务已经结束。")
            execution.cancellation.cancel()
            return execution

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._active_id:
                return None
            return self._summary(self._executions[self._active_id])

    def shutdown(self) -> None:
        with self._lock:
            active_id = self._active_id
        if active_id:
            try:
                self.cancel(active_id)
            except ConfigError:
                pass

    def read(self, execution_id: str, cursor: int) -> dict[str, Any]:
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution:
                raise ConfigError("执行任务不存在或已过期。")
            cursor = max(cursor, execution.output_base)
            start = cursor - execution.output_base
            return {
                **self._summary(execution),
                "cursor": execution.output_end,
                "output": execution.output[start:],
                "truncated": cursor < execution.output_base,
            }

    def _append_output(self, execution_id: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            execution = self._executions[execution_id]
            execution.output += text
            execution.output_end += len(text)
            max_chars = 300_000
            if len(execution.output) > max_chars:
                dropped = len(execution.output) - max_chars
                execution.output = execution.output[dropped:]
                execution.output_base += dropped

    @staticmethod
    def _summary(execution: Execution) -> dict[str, Any]:
        return {
            "id": execution.id,
            "project_id": execution.project_id,
            "service_id": execution.service_id,
            "target_name": execution.target_name,
            "action": execution.action,
            "status": execution.status,
            "exit_code": execution.exit_code,
            "log_path": execution.log_path,
            "done": execution.done,
        }


EXECUTIONS = ExecutionManager()


def config_state() -> dict[str, Any]:
    deploysys.ensure_base_files()
    snapshot = deploysys.load_project_snapshot()
    return {
        "version": APP_VERSION,
        "config_path": str(deploysys.active_projects_file()),
        "revision": snapshot.revision,
        "recovered_from_backup": snapshot.recovered_from_backup,
        "projects": snapshot.data.get("projects") or [],
        "active_execution": EXECUTIONS.active(),
    }


def required(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ConfigError(f"缺少 {key}。")
    return value


def command_lines(data: dict[str, Any], field_name: str = "commands") -> list[str]:
    raw = data.get(field_name) or []
    if not isinstance(raw, list):
        raise ConfigError("命令必须是数组。")
    lines = [str(item).rstrip() for item in raw if str(item).strip()]
    if not lines:
        raise ConfigError("至少需要输入一行命令。")
    return lines


def expected_revision(data: dict[str, Any]) -> int:
    value = data.get("revision")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("配置版本无效，请刷新后重试。")
    return value


def find_project(data: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = deploysys.find_project(data, project_id)
    if not project:
        raise ConfigError("项目不存在。")
    return project


def find_service(project: dict[str, Any], service_id: str) -> dict[str, Any]:
    service = deploysys.find_service(project, service_id)
    if not service:
        raise ConfigError("服务不存在。")
    return service


def find_target(service: dict[str, Any], target_name: str) -> dict[str, Any]:
    target = (service.get("targets") or {}).get(target_name)
    if not isinstance(target, dict):
        raise ConfigError("执行目标不存在。")
    return target


def mutation(data: dict[str, Any], update: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    snapshot = deploysys.projects_store().mutate(expected_revision(data), update)
    return {
        "ok": True,
        "state": {
            "version": APP_VERSION,
            "config_path": str(deploysys.active_projects_file()),
            "revision": snapshot.revision,
            "recovered_from_backup": snapshot.recovered_from_backup,
            "projects": snapshot.data.get("projects") or [],
            "active_execution": EXECUTIONS.active(),
        },
    }


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    project_id, name = required(data, "id"), required(data, "name")

    def update(projects: dict[str, Any]) -> None:
        if deploysys.find_project(projects, project_id):
            raise ConfigError("项目 ID 已存在。")
        projects.setdefault("projects", []).append(
            {
                "id": project_id,
                "name": name,
                "type": "other",
                "platform": deploysys.detect_platform() or deploysys.PLATFORM_MAC,
                "services": [],
            }
        )

    return mutation(data, update)


def update_project(data: dict[str, Any]) -> dict[str, Any]:
    old_id, new_id, name = required(data, "project_id"), required(data, "id"), required(data, "name")

    def update(projects: dict[str, Any]) -> None:
        project = find_project(projects, old_id)
        if new_id != old_id and deploysys.find_project(projects, new_id):
            raise ConfigError("项目 ID 已存在。")
        project["id"], project["name"] = new_id, name

    return mutation(data, update)


def create_service(data: dict[str, Any]) -> dict[str, Any]:
    project_id, service_id = required(data, "project_id"), required(data, "id")
    target_name, commands = required(data, "target_name"), command_lines(data)
    service_name = str(data.get("name") or service_id).strip() or service_id

    def update(projects: dict[str, Any]) -> None:
        project = find_project(projects, project_id)
        if deploysys.find_service(project, service_id):
            raise ConfigError("服务 ID 已存在。")
        project.setdefault("services", []).append(
            {
                "id": service_id,
                "name": service_name,
                "type": "other",
                "targets": {target_name: {"shell": "auto", "commands": {deploysys.COMMAND_KEY: commands}}},
            }
        )

    return mutation(data, update)


def update_service(data: dict[str, Any]) -> dict[str, Any]:
    project_id, old_id = required(data, "project_id"), required(data, "service_id")
    new_id, name = required(data, "id"), required(data, "name")

    def update(projects: dict[str, Any]) -> None:
        project = find_project(projects, project_id)
        service = find_service(project, old_id)
        if new_id != old_id and deploysys.find_service(project, new_id):
            raise ConfigError("服务 ID 已存在。")
        service["id"], service["name"] = new_id, name

    return mutation(data, update)


def create_target(data: dict[str, Any]) -> dict[str, Any]:
    project_id, service_id, target_name = required(data, "project_id"), required(data, "service_id"), required(data, "target_name")
    commands = command_lines(data)
    shell = str(data.get("shell") or "auto")

    def update(projects: dict[str, Any]) -> None:
        service = find_service(find_project(projects, project_id), service_id)
        targets = service.setdefault("targets", {})
        if target_name in targets:
            raise ConfigError("执行目标已存在。")
        targets[target_name] = {"shell": shell, "commands": {deploysys.COMMAND_KEY: commands}}

    return mutation(data, update)


def update_target(data: dict[str, Any]) -> dict[str, Any]:
    project_id, service_id, old_name = required(data, "project_id"), required(data, "service_id"), required(data, "target_name")
    new_name, shell = required(data, "name"), str(data.get("shell") or "auto")

    def update(projects: dict[str, Any]) -> None:
        service = find_service(find_project(projects, project_id), service_id)
        targets = service.setdefault("targets", {})
        target = find_target(service, old_name)
        if new_name != old_name and new_name in targets:
            raise ConfigError("执行目标已存在。")
        target["shell"] = shell
        if new_name != old_name:
            targets[new_name] = targets.pop(old_name)

    return mutation(data, update)


def save_commands(data: dict[str, Any]) -> dict[str, Any]:
    project_id, service_id, target_name = required(data, "project_id"), required(data, "service_id"), required(data, "target_name")
    mode = str(data.get("mode") or "run")
    if mode not in {"run", "status"}:
        raise ConfigError("命令类型不支持。")
    commands = command_lines(data)
    shell = str(data.get("shell") or "auto").lower()
    if shell not in {"auto", "zsh", "bash", "powershell", "cmd"}:
        raise ConfigError("Shell 配置无效。")

    def update(projects: dict[str, Any]) -> None:
        target = find_target(find_service(find_project(projects, project_id), service_id), target_name)
        if mode == "status":
            target["status_commands"] = commands
        else:
            target.setdefault("commands", {})[deploysys.COMMAND_KEY] = commands
        target["shell"] = shell

    return mutation(data, update)


def delete_item(data: dict[str, Any]) -> dict[str, Any]:
    kind = required(data, "kind")
    project_id = required(data, "project_id")

    def update(projects: dict[str, Any]) -> None:
        project = find_project(projects, project_id)
        if kind == "project":
            projects["projects"] = [item for item in projects.get("projects") or [] if item.get("id") != project_id]
        elif kind == "service":
            service_id = required(data, "service_id")
            find_service(project, service_id)
            project["services"] = [item for item in project.get("services") or [] if item.get("id") != service_id]
        elif kind == "target":
            service = find_service(project, required(data, "service_id"))
            target_name = required(data, "target_name")
            find_target(service, target_name)
            service["targets"].pop(target_name)
        else:
            raise ConfigError("删除类型不支持。")

    return mutation(data, update)


def start_execution(data: dict[str, Any], status: bool = False) -> dict[str, Any]:
    projects = deploysys.load_project_snapshot().data
    project = find_project(projects, required(data, "project_id"))
    service = find_service(project, required(data, "service_id"))
    target_name = required(data, "target_name")
    target = find_target(service, target_name)
    commands = target.get("status_commands") if status else (target.get("commands") or {}).get(deploysys.COMMAND_KEY)
    if not isinstance(commands, list) or not commands:
        raise ConfigError("当前执行目标没有可执行命令。")
    execution = EXECUTIONS.start(project, service, target_name, target, "status" if status else "run", commands)
    return {"ok": True, "execution": EXECUTIONS._summary(execution)}


def cancel_execution(data: dict[str, Any]) -> dict[str, Any]:
    execution = EXECUTIONS.cancel(required(data, "execution_id"))
    return {"ok": True, "execution": EXECUTIONS._summary(execution)}


class Handler(BaseHTTPRequestHandler):
    server_version = "DeploySysWeb/2.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_html(render_index())
            elif parsed.path == "/app.js":
                self.send_static(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
            elif parsed.path == "/styles.css":
                self.send_static(WEB_DIR / "styles.css", "text/css; charset=utf-8")
            elif parsed.path == "/api/health":
                self.send_json({"app": "deploy-sys", "version": APP_VERSION})
            elif parsed.path == "/api/state":
                self.require_token()
                self.send_json(config_state())
            elif parsed.path.startswith("/api/executions/"):
                self.require_token()
                execution_id = parsed.path.rsplit("/", 1)[-1]
                cursor = int(parse_qs(parsed.query).get("cursor", ["0"])[0] or 0)
                self.send_json(EXECUTIONS.read(execution_id, cursor))
            elif parsed.path == "/api/execution":
                self.require_token()
                self.send_json({"active_execution": EXECUTIONS.active()})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ConfigConflict as exc:
            self.send_json({"error": str(exc), "code": "conflict"}, HTTPStatus.CONFLICT)
        except (ConfigError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        try:
            self.require_token()
            body = self.read_json()
            if self.path == "/api/projects":
                data = create_project(body)
            elif self.path == "/api/projects/update":
                data = update_project(body)
            elif self.path == "/api/services":
                data = create_service(body)
            elif self.path == "/api/services/update":
                data = update_service(body)
            elif self.path == "/api/targets":
                data = create_target(body)
            elif self.path == "/api/targets/update":
                data = update_target(body)
            elif self.path == "/api/commands":
                data = save_commands(body)
            elif self.path == "/api/delete":
                data = delete_item(body)
            elif self.path == "/api/executions":
                data = start_execution(body)
            elif self.path == "/api/status-executions":
                data = start_execution(body, status=True)
            elif self.path == "/api/executions/cancel":
                data = cancel_execution(body)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_json(data)
        except ConfigConflict as exc:
            self.send_json({"error": str(exc), "code": "conflict"}, HTTPStatus.CONFLICT)
        except (ConfigError, ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_OPTIONS(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def require_token(self) -> None:
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost", "[::1]"}:
            raise ConfigError("请求主机不允许。")
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ConfigError("请求来源不允许。")
        if self.headers.get("X-Deploy-Sys-Token") != REQUEST_TOKEN:
            raise ConfigError("客户端会话已失效，请刷新页面。")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > MAX_BODY_BYTES:
            raise ConfigError("请求内容过大。")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ConfigError("请求内容必须是对象。")
        return data

    def send_html(self, html: str) -> None:
        self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

    def send_static(self, path: Path, content_type: str) -> None:
        self.send_bytes(path.read_bytes(), content_type)

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def send_bytes(self, payload: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self' 'nonce-deploysys'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)


def render_index() -> str:
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("__DEPLOY_SYS_TOKEN__", REQUEST_TOKEN).replace("__APP_VERSION__", APP_VERSION)


def existing_instance_url() -> str | None:
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_COUNT):
        url = f"http://{HOST}:{port}/api/health"
        try:
            with urllib.request.urlopen(url, timeout=0.2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("app") == "deploy-sys":
                    return f"http://{HOST}:{port}/"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            continue
    return None


def find_free_port() -> int:
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_COUNT):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有可用端口。")


def main() -> None:
    deploysys.ensure_base_files()
    existing = existing_instance_url()
    if existing:
        print(f"deploy-sys 已在运行，已打开: {existing}")
        webbrowser.open(existing)
        return
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
        EXECUTIONS.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

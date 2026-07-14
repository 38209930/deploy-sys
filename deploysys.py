#!/usr/bin/env python3
"""统一项目部署运维 CLI."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import platform
import queue
import re
import signal
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from prompt_toolkit import prompt as pt_prompt


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
LOGS_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
PROJECTS_FILE = CONFIG_DIR / "projects.yaml"
PROJECTS_LOCAL_FILE = CONFIG_DIR / "projects.local.yaml"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
DEFAULT_SECRETS_FILE = CONFIG_DIR / "secrets.enc"
TEMP_SECRETS_FILE = CONFIG_DIR / "secrets.yaml"
GITIGNORE_FILE = ROOT / ".gitignore"

SENSITIVE_NAME_RE = re.compile(r"(password|passwd|pwd|token|secret|key|access[_-]?key)", re.I)
TOKEN_RE = re.compile(
    r"(?i)\b((?:token|password|passwd|pwd|secret|access[_-]?key|api[_-]?key)\s*[:=]\s*)"
    r"([^\s'\";,]+)"
)
LONG_SECRET_RE = re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b")


DEFAULT_SETTINGS = {
    "app": {"default_environment": "test", "log_retention_days": 30},
    "security": {
        "secrets_file": "config/secrets.enc",
        "require_master_password": True,
        "mask_secrets_in_output": True,
        "block_commit_if_secret_file_staged": True,
    },
    "safety": {
        "require_strong_confirm_for_prod": True,
        "require_confirm_for_git_push": True,
        "stop_on_command_failure": True,
    },
    "execution": {
        "command_idle_timeout_seconds": 300,
    },
}


DEFAULT_PROJECTS = {"projects": []}
COMMAND_KEY = "run"
ACTION_ORDER = (COMMAND_KEY, "build", "deploy", "start", "stop", "restart", "logs")
PLATFORM_MAC = "mac"
PLATFORM_WINDOWS = "windows"
COMMAND_IDLE_TIMEOUT_EXIT_CODE = 124


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str


class ConfigError(Exception):
    pass


class SecretError(Exception):
    pass


def prompt_text(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = pt_prompt(f"{message}{suffix}: ")
    if not value and default:
        return default
    return value


def prompt_secret(message: str) -> str:
    return pt_prompt(f"{message}: ", is_password=True)


def main() -> int:
    ensure_base_files()
    settings = load_yaml(SETTINGS_FILE, DEFAULT_SETTINGS)
    projects = load_projects()

    if not projects.get("projects"):
        print("检测到还没有项目配置，进入首次启动向导。")
        first_run_wizard(settings, projects)
        projects = load_projects()

    while True:
        print("\n==== deploy-sys ====")
        print("1. 项目部署/服务操作")
        print("2. 服务状态检查")
        print("3. 新增项目")
        print("4. 查看项目配置")
        print("5. 删除已录入内容")
        print("0. 退出")
        choice = prompt_text("请选择").strip()
        if choice == "1":
            project_flow(settings, projects)
        elif choice == "2":
            status_flow(settings, projects)
        elif choice == "3":
            add_project_wizard(projects, settings)
            projects = load_projects()
        elif choice == "4":
            view_project_flow(projects)
        elif choice == "5":
            delete_config_flow(projects)
            projects = load_projects()
        elif choice == "0":
            return 0
        else:
            print("无效选择。")


def ensure_base_files() -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    if not SETTINGS_FILE.exists():
        write_yaml(SETTINGS_FILE, DEFAULT_SETTINGS)
    if not PROJECTS_FILE.exists():
        write_yaml(PROJECTS_FILE, DEFAULT_PROJECTS)
    ensure_gitignore()


def ensure_gitignore() -> None:
    required = [
        "config/secrets*",
        "config/projects.local.yaml",
        "logs/",
        "data/local*",
        "data/operation_logs.jsonl",
        "__pycache__/",
        ".pytest_cache/",
    ]
    existing = GITIGNORE_FILE.read_text(encoding="utf-8").splitlines() if GITIGNORE_FILE.exists() else []
    changed = False
    for item in required:
        if item not in existing:
            existing.append(item)
            changed = True
    if changed or not GITIGNORE_FILE.exists():
        GITIGNORE_FILE.write_text("\n".join(existing).strip() + "\n", encoding="utf-8")


def load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} 必须是 YAML 对象。")
    return data


def active_projects_file() -> Path:
    return PROJECTS_LOCAL_FILE if PROJECTS_LOCAL_FILE.exists() else PROJECTS_FILE


def load_projects() -> dict[str, Any]:
    return load_yaml(active_projects_file(), DEFAULT_PROJECTS)


def save_projects(projects: dict[str, Any]) -> None:
    write_yaml(PROJECTS_LOCAL_FILE, projects)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def first_run_wizard(settings: dict[str, Any], projects: dict[str, Any]) -> None:
    setup_master_password(settings)
    add_project_wizard(projects, settings)


def setup_master_password(settings: dict[str, Any]) -> None:
    secrets_path = get_secrets_path(settings)
    if secrets_path.exists():
        return
    while True:
        pwd1 = prompt_secret("请设置密钥主密码")
        pwd2 = prompt_secret("请再次输入主密码")
        if not pwd1:
            print("主密码不能为空。")
            continue
        if pwd1 != pwd2:
            print("两次主密码不一致。")
            continue
        save_secrets({}, pwd1, secrets_path)
        print(f"已创建加密密钥文件: {secrets_path}")
        return


def add_project_wizard(projects: dict[str, Any], settings: dict[str, Any]) -> None:
    project_id = ask_required("项目 ID，例如 mall-api")
    existing_project = find_project(projects, project_id)
    if existing_project:
        print("项目已存在，当前配置如下：")
        print(render_project_details(existing_project))
        if confirm("是否继续为该项目新增子任务？"):
            append_services_to_project(existing_project, settings)
            save_projects(projects)
        return

    name = ask_required("项目名称")
    project_type = prompt_text("项目分组类型(dotnet/java/vue3/other，默认 other)", "other").strip() or "other"
    project_platform = ask_project_platform()
    project = {
        "id": project_id,
        "name": name,
        "type": project_type,
        "platform": project_platform,
        "services": [],
    }
    projects.setdefault("projects", []).append(project)
    append_services_to_project(project, settings)
    save_projects(projects)
    print(f"已写入项目配置: {PROJECTS_LOCAL_FILE}")


def append_services_to_project(project: dict[str, Any], settings: dict[str, Any]) -> None:
    services: list[dict[str, Any]] = []
    while True:
        service = collect_service_config(project)
        if not service:
            if confirm("是否继续处理其他子任务？"):
                continue
            break
        services.append(service)
        if not confirm("是否继续新增下一个服务？"):
            break
    project.setdefault("services", []).extend(services)


def collect_service_config(project: dict[str, Any]) -> dict[str, Any] | None:
    print("\n配置服务")
    service_id, service_name, service_type = collect_service_identity(project)
    if not service_id:
        return None
    envs: dict[str, Any] = {}
    for env_name in ("test", "prod"):
        print(f"\n配置 {service_name} 的 {env_name} 环境")
        commands = ask_environment_commands(env_name)
        envs[env_name] = {
            "commands": commands,
        }
    return {
        "id": service_id,
        "name": service_name,
        "type": service_type,
        "environments": envs,
    }


def collect_service_identity(project: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    while True:
        service_id = ask_required(f"服务 ID，例如 {project['id']}-api / front-api")
        existing_service = find_service(project, service_id)
        if existing_service:
            print("子任务已存在，当前配置如下：")
            print(render_service_details(existing_service))
            return None, None, None
        service_name = ask_required("服务名称")
        service_type = prompt_text("服务类型(dotnet/java/vue3/other，默认 other)", "other").strip() or "other"
        print("请确认服务基础信息：")
        print(f"- 服务 ID: {service_id}")
        print(f"- 服务名称: {service_name}")
        print(f"- 服务类型: {service_type}")
        if confirm("以上信息是否正确？"):
            return service_id, service_name, service_type
        print("已取消本次输入，请重新录入服务基础信息。")


def ask_required(prompt: str) -> str:
    while True:
        value = prompt_text(prompt).strip()
        if value:
            return value
        print("不能为空。")


def detect_platform() -> str | None:
    system = platform.system()
    if system == "Darwin":
        return PLATFORM_MAC
    if system == "Windows":
        return PLATFORM_WINDOWS
    return None


def normalize_platform(value: str) -> str | None:
    lowered = value.strip().lower()
    if lowered in {"mac", "macos", "darwin", "osx"}:
        return PLATFORM_MAC
    if lowered in {"windows", "win", "win32"}:
        return PLATFORM_WINDOWS
    return None


def platform_label(platform_value: str) -> str:
    return "macOS" if platform_value == PLATFORM_MAC else "Windows"


def ask_project_platform() -> str:
    detected = detect_platform()
    if detected:
        print(f"已识别当前系统: {platform_label(detected)}")
        while True:
            raw = prompt_text("项目运行系统(mac/windows)", detected).strip()
            if not raw:
                return detected
            normalized = normalize_platform(raw)
            if normalized:
                return normalized
            print("请输入 mac 或 windows。")
    print("未能自动识别系统类型，请手动选择。")
    while True:
        print("1. macOS")
        print("2. Windows")
        choice = prompt_text("请选择").strip()
        if choice == "1":
            return PLATFORM_MAC
        if choice == "2":
            return PLATFORM_WINDOWS
        print("无效选择。")


def ask_environment_commands(env_name: str) -> dict[str, list[str]]:
    commands = ask_command_lines(f"{env_name} 环境命令")
    return {COMMAND_KEY: commands} if commands else {}


def ask_command_lines(label: str = "命令") -> list[str]:
    print(f"{label}逐行输入，空行结束。")
    commands: list[str] = []
    while True:
        prompt = f"命令[{len(commands) + 1}]"
        raw = prompt_text(prompt)
        if not raw.strip():
            break
        commands.append(raw.rstrip())
    return commands


def find_project(projects: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    for project in projects.get("projects") or []:
        if project.get("id") == project_id:
            return project
    return None


def find_service(project: dict[str, Any], service_id: str) -> dict[str, Any] | None:
    for service in project_services(project):
        if service.get("id") == service_id:
            return service
    return None


def select_project(projects: dict[str, Any]) -> dict[str, Any] | None:
    items = projects.get("projects") or []
    if not items:
        print("还没有项目配置。")
        return None
    for idx, project in enumerate(items, 1):
        print(f"{idx}. {project.get('name')} ({project.get('id')})")
    choice = prompt_text("请选择项目").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(items):
        print("无效项目。")
        return None
    return items[int(choice) - 1]


def view_project_flow(projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    print(f"项目配置文件: {active_projects_file()}")
    print(render_project_details(project))


def delete_config_flow(projects: dict[str, Any]) -> None:
    print("1. 删除整个项目")
    print("2. 删除项目里的子任务")
    print("3. 删除环境下保存的命令")
    choice = prompt_text("请选择删除类型").strip()
    if choice == "1":
        delete_project_flow(projects)
    elif choice == "2":
        delete_service_flow(projects)
    elif choice == "3":
        delete_action_commands_flow(projects)
    else:
        print("无效选择。")


def select_service(project: dict[str, Any]) -> dict[str, Any] | None:
    services = project_services(project)
    if not services:
        print("项目下没有服务配置。")
        return None
    for idx, service in enumerate(services, 1):
        print(f"{idx}. {service.get('name')} ({service.get('id')})")
    choice = prompt_text("请选择服务").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(services):
        print("无效服务。")
        return None
    return services[int(choice) - 1]


def select_action(commands: dict[str, list[str]]) -> str | None:
    actions = [action for action in ACTION_ORDER if commands.get(action)]
    if not actions:
        print("当前环境没有可删除的命令。")
        return None
    if actions == [COMMAND_KEY]:
        return COMMAND_KEY
    for idx, action in enumerate(actions, 1):
        print(f"{idx}. {action_label(action)}")
    choice = prompt_text("请选择要删除的命令组").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
        print("无效动作。")
        return None
    return actions[int(choice) - 1]


def project_services(project: dict[str, Any]) -> list[dict[str, Any]]:
    services = project.get("services")
    if isinstance(services, list) and services:
        return services
    # 兼容旧版单服务配置
    if project.get("repo") or project.get("environments"):
        return [
            {
                "id": project.get("id", "default"),
                "name": project.get("name", "default"),
                "type": project.get("type", "other"),
                "environments": project.get("environments", {}),
            }
        ]
    return []


def render_project_details(project: dict[str, Any]) -> str:
    lines = [
        f"项目: {project.get('name')} ({project.get('id')})",
        f"类型: {project.get('type', 'other')}",
    ]
    platform_value = project.get("platform")
    if platform_value:
        lines.append(f"运行系统: {platform_label(platform_value)}")
    services = project_services(project)
    if not services:
        lines.append("子任务: 无")
        return "\n".join(lines)
    lines.append("子任务:")
    for service in services:
        lines.extend(render_service_lines(service))
    return "\n".join(lines)


def render_service_details(service: dict[str, Any]) -> str:
    return "\n".join(render_service_lines(service))


def render_service_lines(service: dict[str, Any]) -> list[str]:
    lines = [
        f"- {service.get('name')} ({service.get('id')}) [{service.get('type', 'other')}]",
    ]
    for env_name in ("test", "prod"):
        env_cfg = (service.get("environments") or {}).get(env_name)
        if not env_cfg:
            continue
        lines.append(f"  {env_name}:")
        status_commands = env_cfg.get("status_commands") or []
        if status_commands:
            lines.append("    状态检查命令:")
            for command in status_commands:
                lines.append(f"      {command}")
        commands = env_cfg.get("commands") or {}
        if not commands:
            lines.append("    commands=-")
            continue
        for action in ACTION_ORDER:
            action_commands = commands.get(action) or []
            if action_commands:
                lines.append(f"    {action_label(action)}:")
                for command in action_commands:
                    lines.append(f"      {command}")
    return lines


def action_label(action: str) -> str:
    return "命令" if action == COMMAND_KEY else action


def select_environment(project: dict[str, Any], default: str = "test") -> tuple[str, dict[str, Any]] | None:
    envs = project.get("environments") or {}
    available = [env for env in ("test", "prod") if env in envs]
    if not available:
        print("项目未配置 test/prod 环境。")
        return None
    for idx, env in enumerate(available, 1):
        mark = "默认" if env == default else ""
        print(f"{idx}. {env} {mark}")
    choice = prompt_text("请选择环境").strip()
    if not choice:
        choice = str(available.index(default) + 1) if default in available else "1"
    if not choice.isdigit() or not 1 <= int(choice) <= len(available):
        print("无效环境。")
        return None
    env_name = available[int(choice) - 1]
    return env_name, envs[env_name]


def project_flow(settings: dict[str, Any], projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    service = select_service(project)
    if not service:
        return
    selected = select_environment(service, settings.get("app", {}).get("default_environment", "test"))
    if not selected:
        return
    env_name, env_cfg = selected
    commands = env_cfg.get("commands") or {}
    actions = [a for a in ACTION_ORDER if commands.get(a)]
    if not actions:
        print("该环境没有可执行命令。")
        return
    if actions == [COMMAND_KEY]:
        execute_action(project, service, env_name, env_cfg, COMMAND_KEY, commands[COMMAND_KEY], settings)
        return
    for idx, action in enumerate(actions, 1):
        print(f"{idx}. {action_label(action)}")
    choice = prompt_text("请选择要执行的命令组").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
        print("无效动作。")
        return
    action = actions[int(choice) - 1]
    execute_action(project, service, env_name, env_cfg, action, commands[action], settings)


def execute_action(
    project: dict[str, Any],
    service: dict[str, Any],
    env_name: str,
    env_cfg: dict[str, Any],
    action: str,
    commands: list[str],
    settings: dict[str, Any],
) -> None:
    confirm_action = action_label(action)
    if env_name == "prod" and settings.get("safety", {}).get("require_strong_confirm_for_prod", True):
        if not strong_confirm(f"{project['id']}/{service['id']}", env_name, confirm_action):
            return
    if any(command_has_inline_secret(cmd) for cmd in commands):
        print("警告：命令中疑似包含明文密码或 token。")
        if not strong_confirm(f"{project['id']}/{service['id']}", env_name, confirm_action):
            return

    runner = CommandRunner(settings, {})
    results = []
    for command in commands:
        result = runner.run(command, project, service, env_name, env_cfg, confirm_action)
        results.append(result)
        print(f"退出码: {result.exit_code}")
        if result.exit_code != 0 and settings.get("safety", {}).get("stop_on_command_failure", True):
            print("命令失败，已停止后续步骤。")
            break
    write_audit_log(project, service, env_name, env_cfg, confirm_action, results, runner.log_path)
    print(f"日志: {runner.log_path}")


def command_idle_timeout_seconds(settings: dict[str, Any]) -> int:
    raw = settings.get("execution", {}).get("command_idle_timeout_seconds", 300)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 300


def command_process_options() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            proc.kill()


def enqueue_process_output(proc: subprocess.Popen[str], output_queue: queue.Queue[str | None]) -> None:
    if not proc.stdout:
        output_queue.put(None)
        return
    try:
        while True:
            chunk = proc.stdout.read(1)
            if chunk == "":
                break
            output_queue.put(chunk)
    finally:
        output_queue.put(None)


class CommandRunner:
    def __init__(self, settings: dict[str, Any], secrets: dict[str, str]) -> None:
        self.settings = settings
        self.secrets = secrets
        today = dt.datetime.now().strftime("%Y-%m-%d")
        log_dir = LOGS_DIR / today
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{dt.datetime.now().strftime('%H%M%S')}.log"

    def run(
        self,
        command: str,
        project: dict[str, Any],
        service: dict[str, Any],
        env_name: str,
        env_cfg: dict[str, Any],
        action: str,
    ) -> CommandResult:
        masked_command = mask_text(command, self.secrets.values())
        print(f"执行: {masked_command}")
        start = dt.datetime.now()
        env = os.environ.copy()
        env.update(self.secrets)
        proc = subprocess.Popen(
            command,
            cwd=None,
            env=env,
            shell=True,
            text=True,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **command_process_options(),
        )
        output_chunks: list[str] = []
        idle_timeout = command_idle_timeout_seconds(self.settings)
        last_output_at = dt.datetime.now()
        output_queue: queue.Queue[str | None] = queue.Queue()
        reader = threading.Thread(target=enqueue_process_output, args=(proc, output_queue), daemon=True)
        reader.start()
        timed_out = False
        with self.log_path.open("a", encoding="utf-8") as fh:
            host = env_cfg.get("host", "-") if isinstance(env_cfg, dict) else "-"
            fh.write(f"project={project.get('id')} service={service.get('id')} env={env_name} action={action} host={host}\n")
            fh.write(f"started_at={start.isoformat()}\n")
            fh.write(f"command={masked_command}\n")
            fh.write("--- output ---\n")
            while True:
                try:
                    chunk = output_queue.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None and not reader.is_alive():
                        break
                    idle_seconds = (dt.datetime.now() - last_output_at).total_seconds()
                    if idle_timeout and idle_seconds >= idle_timeout:
                        timeout_message = (
                            f"\n命令超过 {idle_timeout} 秒没有输出，已终止。"
                            "如远端备份或上传需要更久，可调整 settings.yaml 中的 "
                            "execution.command_idle_timeout_seconds，设为 0 可关闭。\n"
                        )
                        output_chunks.append(timeout_message)
                        print(timeout_message, end="", flush=True)
                        fh.write(timeout_message)
                        fh.flush()
                        timed_out = True
                        terminate_process_tree(proc)
                        break
                    continue
                if chunk is None:
                    if proc.poll() is not None:
                        break
                    continue
                last_output_at = dt.datetime.now()
                output_chunks.append(chunk)
                masked_chunk = mask_text(chunk, self.secrets.values())
                print(masked_chunk, end="", flush=True)
                fh.write(masked_chunk)
                fh.flush()
            if proc.stdout:
                proc.stdout.close()
        reader.join(timeout=1)
        exit_code = COMMAND_IDLE_TIMEOUT_EXIT_CODE if timed_out else proc.wait()
        end = dt.datetime.now()
        raw_output = "".join(output_chunks)
        output = mask_text(raw_output, self.secrets.values())
        with self.log_path.open("a", encoding="utf-8") as fh:
            if output and not output.endswith("\n"):
                fh.write("\n")
            fh.write(f"finished_at={end.isoformat()} exit_code={exit_code}\n")
            if exit_code == 0:
                cleaned_paths = cleanup_temp_publish_dirs(raw_output)
                for cleaned_path in cleaned_paths:
                    fh.write(f"cleanup_temp_dir={cleaned_path}\n")
                    print(f"已清理本地临时发布目录: {cleaned_path}")
        return CommandResult(masked_command, exit_code, output)

    def append_log(
        self,
        project: dict[str, Any],
        service: dict[str, Any],
        env_name: str,
        action: str,
        host: str,
        command: str,
        exit_code: int,
        output: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> None:
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"project={project.get('id')} service={service.get('id')} env={env_name} action={action} host={host}\n")
            fh.write(f"started_at={start.isoformat()} finished_at={end.isoformat()} exit_code={exit_code}\n")
            fh.write(f"command={command}\n")
            fh.write(output)
            if output and not output.endswith("\n"):
                fh.write("\n")


def command_has_inline_secret(command: str) -> bool:
    return bool(TOKEN_RE.search(command) or re.search(r"(?i)--(?:password|token|secret|key)[=\s]\S+", command))


def cleanup_temp_publish_dirs(output: str) -> list[str]:
    temp_root = Path(tempfile.gettempdir()).resolve()
    cleaned: list[str] = []
    for raw_path in re.findall(r"(/[^\s'\"`]+)", output):
        candidate = Path(raw_path.rstrip(".,;:)"))
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_dir():
            continue
        if temp_root not in resolved.parents:
            continue
        if not re.fullmatch(r"[^/]+\.[A-Za-z0-9]{4,}", resolved.name):
            continue
        shutil.rmtree(resolved)
        cleaned.append(str(resolved))
    return cleaned


def mask_text(text: str, secret_values: Iterable[str]) -> str:
    masked = text
    for value in secret_values:
        if value:
            masked = masked.replace(str(value), "******")
    masked = TOKEN_RE.sub(lambda m: m.group(1) + "******", masked)
    masked = LONG_SECRET_RE.sub(lambda m: "******" if looks_like_secret(m.group(0)) else m.group(0), masked)
    return masked


def looks_like_secret(value: str) -> bool:
    return bool(re.search(r"[A-Z]", value) and re.search(r"[a-z]", value) and re.search(r"\d", value))


def strong_confirm(project_id: str, env_name: str, action: str) -> bool:
    phrase = f"{project_id} {env_name} {action}"
    typed = prompt_text(f"高风险操作，请输入确认词 `{phrase}`").strip()
    if typed != phrase:
        print("确认词不匹配，已取消。")
        return False
    return True


def confirm(prompt: str) -> bool:
    return prompt_text(f"{prompt} [y/N]").strip().lower() == "y"


def write_audit_log(
    project: dict[str, Any],
    service: dict[str, Any],
    env_name: str,
    env_cfg: dict[str, Any],
    action: str,
    results: list[CommandResult],
    log_path: Path,
) -> None:
    audit_file = DATA_DIR / "operation_logs.jsonl"
    record = {
        "project_id": project.get("id"),
        "service_id": service.get("id"),
        "env_name": env_name,
        "action_name": action,
        "target_host": "-",
        "commands": [r.command for r in results],
        "exit_code": results[-1].exit_code if results else None,
        "created_at": dt.datetime.now().isoformat(),
        "log_file": str(log_path),
    }
    with audit_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_secrets_path(settings: dict[str, Any]) -> Path:
    raw = settings.get("security", {}).get("secrets_file") or str(DEFAULT_SECRETS_FILE)
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def save_secrets(secrets: dict[str, str], password: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    key = derive_fernet_key(password, salt)
    token = Fernet(key).encrypt(json.dumps(secrets, ensure_ascii=False).encode("utf-8"))
    payload = {
        "version": 1,
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": 390000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token.decode("ascii"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_secrets(password: str, path: Path) -> dict[str, str]:
    if not path.exists():
        raise SecretError(f"密钥文件不存在: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    salt = base64.b64decode(payload["salt"])
    token = payload["ciphertext"].encode("ascii")
    key = derive_fernet_key(password, salt)
    try:
        raw = Fernet(key).decrypt(token)
    except InvalidToken as exc:
        raise SecretError("主密码错误或密钥文件已损坏。") from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise SecretError("密钥文件内容非法。")
    return {str(k): str(v) for k, v in data.items()}


def secrets_flow(settings: dict[str, Any]) -> None:
    path = get_secrets_path(settings)
    if not path.exists():
        setup_master_password(settings)
    password = prompt_secret("请输入密钥主密码")
    secrets = load_secrets(password, path)
    while True:
        print("\n==== 密钥管理 ====")
        print("1. 列出密钥名")
        print("2. 新增/更新密钥")
        print("3. 删除密钥")
        print("4. 显示密钥明文")
        print("5. 导入 config/secrets.yaml")
        print("0. 返回")
        choice = prompt_text("请选择").strip()
        if choice == "1":
            for name in sorted(secrets):
                print(name)
        elif choice == "2":
            name = ask_required("密钥名")
            secrets[name] = prompt_secret("密钥值")
            save_secrets(secrets, password, path)
        elif choice == "3":
            name = ask_required("密钥名")
            secrets.pop(name, None)
            save_secrets(secrets, password, path)
        elif choice == "4":
            name = ask_required("密钥名")
            if strong_confirm("secrets", "local", "show"):
                print(secrets.get(name, "不存在"))
        elif choice == "5":
            imported = import_temp_secrets()
            secrets.update(imported)
            save_secrets(secrets, password, path)
            print("已导入加密文件。请手动删除 config/secrets.yaml。")
        elif choice == "0":
            return
        else:
            print("无效选择。")


def import_temp_secrets() -> dict[str, str]:
    if not TEMP_SECRETS_FILE.exists():
        print(f"未找到 {TEMP_SECRETS_FILE}")
        return {}
    data = load_yaml(TEMP_SECRETS_FILE, {})
    secrets = data.get("secrets", data)
    if not isinstance(secrets, dict):
        raise ConfigError("config/secrets.yaml 格式非法。")
    return {str(k): str(v) for k, v in secrets.items()}


def git_flow(settings: dict[str, Any], projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    service = select_service(project)
    if not service:
        return
    selected = select_environment(service, settings.get("app", {}).get("default_environment", "test"))
    if not selected:
        return
    env_name, env_cfg = selected
    repo = derive_repo_from_commands(env_cfg)
    if not repo:
        print("当前环境无法自动识别 Git 工作目录，请在已保存命令中包含 `cd /path/to/repo`。")
        return
    actions = ["status", "fetch", "pull", "checkout", "commit", "push", "merge"]
    for idx, action in enumerate(actions, 1):
        print(f"{idx}. {action}")
    choice = prompt_text("请选择 Git 操作").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
        print("无效操作。")
        return
    action = actions[int(choice) - 1]
    run_git_action(project, service, env_name, repo, action, settings)


def run_git_action(
    project: dict[str, Any],
    service: dict[str, Any],
    env_name: str,
    repo: str,
    action: str,
    settings: dict[str, Any],
) -> None:
    if not Path(repo).exists():
        print(f"工作目录不存在: {repo}")
        return
    if action in {"commit", "push"} and settings.get("security", {}).get("block_commit_if_secret_file_staged", True):
        if has_staged_secret_file(repo):
            print("暂存区包含敏感文件，已阻止 commit/push。")
            return
    if action in {"pull", "checkout", "merge"} and is_worktree_dirty(repo):
        print("工作树存在未提交改动，已阻止该操作。")
        return
    args = ["git"]
    if action == "status":
        args += ["status", "--short", "--branch"]
    elif action == "fetch":
        args += ["fetch", "--all", "--prune"]
    elif action == "pull":
        args += ["pull", "--ff-only"]
    elif action == "checkout":
        target = ask_required("目标分支")
        args += ["checkout", target]
    elif action == "commit":
        msg = ask_required("commit message")
        args += ["commit", "-m", msg]
    elif action == "push":
        if settings.get("safety", {}).get("require_confirm_for_git_push", True):
            if not strong_confirm(f"{project['id']}/{service['id']}", env_name, "push"):
                return
        args += ["push"]
    elif action == "merge":
        target = ask_required("要合并的分支")
        if not strong_confirm(f"{project['id']}/{service['id']}", env_name, "merge"):
            return
        args += ["merge", "--no-ff", target]
    proc = subprocess.run(args, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(proc.stdout)


def has_staged_secret_file(repo: str) -> bool:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    staged = proc.stdout.splitlines()
    return any(path.startswith("config/secrets") or SENSITIVE_NAME_RE.search(Path(path).name) for path in staged)


def is_worktree_dirty(repo: str) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return bool(proc.stdout.strip())


def status_flow(settings: dict[str, Any], projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    service = select_service(project)
    if not service:
        return
    selected = select_environment(service, settings.get("app", {}).get("default_environment", "test"))
    if not selected:
        return
    env_name, env_cfg = selected
    print(f"项目: {project.get('name')} 服务: {service.get('name')} 环境: {env_name}")
    status_commands = env_cfg.get("status_commands") or []
    if not status_commands:
        print("当前环境还没有状态检查命令。")
        status_commands = ask_command_lines(f"{env_name} 环境状态检查命令")
        if not status_commands:
            print("未录入状态检查命令。")
            return
        env_cfg["status_commands"] = status_commands
        save_projects(projects)
        print(f"已保存状态检查命令到: {PROJECTS_LOCAL_FILE}")
    execute_status_commands(project, service, env_name, env_cfg, status_commands, settings)


def execute_status_commands(
    project: dict[str, Any],
    service: dict[str, Any],
    env_name: str,
    env_cfg: dict[str, Any],
    commands: list[str],
    settings: dict[str, Any],
) -> None:
    runner = CommandRunner(settings, {})
    results = []
    for command in commands:
        result = runner.run(command, project, service, env_name, env_cfg, "状态检查")
        results.append(result)
        print(f"退出码: {result.exit_code}")
        if result.exit_code != 0 and settings.get("safety", {}).get("stop_on_command_failure", True):
            print("命令失败，已停止后续状态检查。")
            break
    write_audit_log(project, service, env_name, env_cfg, "状态检查", results, runner.log_path)
    print(f"日志: {runner.log_path}")


def derive_repo_from_commands(env_cfg: dict[str, Any]) -> str:
    commands = env_cfg.get("commands") or {}
    for action in ACTION_ORDER:
        for command in commands.get(action) or []:
            repo = extract_repo_from_command(command)
            if repo:
                return repo
    return ""


def extract_repo_from_command(command: str) -> str:
    match = re.match(r"^\s*cd\s+(.+?)\s*$", command)
    if not match:
        return ""
    path = match.group(1).strip()
    if (path.startswith("'") and path.endswith("'")) or (path.startswith('"') and path.endswith('"')):
        path = path[1:-1]
    return path


def delete_project_flow(projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    if not strong_confirm(project["id"], "local", "delete-project"):
        return
    items = projects.get("projects") or []
    projects["projects"] = [item for item in items if item.get("id") != project.get("id")]
    save_projects(projects)
    print(f"已删除项目: {project.get('name')} ({project.get('id')})")


def delete_service_flow(projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    service = select_service(project)
    if not service:
        return
    if not strong_confirm(f"{project['id']}/{service['id']}", "local", "delete-service"):
        return
    services = project.get("services")
    if isinstance(services, list):
        project["services"] = [item for item in services if item.get("id") != service.get("id")]
        save_projects(projects)
        print(f"已删除子任务: {service.get('name')} ({service.get('id')})")
        return
    raise ConfigError("旧版单服务配置不能直接删除子任务，请删除整个项目后重新录入。")


def delete_action_commands_flow(projects: dict[str, Any]) -> None:
    project = select_project(projects)
    if not project:
        return
    service = select_service(project)
    if not service:
        return
    selected = select_environment(service)
    if not selected:
        return
    env_name, env_cfg = selected
    commands = env_cfg.get("commands") or {}
    action = select_action(commands)
    if not action:
        return
    if not strong_confirm(f"{project['id']}/{service['id']}", env_name, f"delete-{action_label(action)}"):
        return
    commands.pop(action, None)
    save_projects(projects)
    print(f"已删除 {service.get('name')} {env_name} 环境下的 {action} 命令。")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigError, SecretError, KeyboardInterrupt) as exc:
        print(f"\n错误: {exc}")
        raise SystemExit(1)

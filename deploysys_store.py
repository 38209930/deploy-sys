"""本地项目配置的可靠读写仓储。"""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml


SCHEMA_VERSION = 2
LOCK_TIMEOUT_SECONDS = 8
LOCK_STALE_SECONDS = 120
BACKUP_LIMIT = 20
_PROCESS_LOCKS: dict[Path, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class ConfigError(Exception):
    """项目配置无法读取或校验。"""


class ConfigConflict(ConfigError):
    """配置已经被另一个窗口更新。"""


@dataclass(frozen=True)
class ConfigSnapshot:
    data: dict[str, Any]
    revision: int
    recovered_from_backup: bool = False


def _process_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(resolved, threading.RLock())


class ConfigStore:
    def __init__(self, local_path: Path, template_path: Path, backup_dir: Path) -> None:
        self.local_path = local_path
        self.template_path = template_path
        self.backup_dir = backup_dir
        self.lock_path = local_path.with_suffix(local_path.suffix + ".lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        """跨线程、跨进程的轻量锁；锁文件异常退出后会自动过期。"""
        with _process_lock(self.local_path):
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            fd: int | None = None
            while fd is None:
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, f"pid={os.getpid()}\ncreated_at={datetime.now().isoformat()}\n".encode("utf-8"))
                except FileExistsError:
                    try:
                        age = time.time() - self.lock_path.stat().st_mtime
                        if age > LOCK_STALE_SECONDS:
                            self.lock_path.unlink(missing_ok=True)
                            continue
                    except FileNotFoundError:
                        continue
                    if time.monotonic() - started >= LOCK_TIMEOUT_SECONDS:
                        raise ConfigError("项目配置正被另一个客户端保存，请稍后刷新后重试。")
                    time.sleep(0.05)
            try:
                yield
            finally:
                if fd is not None:
                    os.close(fd)
                self.lock_path.unlink(missing_ok=True)

    def load(self) -> ConfigSnapshot:
        with self.locked():
            return self._load_locked(migrate=True)

    def mutate(
        self,
        expected_revision: int | None,
        mutator: Callable[[dict[str, Any]], None],
    ) -> ConfigSnapshot:
        with self.locked():
            snapshot = self._load_locked(migrate=True)
            if expected_revision is not None and expected_revision != snapshot.revision:
                raise ConfigConflict("配置已在另一个窗口更新，请刷新后再保存。")
            updated = copy.deepcopy(snapshot.data)
            mutator(updated)
            updated, _ = canonicalize_projects(updated)
            validate_projects(updated)
            updated["schema_version"] = SCHEMA_VERSION
            updated["revision"] = snapshot.revision + 1
            self._backup_current_locked()
            self._atomic_write_locked(self.local_path, updated)
            return ConfigSnapshot(updated, int(updated["revision"]))

    def replace(self, data: dict[str, Any]) -> ConfigSnapshot:
        """CLI 兼容入口。它始终基于当前文件原子写入，但不做旧窗口覆盖保护。"""
        with self.locked():
            current = self._load_locked(migrate=True)
            updated, _ = canonicalize_projects(copy.deepcopy(data))
            validate_projects(updated)
            updated["schema_version"] = SCHEMA_VERSION
            updated["revision"] = current.revision + 1
            self._backup_current_locked()
            self._atomic_write_locked(self.local_path, updated)
            return ConfigSnapshot(updated, int(updated["revision"]))

    def _load_locked(self, migrate: bool) -> ConfigSnapshot:
        source = self.local_path if self.local_path.exists() else self.template_path
        if not source.exists():
            data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "revision": 0, "projects": []}
            return ConfigSnapshot(data, 0)
        try:
            raw = self._read_yaml(source)
        except ConfigError:
            if source != self.local_path:
                raise
            recovered = self._recover_from_backup_locked()
            if recovered is None:
                raise
            return recovered
        data, migrated = canonicalize_projects(raw)
        validate_projects(data)
        revision = int(data.get("revision") or 0)
        data["schema_version"] = SCHEMA_VERSION
        data["revision"] = revision
        needs_local_copy = source != self.local_path and bool(data.get("projects"))
        if migrate and (migrated or needs_local_copy):
            self._backup_current_locked()
            if migrated and source == self.local_path:
                data["revision"] = revision + 1
                revision += 1
            if source == self.local_path or needs_local_copy:
                self._atomic_write_locked(self.local_path, data)
        return ConfigSnapshot(data, revision)

    def _recover_from_backup_locked(self) -> ConfigSnapshot | None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        broken = self.backup_dir / f"projects.local.{stamp}.broken.yaml"
        shutil.copy2(self.local_path, broken)
        for candidate in sorted(self.backup_dir.glob("projects.local.*.yaml"), reverse=True):
            if candidate.name.endswith(".broken.yaml"):
                continue
            try:
                data = self._read_yaml(candidate)
                data, _ = canonicalize_projects(data)
                validate_projects(data)
            except ConfigError:
                continue
            data["schema_version"] = SCHEMA_VERSION
            data["revision"] = int(data.get("revision") or 0) + 1
            self._atomic_write_locked(self.local_path, data)
            return ConfigSnapshot(data, int(data["revision"]), recovered_from_backup=True)
        return None

    def _backup_current_locked(self) -> None:
        if not self.local_path.exists():
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"projects.local.{stamp}.yaml"
        shutil.copy2(self.local_path, destination)
        backups = sorted(self.backup_dir.glob("projects.local.*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in backups[BACKUP_LIMIT:]:
            stale.unlink(missing_ok=True)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"无法读取项目配置: {path}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path} 必须是 YAML 对象。")
        return data

    @staticmethod
    def _atomic_write_locked(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)


def _as_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).rstrip() for item in value if str(item).strip()]


def canonicalize_projects(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    data = copy.deepcopy(raw)
    changed = False
    projects = data.get("projects")
    if projects is None:
        projects = []
        data["projects"] = projects
        changed = True
    if not isinstance(projects, list):
        raise ConfigError("projects 必须是数组。")
    for project in projects:
        if not isinstance(project, dict):
            raise ConfigError("projects 中的项目必须是对象。")
        services = project.get("services")
        legacy_environments = project.pop("environments", None)
        if legacy_environments is not None:
            if not isinstance(services, list):
                services = []
            services.insert(
                0,
                {
                    "id": str(project.get("id") or "default"),
                    "name": str(project.get("name") or project.get("id") or "default"),
                    "type": str(project.get("type") or "other"),
                    "targets": legacy_environments,
                },
            )
            project["services"] = services
            project.pop("repo", None)
            changed = True
        elif not isinstance(services, list):
            project["services"] = []
            services = project["services"]
            changed = True
        for service in services:
            if not isinstance(service, dict):
                raise ConfigError("服务配置必须是对象。")
            targets = service.get("targets")
            environments = service.pop("environments", None)
            if not isinstance(targets, dict):
                targets = environments if isinstance(environments, dict) else {}
                service["targets"] = targets
                changed = True
            elif environments is not None:
                changed = True
            for target_name, target in list(targets.items()):
                if not isinstance(target, dict):
                    targets[target_name] = {"commands": {"run": _as_lines(target)}}
                    target = targets[target_name]
                    changed = True
                commands = target.get("commands")
                if not isinstance(commands, dict):
                    target["commands"] = {"run": _as_lines(commands)}
                    commands = target["commands"]
                    changed = True
                for action, lines in list(commands.items()):
                    normalized = _as_lines(lines)
                    if normalized != lines:
                        commands[action] = normalized
                        changed = True
                status_lines = target.get("status_commands")
                if status_lines is not None:
                    normalized_status = _as_lines(status_lines)
                    if normalized_status != status_lines:
                        target["status_commands"] = normalized_status
                        changed = True
                if target.get("shell") not in {None, "auto", "zsh", "bash", "powershell", "cmd"}:
                    target["shell"] = "auto"
                    changed = True
    if data.get("schema_version") != SCHEMA_VERSION:
        changed = True
    return data, changed


def validate_projects(data: dict[str, Any]) -> None:
    project_ids: set[str] = set()
    for project in data.get("projects") or []:
        project_id = str(project.get("id") or "").strip()
        if not project_id:
            raise ConfigError("项目 ID 不能为空。")
        if project_id in project_ids:
            raise ConfigError(f"项目 ID 重复: {project_id}")
        project_ids.add(project_id)
        service_ids: set[str] = set()
        for service in project.get("services") or []:
            service_id = str(service.get("id") or "").strip()
            if not service_id:
                raise ConfigError(f"项目 {project_id} 存在空服务 ID。")
            if service_id in service_ids:
                raise ConfigError(f"项目 {project_id} 的服务 ID 重复: {service_id}")
            service_ids.add(service_id)
            target_names: set[str] = set()
            for target_name, target in (service.get("targets") or {}).items():
                name = str(target_name).strip()
                if not name or name in target_names:
                    raise ConfigError(f"服务 {service_id} 的执行目标名称无效或重复。")
                target_names.add(name)
                if not isinstance(target, dict):
                    raise ConfigError(f"服务 {service_id} 的执行目标必须是对象。")

#!/usr/bin/env python3
"""deploy-sys 桌面客户端。"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

import deploysys


class CommandEditor(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str, initial: list[str] | None = None) -> None:
        super().__init__(parent)
        self.title(title)
        self.result: list[str] | None = None
        self.geometry("720x420")
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="每行一条命令，执行时按顺序运行。").pack(anchor="w", padx=12, pady=(12, 4))
        self.text = ScrolledText(self, wrap="word", height=16)
        self.text.pack(fill="both", expand=True, padx=12, pady=8)
        if initial:
            self.text.insert("1.0", "\n".join(initial))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="保存", command=self.save).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        self.text.focus_set()

    def save(self) -> None:
        lines = [line.rstrip() for line in self.text.get("1.0", "end").splitlines() if line.strip()]
        self.result = lines
        self.destroy()


class ServiceEditor(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("新增服务")
        self.result: dict[str, Any] | None = None
        self.geometry("760x560")
        self.transient(parent)
        self.grab_set()

        form = ttk.Frame(self)
        form.pack(fill="x", padx=12, pady=(12, 4))
        form.columnconfigure(1, weight=1)

        self.service_id = tk.StringVar()
        self.service_name = tk.StringVar()
        self.service_type = tk.StringVar(value="other")
        self.target_name = tk.StringVar(value=deploysys.DEFAULT_TARGET_NAME)

        ttk.Label(form, text="服务 ID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.service_id).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="服务名称").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.service_name).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="服务类型").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=self.service_type,
            values=("other", "dotnet", "java", "vue3"),
        ).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="执行目标").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.target_name).grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(self, text="执行命令，每行一条。").pack(anchor="w", padx=12, pady=(8, 4))
        self.commands = ScrolledText(self, wrap="word", height=16)
        self.commands.pack(fill="both", expand=True, padx=12, pady=4)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(buttons, text="保存", command=self.save).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        self.service_id.trace_add("write", self.fill_name_from_id)
        self.service_id_entry_focus()

    def service_id_entry_focus(self) -> None:
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                for nested in child.winfo_children():
                    if isinstance(nested, ttk.Entry):
                        nested.focus_set()
                        return

    def fill_name_from_id(self, *_args: Any) -> None:
        if not self.service_name.get().strip():
            self.service_name.set(self.service_id.get().strip())

    def save(self) -> None:
        service_id = self.service_id.get().strip()
        target_name = self.target_name.get().strip()
        if not service_id:
            messagebox.showerror("缺少服务 ID", "请输入服务 ID。", parent=self)
            return
        if not target_name:
            messagebox.showerror("缺少执行目标", "请输入执行目标。", parent=self)
            return
        commands = [line.rstrip() for line in self.commands.get("1.0", "end").splitlines() if line.strip()]
        self.result = {
            "id": service_id,
            "name": self.service_name.get().strip() or service_id,
            "type": self.service_type.get().strip() or "other",
            "target_name": target_name,
            "commands": commands,
        }
        self.destroy()


class DeploySysGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("deploy-sys")
        self.geometry("1180x760")
        self.minsize(980, 620)

        deploysys.ensure_base_files()
        self.settings = deploysys.load_yaml(deploysys.SETTINGS_FILE, deploysys.DEFAULT_SETTINGS)
        self.projects = deploysys.load_projects()
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        self.status_var = tk.StringVar(value="")

        self.project_items: list[dict[str, Any]] = []
        self.service_items: list[dict[str, Any]] = []
        self.target_items: list[tuple[str, dict[str, Any]]] = []
        self.action_items: list[str] = []

        self.create_widgets()
        self.refresh_projects()
        self.after(100, self.drain_output)

    def create_widgets(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=10, pady=8)
        ttk.Button(toolbar, text="重新加载配置", command=self.reload_config).pack(side="left")
        ttk.Button(toolbar, text="新增项目", command=self.add_project).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="新增服务", command=self.add_service).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="新增执行目标", command=self.add_target).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="删除所选", command=self.delete_selected).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="打开配置文件", command=self.open_config_file).pack(side="right")

        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=10, pady=(0, 6))

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(main)
        middle = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(middle, weight=1)
        main.add(right, weight=3)

        self.project_list = self.make_list_panel(left, "项目", self.on_project_selected)
        self.service_list = self.make_list_panel(middle, "服务", self.on_service_selected)

        top_right = ttk.Frame(right)
        top_right.pack(fill="x")
        ttk.Label(top_right, text="执行目标").grid(row=0, column=0, sticky="w")
        ttk.Label(top_right, text="动作").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.target_box = ttk.Combobox(top_right, state="readonly", width=22)
        self.target_box.grid(row=1, column=0, sticky="ew")
        self.target_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_actions())
        self.action_box = ttk.Combobox(top_right, state="readonly", width=18)
        self.action_box.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        self.action_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_command_preview())
        top_right.columnconfigure(0, weight=1)
        top_right.columnconfigure(1, weight=1)

        ttk.Label(right, text="命令预览").pack(anchor="w", pady=(12, 4))
        self.command_preview = ScrolledText(right, height=8, wrap="word")
        self.command_preview.pack(fill="x")

        button_row = ttk.Frame(right)
        button_row.pack(fill="x", pady=8)
        self.execute_button = ttk.Button(button_row, text="执行", command=self.execute_selected)
        self.execute_button.pack(side="left")
        ttk.Button(button_row, text="保存命令", command=self.save_selected_commands).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="状态检查", command=self.execute_status).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="清空日志", command=self.clear_log).pack(side="right")

        ttk.Label(right, text="执行日志").pack(anchor="w")
        self.log_text = ScrolledText(right, wrap="word")
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))

    def make_list_panel(self, parent: tk.Misc, title: str, callback: Any) -> tk.Listbox:
        ttk.Label(parent, text=title).pack(anchor="w")
        listbox = tk.Listbox(parent, exportselection=False)
        listbox.pack(fill="both", expand=True, pady=(4, 0))
        listbox.bind("<<ListboxSelect>>", callback)
        return listbox

    def selected_ids(self) -> tuple[str | None, str | None]:
        project = self.selected_project()
        service = self.selected_service()
        return (
            str(project.get("id")) if project else None,
            str(service.get("id")) if service else None,
        )

    def reload_config(
        self,
        silent: bool = False,
        project_id: str | None = None,
        service_id: str | None = None,
    ) -> None:
        if project_id is None and service_id is None:
            project_id, service_id = self.selected_ids()
        self.settings = deploysys.load_yaml(deploysys.SETTINGS_FILE, deploysys.DEFAULT_SETTINGS)
        self.projects = deploysys.load_projects()
        self.refresh_projects(project_id, service_id)
        message = f"已重新加载配置: {deploysys.active_projects_file()}"
        self.status_var.set(message)
        if not silent:
            self.append_log(message + "\n")

    def refresh_projects(self, project_id: str | None = None, service_id: str | None = None) -> None:
        self.project_items = self.projects.get("projects") or []
        self.project_list.delete(0, tk.END)
        for project in self.project_items:
            self.project_list.insert(tk.END, f"{project.get('name')} ({project.get('id')})")
        self.service_list.delete(0, tk.END)
        self.clear_target_state()
        if not self.project_items:
            self.status_var.set(f"未加载到项目配置: {deploysys.active_projects_file()}")
            return
        selected_index = 0
        if project_id:
            for idx, project in enumerate(self.project_items):
                if project.get("id") == project_id:
                    selected_index = idx
                    break
        self.project_list.selection_set(selected_index)
        self.project_list.see(selected_index)
        self.on_project_selected(service_id=service_id)
        self.status_var.set(f"已加载 {len(self.project_items)} 个项目: {deploysys.active_projects_file()}")

    def on_project_selected(self, _event: Any = None, service_id: str | None = None) -> None:
        project = self.selected_project()
        self.service_items = deploysys.project_services(project) if project else []
        self.service_list.delete(0, tk.END)
        for service in self.service_items:
            self.service_list.insert(tk.END, f"{service.get('name')} ({service.get('id')})")
        self.clear_target_state()
        if not self.service_items:
            return
        selected_index = 0
        if service_id:
            for idx, service in enumerate(self.service_items):
                if service.get("id") == service_id:
                    selected_index = idx
                    break
        self.service_list.selection_set(selected_index)
        self.service_list.see(selected_index)
        self.on_service_selected()

    def on_service_selected(self, _event: Any = None) -> None:
        service = self.selected_service()
        targets = deploysys.service_targets(service) if service else {}
        self.target_items = [(name, targets[name]) for name in deploysys.ordered_target_names(service or {})]
        self.target_box["values"] = [name for name, _cfg in self.target_items]
        if self.target_items:
            self.target_box.current(0)
        self.refresh_actions()

    def refresh_actions(self) -> None:
        target = self.selected_target()
        commands = (target[1].get("commands") if target else {}) or {}
        self.action_items = deploysys.available_actions(commands)
        self.action_box["values"] = [deploysys.action_label(action) for action in self.action_items]
        if self.action_items:
            self.action_box.current(0)
        self.refresh_command_preview()

    def refresh_command_preview(self) -> None:
        commands = self.selected_commands()
        self.command_preview.delete("1.0", "end")
        self.command_preview.insert("1.0", "\n".join(commands))

    def clear_target_state(self) -> None:
        self.target_items = []
        self.action_items = []
        self.target_box["values"] = []
        self.action_box["values"] = []
        self.target_box.set("")
        self.action_box.set("")
        self.refresh_command_preview()

    def selected_project(self) -> dict[str, Any] | None:
        selection = self.project_list.curselection()
        return self.project_items[selection[0]] if selection else None

    def selected_service(self) -> dict[str, Any] | None:
        selection = self.service_list.curselection()
        return self.service_items[selection[0]] if selection else None

    def selected_target(self) -> tuple[str, dict[str, Any]] | None:
        idx = self.target_box.current()
        return self.target_items[idx] if 0 <= idx < len(self.target_items) else None

    def selected_action(self) -> str | None:
        idx = self.action_box.current()
        return self.action_items[idx] if 0 <= idx < len(self.action_items) else None

    def selected_commands(self) -> list[str]:
        target = self.selected_target()
        action = self.selected_action()
        if not target or not action:
            return []
        return ((target[1].get("commands") or {}).get(action) or [])

    def preview_command_lines(self) -> list[str]:
        return [line.rstrip() for line in self.command_preview.get("1.0", "end").splitlines() if line.strip()]

    def save_selected_commands(self) -> None:
        project = self.selected_project()
        service = self.selected_service()
        target = self.selected_target()
        action = self.selected_action() or deploysys.COMMAND_KEY
        if not project or not service or not target:
            messagebox.showinfo("不能保存", "请选择项目、服务和执行目标。")
            return
        commands = self.preview_command_lines()
        target[1].setdefault("commands", {})[action] = commands
        project_id = str(project.get("id"))
        service_id = str(service.get("id"))
        target_name = target[0]
        deploysys.save_projects(self.projects)
        self.reload_config(silent=True, project_id=project_id, service_id=service_id)
        self.select_target_by_name(target_name)
        self.select_action_by_key(action)
        messagebox.showinfo("已保存", "命令已保存。")
        self.append_log(f"已保存命令: {project_id}/{service_id} {target_name} {deploysys.action_label(action)}\n")

    def add_project(self) -> None:
        project_id = self.ask_required("新增项目", "项目 ID")
        if not project_id:
            return
        if deploysys.find_project(self.projects, project_id):
            messagebox.showinfo("项目已存在", "该项目已存在，请选择项目后使用“新增服务”。")
            return
        name = self.ask_required("新增项目", "项目名称")
        if not name:
            return
        project_type = simpledialog.askstring("新增项目", "项目类型", initialvalue="other", parent=self) or "other"
        platform_value = deploysys.detect_platform() or deploysys.PLATFORM_MAC
        project = {
            "id": project_id,
            "name": name,
            "type": project_type.strip() or "other",
            "platform": platform_value,
            "services": [],
        }
        self.projects.setdefault("projects", []).append(project)
        deploysys.save_projects(self.projects)
        self.reload_config(silent=True, project_id=project_id)
        if messagebox.askyesno("新增服务", "是否现在为该项目新增服务？"):
            self.add_service()

    def add_service(self) -> None:
        project = self.selected_project()
        if not project:
            messagebox.showinfo("请选择项目", "请先选择一个项目。")
            return
        project_id = str(project.get("id"))
        dialog = ServiceEditor(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        service_id = dialog.result["id"]
        if deploysys.find_service(project, service_id):
            messagebox.showerror("服务已存在", "该项目下已存在同 ID 服务。")
            return
        target_name = dialog.result["target_name"]
        commands = dialog.result["commands"]
        service = {
            "id": service_id,
            "name": dialog.result["name"],
            "type": dialog.result["type"],
            "targets": {
                target_name: {
                    "commands": {deploysys.COMMAND_KEY: commands} if commands else {},
                }
            },
        }
        project.setdefault("services", []).append(service)
        deploysys.save_projects(self.projects)
        self.reload_config(silent=True, project_id=project_id, service_id=service_id)
        self.select_target_by_name(target_name)
        messagebox.showinfo("已保存", f"服务已保存到项目 {project.get('name')}：{service['name']}")
        self.append_log(f"已保存服务: {project_id}/{service_id}\n")

    def add_target(self) -> None:
        project = self.selected_project()
        service = self.selected_service()
        if not project or not service:
            messagebox.showinfo("请选择服务", "请先选择一个服务。")
            return
        project_id = str(project.get("id"))
        service_id = str(service.get("id"))
        if self.add_target_to_service(service, save=True):
            self.reload_config(silent=True, project_id=project_id, service_id=service_id)
            messagebox.showinfo("已保存", "执行目标已保存。")

    def add_target_to_service(self, service: dict[str, Any], save: bool) -> bool:
        name = self.ask_required("新增执行目标", "执行目标名称，例如 默认 / test / prod / local")
        if not name:
            return False
        targets = service.setdefault("targets", {})
        if name in targets:
            messagebox.showerror("执行目标已存在", "该服务下已存在同名执行目标。")
            return False
        commands = self.ask_commands(f"{service.get('name')} - {name} 执行命令")
        targets[name] = {"commands": {deploysys.COMMAND_KEY: commands} if commands else {}}
        if save:
            deploysys.save_projects(self.projects)
        return True

    def ask_required(self, title: str, prompt: str) -> str | None:
        value = simpledialog.askstring(title, prompt, parent=self)
        value = value.strip() if value else ""
        return value or None

    def ask_commands(self, title: str, initial: list[str] | None = None) -> list[str]:
        dialog = CommandEditor(self, title, initial)
        self.wait_window(dialog)
        return dialog.result or []

    def delete_selected(self) -> None:
        project = self.selected_project()
        service = self.selected_service()
        target = self.selected_target()
        if target and service:
            if messagebox.askyesno("删除执行目标", f"删除执行目标 {target[0]}？"):
                deploysys.service_targets(service).pop(target[0], None)
                if "targets" in service:
                    service["targets"].pop(target[0], None)
                deploysys.save_projects(self.projects)
                project = self.selected_project()
                project_id = str(project.get("id")) if project else None
                service_id = str(service.get("id"))
                self.reload_config(silent=True, project_id=project_id, service_id=service_id)
            return
        if service and project:
            if messagebox.askyesno("删除服务", f"删除服务 {service.get('name')}？"):
                project_id = str(project.get("id"))
                project["services"] = [item for item in project.get("services", []) if item.get("id") != service.get("id")]
                deploysys.save_projects(self.projects)
                self.reload_config(silent=True, project_id=project_id)
            return
        if project and messagebox.askyesno("删除项目", f"删除项目 {project.get('name')}？"):
            self.projects["projects"] = [item for item in self.projects.get("projects", []) if item.get("id") != project.get("id")]
            deploysys.save_projects(self.projects)
            self.reload_config(silent=True)

    def execute_selected(self) -> None:
        project = self.selected_project()
        service = self.selected_service()
        target = self.selected_target()
        action = self.selected_action()
        commands = self.selected_commands()
        if not project or not service or not target or not action or not commands:
            messagebox.showinfo("不能执行", "请选择项目、服务、执行目标，并确认已配置命令。")
            return
        if any(deploysys.command_has_inline_secret(cmd) for cmd in commands):
            if not messagebox.askyesno("疑似敏感命令", "命令中疑似包含明文密码或 token，确认继续执行？"):
                return
        self.run_in_background(project, service, target[0], target[1], deploysys.action_label(action), commands)

    def execute_status(self) -> None:
        project = self.selected_project()
        service = self.selected_service()
        target = self.selected_target()
        if not project or not service or not target:
            messagebox.showinfo("不能执行", "请选择项目、服务和执行目标。")
            return
        commands = target[1].get("status_commands") or []
        if not commands:
            commands = self.ask_commands(f"{service.get('name')} - {target[0]} 状态检查命令")
            if not commands:
                return
            target[1]["status_commands"] = commands
            deploysys.save_projects(self.projects)
            self.reload_config(silent=True, project_id=str(project.get("id")), service_id=str(service.get("id")))
            service = self.selected_service()
            target = self.selected_target()
            if not service or not target:
                return
        self.run_in_background(project, service, target[0], target[1], "状态检查", commands)

    def run_in_background(
        self,
        project: dict[str, Any],
        service: dict[str, Any],
        target_name: str,
        target_cfg: dict[str, Any],
        action: str,
        commands: list[str],
    ) -> None:
        if self.running:
            messagebox.showinfo("正在执行", "已有命令正在执行，请等待完成。")
            return
        self.running = True
        self.execute_button.configure(state="disabled")
        self.append_log(f"\n==== {project.get('id')}/{service.get('id')} {target_name} {action} ====\n")

        def worker() -> None:
            try:
                deploysys.run_action_commands(
                    project,
                    service,
                    target_name,
                    target_cfg,
                    action,
                    commands,
                    self.settings,
                    self.output_queue.put,
                )
            except Exception as exc:  # noqa: BLE001
                self.output_queue.put(f"\n错误: {exc}\n")
            finally:
                self.output_queue.put("__DEPLOYSYS_GUI_DONE__")

        threading.Thread(target=worker, daemon=True).start()

    def drain_output(self) -> None:
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__DEPLOYSYS_GUI_DONE__":
                self.running = False
                self.execute_button.configure(state="normal")
                continue
            self.append_log(item)
        self.after(100, self.drain_output)

    def append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def open_config_file(self) -> None:
        path = deploysys.active_projects_file()
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def select_project_by_id(self, project_id: str) -> None:
        for idx, project in enumerate(self.project_items):
            if project.get("id") == project_id:
                self.project_list.selection_clear(0, tk.END)
                self.project_list.selection_set(idx)
                self.project_list.see(idx)
                self.on_project_selected()
                return

    def select_service_by_id(self, service_id: str) -> None:
        for idx, service in enumerate(self.service_items):
            if service.get("id") == service_id:
                self.service_list.selection_clear(0, tk.END)
                self.service_list.selection_set(idx)
                self.service_list.see(idx)
                self.on_service_selected()
                return

    def select_target_by_name(self, target_name: str) -> None:
        for idx, (name, _cfg) in enumerate(self.target_items):
            if name == target_name:
                self.target_box.current(idx)
                self.refresh_actions()
                return

    def select_action_by_key(self, action: str) -> None:
        for idx, item in enumerate(self.action_items):
            if item == action:
                self.action_box.current(idx)
                self.refresh_command_preview()
                return


def main() -> None:
    app = DeploySysGui()
    app.mainloop()


if __name__ == "__main__":
    main()

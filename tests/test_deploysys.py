import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import deploysys
import deploysys_gui
from deploysys_store import ConfigConflict, ConfigStore


class IsolatedWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = {
            name: getattr(deploysys, name)
            for name in ("CONFIG_DIR", "PROJECTS_FILE", "PROJECTS_LOCAL_FILE", "SETTINGS_FILE", "LOGS_DIR", "DATA_DIR", "GITIGNORE_FILE")
        }
        deploysys.CONFIG_DIR = self.root / "config"
        deploysys.PROJECTS_FILE = deploysys.CONFIG_DIR / "projects.yaml"
        deploysys.PROJECTS_LOCAL_FILE = deploysys.CONFIG_DIR / "projects.local.yaml"
        deploysys.SETTINGS_FILE = deploysys.CONFIG_DIR / "settings.yaml"
        deploysys.LOGS_DIR = self.root / "logs"
        deploysys.DATA_DIR = self.root / "data"
        deploysys.GITIGNORE_FILE = self.root / ".gitignore"
        deploysys.ensure_base_files()

    def tearDown(self):
        for name, value in self.original.items():
            setattr(deploysys, name, value)
        self.temp.cleanup()


class ConfigStoreTests(IsolatedWorkspace):
    def test_legacy_project_is_migrated_with_backup(self):
        deploysys.PROJECTS_LOCAL_FILE.write_text(
            "projects:\n  - id: legacy\n    name: Legacy\n    environments:\n      prod:\n        commands:\n          deploy: [echo legacy]\n",
            encoding="utf-8",
        )
        snapshot = deploysys.load_project_snapshot()
        project = snapshot.data["projects"][0]
        self.assertEqual(project["services"][0]["id"], "legacy")
        self.assertEqual(project["services"][0]["targets"]["prod"]["commands"]["deploy"], ["echo legacy"])
        self.assertTrue(list((deploysys.DATA_DIR / "config-backups").glob("projects.local.*.yaml")))

    def test_parallel_mutations_keep_all_services(self):
        store = deploysys.projects_store()
        store.mutate(0, lambda data: data["projects"].append({"id": "suite", "name": "Suite", "services": []}))

        def add(index):
            store.mutate(
                None,
                lambda data, i=index: data["projects"][0]["services"].append(
                    {"id": f"svc-{i}", "name": f"Service {i}", "targets": {"default": {"commands": {"run": ["echo ok"]}}}}
                ),
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(add, range(100)))
        services = store.load().data["projects"][0]["services"]
        self.assertEqual(len(services), 100)
        self.assertEqual({item["id"] for item in services}, {f"svc-{i}" for i in range(100)})

    def test_failed_atomic_write_keeps_previous_config(self):
        store = deploysys.projects_store()
        store.mutate(0, lambda data: data["projects"].append({"id": "safe", "name": "Safe", "services": []}))
        original = deploysys.PROJECTS_LOCAL_FILE.read_text(encoding="utf-8")
        with patch("deploysys_store.yaml.safe_dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.mutate(1, lambda data: data["projects"].append({"id": "lost", "name": "Lost", "services": []}))
        self.assertEqual(deploysys.PROJECTS_LOCAL_FILE.read_text(encoding="utf-8"), original)

    def test_corrupted_config_recovers_latest_backup(self):
        store = deploysys.projects_store()
        store.mutate(0, lambda data: data["projects"].append({"id": "recover", "name": "Recover", "services": []}))
        store.mutate(1, lambda data: data["projects"][0].update({"name": "Recover Updated"}))
        deploysys.PROJECTS_LOCAL_FILE.write_text("projects: [broken", encoding="utf-8")
        snapshot = store.load()
        self.assertTrue(snapshot.recovered_from_backup)
        self.assertEqual(snapshot.data["projects"][0]["name"], "Recover")


class CommandRunnerTests(IsolatedWorkspace):
    def settings(self, timeout=5):
        return {"safety": {"stop_on_command_failure": True}, "execution": {"command_idle_timeout_seconds": timeout}}

    def context_commands(self, target):
        if os.name == "nt":
            return [f'Set-Location "{target}"', "$env:DEPLOYSYS_FLAG='works'", f'if ($PWD.Path -ne "{target}") {{ throw "wrong cwd" }}', 'Write-Output "context-ok|$env:DEPLOYSYS_FLAG"']
        return [f'cd "{target}"', "export DEPLOYSYS_FLAG=works", f'test "$PWD" = "{target}"', 'printf "context-ok|%s\\n" "$DEPLOYSYS_FLAG"']

    @staticmethod
    def sleep_command(seconds):
        return f"Start-Sleep -Seconds {seconds}" if os.name == "nt" else f"{sys.executable} -c 'import time; time.sleep({seconds})'"

    @staticmethod
    def print_command(text):
        return f'Write-Output "{text}"' if os.name == "nt" else f'printf "{text}"'

    def test_multiline_block_preserves_cd_and_environment(self):
        target = self.root / "target"
        target.mkdir()
        output = []
        results, _ = deploysys.run_action_commands(
            {"id": "p"}, {"id": "s"}, "prod", {}, "执行",
            self.context_commands(target),
            self.settings(), output.append,
        )
        self.assertEqual(results[-1].exit_code, 0)
        self.assertIn("context-ok|works", results[-1].output)

    def test_command_block_stops_after_first_failure(self):
        output = []
        results, _ = deploysys.run_action_commands(
            {"id": "p"}, {"id": "s"}, "default", {}, "执行", ["throw 'failed'" if os.name == "nt" else "false", self.print_command("should-not-run")], self.settings(), output.append
        )
        self.assertNotEqual(results[-1].exit_code, 0)
        self.assertNotIn("should-not-run", results[-1].output)

    def test_runner_never_guesses_temp_directory_for_cleanup(self):
        directory = self.root / "publish.cache"
        directory.mkdir()
        runner = deploysys.CommandRunner(self.settings(), {})
        result = runner.run(self.print_command(str(directory)), {"id": "p"}, {"id": "s"}, "default", {}, "执行")
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(directory.exists())

    def test_cancel_stops_process_group(self):
        token = deploysys.CancellationToken()
        outcome = {}

        def run():
            outcome["result"] = deploysys.run_action_commands(
                {"id": "p"}, {"id": "s"}, "default", {}, "执行", [self.sleep_command(20)], self.settings(30), cancellation_token=token
            )

        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(0.35)
        token.cancel()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["result"][0][-1].exit_code, 130)

    def test_timeout_and_unique_log_files(self):
        first = deploysys.CommandRunner(self.settings(1), {})
        result = first.run(self.sleep_command(5), {"id": "p"}, {"id": "s"}, "default", {}, "执行")
        second = deploysys.CommandRunner(self.settings(), {})
        self.assertEqual(result.exit_code, deploysys.COMMAND_IDLE_TIMEOUT_EXIT_CODE)
        self.assertNotEqual(first.log_path, second.log_path)


class CliNavigationTests(IsolatedWorkspace):
    def setUp(self):
        super().setUp()
        self.settings = {"app": {"default_environment": "prod"}, "safety": {"stop_on_command_failure": True}}
        deploysys.save_projects(
            {
                "projects": [
                    {
                        "id": "apollo",
                        "name": "Apollo",
                        "services": [
                            {
                                "id": "admin-pc",
                                "name": "后台管理系统",
                                "targets": {
                                    "prod": {
                                        "commands": {
                                            "run": [self.print_command("deploy-ok")],
                                        }
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        )

    @staticmethod
    def print_command(text):
        return f'Write-Output "{text}"' if os.name == "nt" else f'printf "{text}"'

    def run_with_inputs(self, func, inputs):
        iterator = iter(inputs)

        def fake_prompt(_message, default=""):
            try:
                return next(iterator)
            except StopIteration:
                self.fail("测试输入不足，菜单没有按预期返回。")

        output = StringIO()
        with patch("deploysys.prompt_text", side_effect=fake_prompt), redirect_stdout(output):
            func()
        return output.getvalue()

    def test_execution_returns_to_current_project_menu(self):
        projects = deploysys.load_projects()
        project = deploysys.find_project(projects, "apollo")
        with patch("deploysys.execute_action") as execute:
            output = self.run_with_inputs(
                lambda: deploysys.current_project_menu(self.settings, project["id"]),
                ["1", "1", "1", "1", "0"],
            )
        execute.assert_called_once()
        self.assertGreaterEqual(output.count("==== 当前项目: Apollo (apollo) ===="), 2)

    def test_target_back_returns_to_service_list_before_project_menu(self):
        output = self.run_with_inputs(
            lambda: deploysys.current_project_menu(self.settings, "apollo"),
            ["1", "1", "0", "0", "0"],
        )
        self.assertGreaterEqual(output.count("==== 服务列表 ===="), 2)
        self.assertGreaterEqual(output.count("==== 当前项目: Apollo (apollo) ===="), 2)

    def test_invalid_service_choice_stays_in_service_menu(self):
        output = self.run_with_inputs(
            lambda: deploysys.current_project_menu(self.settings, "apollo"),
            ["1", "9", "0", "0"],
        )
        self.assertIn("无效服务。", output)
        self.assertGreaterEqual(output.count("==== 服务列表 ===="), 2)

    def test_status_command_save_returns_to_current_project_menu(self):
        with patch("deploysys.execute_status_commands") as execute_status:
            output = self.run_with_inputs(
                lambda: deploysys.current_project_menu(self.settings, "apollo"),
                ["2", "1", "1", self.print_command("status-ok"), "", "0"],
            )
        execute_status.assert_called_once()
        projects = deploysys.load_projects()
        project = deploysys.find_project(projects, "apollo")
        service = deploysys.find_service(project, "admin-pc")
        self.assertEqual(service["targets"]["prod"]["status_commands"], [self.print_command("status-ok")])
        self.assertGreaterEqual(output.count("==== 当前项目: Apollo (apollo) ===="), 2)

    def test_add_service_reloads_project_before_next_render(self):
        def append_service(project, _settings):
            project["services"].append(
                {
                    "id": "worker",
                    "name": "定时服务",
                    "targets": {"prod": {"commands": {"run": [self.print_command("worker")]}}},
                }
            )

        with patch("deploysys.append_services_to_project", side_effect=append_service):
            output = self.run_with_inputs(
                lambda: deploysys.current_project_menu(self.settings, "apollo"),
                ["3", "4", "0"],
            )
        self.assertIn("定时服务 (worker)", output)

    def test_delete_service_keeps_current_project_context(self):
        with patch("deploysys.strong_confirm", return_value=True):
            output = self.run_with_inputs(
                lambda: deploysys.current_project_menu(self.settings, "apollo"),
                ["5", "2", "1", "4", "0"],
            )
        projects = deploysys.load_projects()
        project = deploysys.find_project(projects, "apollo")
        self.assertEqual(project["services"], [])
        self.assertIn("子任务: 无", output)
        self.assertGreaterEqual(output.count("==== 当前项目: Apollo (apollo) ===="), 2)

    def test_delete_project_returns_to_project_list(self):
        projects = deploysys.load_projects()
        projects["projects"].append({"id": "mall", "name": "Mall", "services": []})
        deploysys.save_projects(projects)
        with patch("deploysys.strong_confirm", return_value=True):
            output = self.run_with_inputs(
                lambda: deploysys.project_list_loop(self.settings),
                ["1", "5", "1", "0"],
            )
        projects = deploysys.load_projects()
        self.assertIsNone(deploysys.find_project(projects, "apollo"))
        self.assertIsNotNone(deploysys.find_project(projects, "mall"))
        self.assertGreaterEqual(output.count("==== 项目列表 ===="), 2)


class ApiTests(IsolatedWorkspace):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), deploysys_gui.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def request(self, path, body=None):
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=payload,
            headers={"X-Deploy-Sys-Token": deploysys_gui.REQUEST_TOKEN, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    @staticmethod
    def print_command(text):
        return f'Write-Output "{text}"' if os.name == "nt" else f'printf "{text}"'

    def test_create_duplicate_and_revision_conflict_are_explicit(self):
        status, created = self.request("/api/projects", {"revision": 0, "id": "demo", "name": "Demo"})
        self.assertEqual(status, 200)
        revision = created["state"]["revision"]
        status, duplicate = self.request("/api/projects", {"revision": revision, "id": "demo", "name": "Duplicate"})
        self.assertEqual(status, 400)
        self.assertIn("已存在", duplicate["error"])
        status, conflict = self.request("/api/services", {"revision": 0, "project_id": "demo", "id": "api", "name": "API", "target_name": "prod", "commands": ["echo ok"]})
        self.assertEqual(status, 409)
        self.assertEqual(conflict["code"], "conflict")

    def test_service_target_commands_and_execution(self):
        _, project = self.request("/api/projects", {"revision": 0, "id": "demo", "name": "Demo"})
        _, service = self.request("/api/services", {"revision": project["state"]["revision"], "project_id": "demo", "id": "api", "name": "API", "target_name": "default", "commands": [self.print_command("api-ok")]})
        status, execution = self.request("/api/executions", {"project_id": "demo", "service_id": "api", "target_name": "default"})
        self.assertEqual(status, 200)
        execution_id = execution["execution"]["id"]
        cursor = 0
        for _ in range(20):
            time.sleep(0.05)
            status, payload = self.request(f"/api/executions/{execution_id}?cursor={cursor}")
            cursor = payload["cursor"]
            if payload["done"]:
                break
        self.assertEqual(status, 200)
        self.assertTrue(payload["done"])
        self.assertEqual(payload["status"], "success")

    def test_token_and_empty_command_are_rejected(self):
        request = Request(f"http://127.0.0.1:{self.port}/api/state")
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 400)
        _, project = self.request("/api/projects", {"revision": 0, "id": "demo", "name": "Demo"})
        status, payload = self.request("/api/services", {"revision": project["state"]["revision"], "project_id": "demo", "id": "api", "name": "API", "target_name": "default", "commands": []})
        self.assertEqual(status, 400)
        self.assertIn("至少需要", payload["error"])


class CompatibilityTests(unittest.TestCase):
    def test_encryption_round_trip_and_masking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.enc"
            deploysys.save_secrets({"TOKEN": "Abc123SecretValue"}, "master", path)
            self.assertNotIn("Abc123SecretValue", path.read_text(encoding="utf-8"))
            self.assertEqual(deploysys.load_secrets("master", path)["TOKEN"], "Abc123SecretValue")
        self.assertIn("******", deploysys.mask_text("password=something", []))

    def test_shell_selection_and_target_order(self):
        self.assertEqual(deploysys.build_shell_command("echo ok", "auto")[-1], "echo ok")
        service = {"targets": {"prod": {}, "custom": {}, "默认": {}}}
        self.assertEqual(deploysys.ordered_target_names(service), ["默认", "prod", "custom"])


if __name__ == "__main__":
    unittest.main()

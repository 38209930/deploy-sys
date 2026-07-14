import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import StringIO

import deploysys


class DeploySysTests(unittest.TestCase):
    def test_secrets_are_encrypted_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.enc"
            deploysys.save_secrets({"TOKEN": "abc123SECRETvalue"}, "master", path)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("abc123SECRETvalue", raw)
            self.assertEqual(deploysys.load_secrets("master", path)["TOKEN"], "abc123SECRETvalue")

    def test_wrong_password_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.enc"
            deploysys.save_secrets({"TOKEN": "value"}, "master", path)
            with self.assertRaises(deploysys.SecretError):
                deploysys.load_secrets("wrong", path)

    def test_mask_text_masks_known_values_and_password_fields(self):
        text = "password=my-pass TOKEN=Abcdef1234567890Abcdef1234567890 done"
        masked = deploysys.mask_text(text, ["my-pass"])
        self.assertNotIn("my-pass", masked)
        self.assertIn("password=******", masked)

    def test_inline_secret_detection(self):
        self.assertTrue(deploysys.command_has_inline_secret("deploy --password=abc"))
        self.assertTrue(deploysys.command_has_inline_secret("TOKEN=abc sh deploy.sh"))
        self.assertFalse(deploysys.command_has_inline_secret("sh deploy.sh"))

    def test_audit_log_masks_command_supplied_by_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_data = deploysys.DATA_DIR
            deploysys.DATA_DIR = Path(tmp)
            try:
                deploysys.write_audit_log(
                    {"id": "p1"},
                    {"id": "svc1"},
                    "test",
                    {"host": "local"},
                    "deploy",
                    [deploysys.CommandResult("echo ******", 0, "ok")],
                    Path(tmp) / "x.log",
                )
                line = (Path(tmp) / "operation_logs.jsonl").read_text(encoding="utf-8")
                data = json.loads(line)
                self.assertEqual(data["commands"], ["echo ******"])
            finally:
                deploysys.DATA_DIR = old_data

    def test_project_services_supports_legacy_single_service(self):
        project = {
            "id": "mall",
            "name": "Mall",
            "type": "dotnet",
            "environments": {"test": {"commands": {"deploy": ["sh deploy.sh"]}}},
        }
        services = deploysys.project_services(project)
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["id"], "mall")
        self.assertEqual(services[0]["environments"]["test"]["commands"]["deploy"], ["sh deploy.sh"])

    def test_project_services_prefers_explicit_services(self):
        project = {
            "id": "suite",
            "services": [
                {"id": "front-api", "name": "Front API"},
                {"id": "back-api", "name": "Back API"},
            ],
        }
        services = deploysys.project_services(project)
        self.assertEqual([item["id"] for item in services], ["front-api", "back-api"])

    def test_find_project_and_service(self):
        projects = {
            "projects": [
                {
                    "id": "mall",
                    "services": [{"id": "front-api", "name": "Front API"}],
                }
            ]
        }
        project = deploysys.find_project(projects, "mall")
        self.assertIsNotNone(project)
        self.assertEqual(deploysys.find_service(project, "front-api")["name"], "Front API")

    def test_view_project_flow_prints_config_path(self):
        projects = {"projects": [{"id": "mall", "name": "Mall", "services": []}]}
        with patch("deploysys.prompt_text", side_effect=["1"]), patch("sys.stdout", new_callable=StringIO) as output:
            deploysys.view_project_flow(projects)
        rendered = output.getvalue()
        self.assertIn(str(deploysys.active_projects_file()), rendered)
        self.assertIn("Mall (mall)", rendered)

    def test_render_project_details_contains_services_and_commands(self):
        project = {
            "id": "mall",
            "name": "Mall",
            "type": "other",
            "services": [
                {
                    "id": "front-api",
                    "name": "Front API",
                    "type": "java",
                    "environments": {
                        "prod": {
                            "commands": {
                                "run": [
                                    "cd /path/to/demo/front-api",
                                    "ENV_FILE=config/env.prod.example bash scripts/deploy-front-api.sh",
                                ]
                            },
                        }
                    },
                }
            ],
        }
        rendered = deploysys.render_project_details(project)
        self.assertIn("Mall (mall)", rendered)
        self.assertIn("Front API (front-api)", rendered)
        self.assertIn("命令:", rendered)
        self.assertIn("ENV_FILE=config/env.prod.example bash scripts/deploy-front-api.sh", rendered)
        self.assertNotIn("repo.mac", rendered)
        self.assertNotIn("mode=", rendered)
        self.assertNotIn("workdir=", rendered)
        self.assertNotIn("ports=", rendered)
        self.assertNotIn("health_urls=", rendered)
        self.assertNotIn("secrets=", rendered)

    def test_render_project_details_contains_status_commands(self):
        project = {
            "id": "mall",
            "name": "Mall",
            "services": [
                {
                    "id": "front-api",
                    "name": "Front API",
                    "environments": {
                        "test": {
                            "commands": {"run": ["echo deploy"]},
                            "status_commands": ["echo status"],
                        }
                    },
                }
            ],
        }
        rendered = deploysys.render_project_details(project)
        self.assertIn("状态检查命令:", rendered)
        self.assertIn("echo status", rendered)

    def test_ask_command_lines_collects_multiple_lines(self):
        with patch("deploysys.prompt_text", side_effect=["cd /tmp/app", "bash deploy.sh", ""]):
            commands = deploysys.ask_command_lines("test 环境命令")
        self.assertEqual(commands, ["cd /tmp/app", "bash deploy.sh"])

    def test_select_action_returns_run_without_prompt(self):
        commands = {"run": ["sh deploy.sh"]}
        action = deploysys.select_action(commands)
        self.assertEqual(action, "run")

    def test_select_action_returns_expected_legacy_action(self):
        commands = {"build": ["npm run build"], "deploy": ["sh deploy.sh"]}
        with patch("deploysys.prompt_text", side_effect=["2"]):
            action = deploysys.select_action(commands)
        self.assertEqual(action, "deploy")

    def test_delete_service_flow_removes_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_projects = deploysys.PROJECTS_FILE
            old_local_projects = deploysys.PROJECTS_LOCAL_FILE
            deploysys.PROJECTS_FILE = Path(tmp) / "projects.yaml"
            deploysys.PROJECTS_LOCAL_FILE = Path(tmp) / "projects.local.yaml"
            projects = {
                "projects": [
                    {
                        "id": "mall",
                        "name": "Mall",
                        "services": [
                            {"id": "front-api", "name": "Front API"},
                            {"id": "back-api", "name": "Back API"},
                        ],
                    }
                ]
            }
            try:
                with patch("deploysys.prompt_text", side_effect=["1", "1", "mall/front-api local delete-service"]):
                    deploysys.delete_service_flow(projects)
                saved = deploysys.load_yaml(deploysys.PROJECTS_LOCAL_FILE, {"projects": []})
                self.assertEqual([item["id"] for item in saved["projects"][0]["services"]], ["back-api"])
            finally:
                deploysys.PROJECTS_FILE = old_projects
                deploysys.PROJECTS_LOCAL_FILE = old_local_projects

    def test_delete_action_commands_flow_removes_only_selected_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_projects = deploysys.PROJECTS_FILE
            old_local_projects = deploysys.PROJECTS_LOCAL_FILE
            deploysys.PROJECTS_FILE = Path(tmp) / "projects.yaml"
            deploysys.PROJECTS_LOCAL_FILE = Path(tmp) / "projects.local.yaml"
            projects = {
                "projects": [
                    {
                        "id": "mall",
                        "name": "Mall",
                        "services": [
                            {
                                "id": "front-api",
                                "name": "Front API",
                                "environments": {
                                    "test": {
                                        "commands": {
                                            "build": ["npm run build"],
                                            "deploy": ["sh deploy.sh"],
                                        }
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
            try:
                with patch("deploysys.prompt_text", side_effect=["1", "1", "1", "2", "mall/front-api test delete-deploy"]):
                    deploysys.delete_action_commands_flow(projects)
                saved = deploysys.load_yaml(deploysys.PROJECTS_LOCAL_FILE, {"projects": []})
                commands = saved["projects"][0]["services"][0]["environments"]["test"]["commands"]
                self.assertIn("build", commands)
                self.assertNotIn("deploy", commands)
            finally:
                deploysys.PROJECTS_FILE = old_projects
                deploysys.PROJECTS_LOCAL_FILE = old_local_projects

    def test_extract_repo_from_command(self):
        self.assertEqual(
            deploysys.extract_repo_from_command("cd /path/to/demo/front-api"),
            "/path/to/demo/front-api",
        )
        self.assertEqual(deploysys.extract_repo_from_command('cd "/tmp/my repo"'), "/tmp/my repo")
        self.assertEqual(deploysys.extract_repo_from_command("bash deploy.sh"), "")

    def test_derive_repo_from_commands_prefers_first_cd(self):
        env_cfg = {"commands": {"deploy": ["cd /tmp/app", "bash deploy.sh"]}}
        self.assertEqual(deploysys.derive_repo_from_commands(env_cfg), "/tmp/app")

    def test_derive_repo_from_run_commands(self):
        env_cfg = {"commands": {"run": ["cd /tmp/app", "bash deploy.sh"]}}
        self.assertEqual(deploysys.derive_repo_from_commands(env_cfg), "/tmp/app")

    def test_ask_environment_commands_uses_single_run_key(self):
        with patch("deploysys.prompt_text", side_effect=["cd /tmp/app", "bash deploy.sh", ""]):
            commands = deploysys.ask_environment_commands("prod")
        self.assertEqual(commands, {"run": ["cd /tmp/app", "bash deploy.sh"]})

    def test_status_flow_prompts_saves_and_executes_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_projects = deploysys.PROJECTS_FILE
            old_local_projects = deploysys.PROJECTS_LOCAL_FILE
            deploysys.PROJECTS_FILE = Path(tmp) / "projects.yaml"
            deploysys.PROJECTS_LOCAL_FILE = Path(tmp) / "projects.local.yaml"
            projects = {
                "projects": [
                    {
                        "id": "mall",
                        "name": "Mall",
                        "services": [
                            {
                                "id": "front-api",
                                "name": "Front API",
                                "environments": {"test": {"commands": {"run": ["echo deploy"]}}},
                            }
                        ],
                    }
                ]
            }
            settings = {"app": {"default_environment": "test"}, "safety": {"stop_on_command_failure": True}}
            try:
                with patch("deploysys.prompt_text", side_effect=["1", "1", "1", "echo status", ""]), patch(
                    "deploysys.execute_status_commands"
                ) as execute:
                    deploysys.status_flow(settings, projects)
                saved = deploysys.load_yaml(deploysys.PROJECTS_LOCAL_FILE, {"projects": []})
                env_cfg = saved["projects"][0]["services"][0]["environments"]["test"]
                self.assertEqual(env_cfg["status_commands"], ["echo status"])
                execute.assert_called_once()
            finally:
                deploysys.PROJECTS_FILE = old_projects
                deploysys.PROJECTS_LOCAL_FILE = old_local_projects

    def test_collect_service_identity_allows_reentry(self):
        project = {"id": "mall", "services": []}
        with patch(
            "deploysys.prompt_text",
            side_effect=[
                "front-api",
                "错误名称",
                "vue3",
                "n",
                "front-api",
                "正确名称",
                "vue3",
                "y",
            ],
        ):
            service_id, service_name, service_type = deploysys.collect_service_identity(project)
        self.assertEqual((service_id, service_name, service_type), ("front-api", "正确名称", "vue3"))

    def test_detect_platform_on_darwin(self):
        with patch("deploysys.platform.system", return_value="Darwin"):
            self.assertEqual(deploysys.detect_platform(), deploysys.PLATFORM_MAC)

    def test_detect_platform_on_windows(self):
        with patch("deploysys.platform.system", return_value="Windows"):
            self.assertEqual(deploysys.detect_platform(), deploysys.PLATFORM_WINDOWS)

    def test_detect_platform_returns_none_for_unknown(self):
        with patch("deploysys.platform.system", return_value="Linux"):
            self.assertIsNone(deploysys.detect_platform())

    def test_normalize_platform_accepts_aliases(self):
        self.assertEqual(deploysys.normalize_platform("macOS"), deploysys.PLATFORM_MAC)
        self.assertEqual(deploysys.normalize_platform("win"), deploysys.PLATFORM_WINDOWS)
        self.assertIsNone(deploysys.normalize_platform("linux"))

    def test_ask_project_platform_uses_detected_default(self):
        with patch("deploysys.detect_platform", return_value=deploysys.PLATFORM_MAC), patch(
            "deploysys.prompt_text", return_value=""
        ):
            self.assertEqual(deploysys.ask_project_platform(), deploysys.PLATFORM_MAC)

    def test_ask_project_platform_allows_override_when_detected(self):
        with patch("deploysys.detect_platform", return_value=deploysys.PLATFORM_MAC), patch(
            "deploysys.prompt_text", return_value="windows"
        ):
            self.assertEqual(deploysys.ask_project_platform(), deploysys.PLATFORM_WINDOWS)

    def test_ask_project_platform_prompts_manual_selection_when_unknown(self):
        with patch("deploysys.detect_platform", return_value=None), patch("deploysys.prompt_text", return_value="2"):
            self.assertEqual(deploysys.ask_project_platform(), deploysys.PLATFORM_WINDOWS)

    def test_render_project_details_contains_platform(self):
        project = {
            "id": "mall",
            "name": "Mall",
            "platform": deploysys.PLATFORM_MAC,
            "services": [],
        }
        rendered = deploysys.render_project_details(project)
        self.assertIn("运行系统: macOS", rendered)


if __name__ == "__main__":
    unittest.main()

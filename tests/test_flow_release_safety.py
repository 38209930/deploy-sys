import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml


ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = load("flow_evidence", "flow-build-evidence.py")
deploy = load("acs_deploy", "acs-image-deploy.py")
menus = load("flow_menus", "sync-flow-menus.py")
generator = load("flow_generator", "generate-flow-pipelines.py")


class NewRetailConfigTests(unittest.TestCase):
    def test_independent_release_source_and_unchanged_targets(self):
        services = yaml.safe_load((ROOT / "deployment/flow/services.yaml").read_text())["services"]
        rows = [s for s in services if s["group"] == "new-retail"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["repo"], "new-store/new-store-api.git")
            self.assertEqual(row["branch"], "release")
            self.assertEqual(row["namespace"], "new-retail")
            self.assertEqual(row["deployment"], row["id"])
            self.assertEqual(row["container"], row["id"].removeprefix("new-retail-"))
            self.assertEqual(row["replicas"], 1)
            self.assertEqual(row["repo_dir"], "/Volumes/SSD/work/mall/新零售/newsale-api")

    def test_regenerated_new_retail_templates_match_checked_in_files(self):
        # 全部输出仅写临时目录，不运行真实同步脚本或改其他项目模板。
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch.object(generator, "OUTPUT", output):
                generator.main()
            for service in ("front", "back", "worker"):
                for suffix in ("", "-confirm"):
                    name = f"pipeline-new-retail-{service}{suffix}.yaml"
                    self.assertEqual((output / name).read_text(),
                                     (ROOT / "deployment/flow/services" / name).read_text())
                build = yaml.safe_load((output / f"pipeline-new-retail-{service}.yaml").read_text())
                self.assertEqual(build["sources"]["source_repo"]["triggerEvents"], [])
                confirm = yaml.safe_load((output / f"pipeline-new-retail-{service}-confirm.yaml").read_text())
                self.assertEqual(confirm["stages"]["confirm_stage"]["jobs"]["confirm_job"]["component"], "ManualValidate")


class FlowMenuTests(unittest.TestCase):
    def test_status_command_is_on_target_for_gui_and_cli(self):
        item = menus.entry("flow-api-build", "API Flow 构建", "java", "echo build", "echo status")
        target = item["targets"]["prod"]
        self.assertEqual(target["commands"]["run"][-1], "echo build")
        self.assertEqual(target["status_commands"][-1], "echo status")
        self.assertNotIn("status_commands", target["commands"])

    def test_command_blocks_keep_all_release_steps_in_one_menu_action(self):
        item = menus.entry("flow-api-prepare", "API 准备发布", "java", ["echo push", "echo build"],
                           ["echo flow", "echo acs"])
        target = item["targets"]["prod"]
        self.assertEqual(target["commands"]["run"][-2:], ["echo push", "echo build"])
        self.assertEqual(target["status_commands"][-2:], ["echo flow", "echo acs"])

    def test_flow_entry_completes_release_and_keeps_explicit_production_confirmation(self):
        row = {"id": "points-mall-front", "name": "积分商城前台 API", "kind": "dotnet",
               "repo_dir": "/workspace/jifen-api", "branch": "release",
               "acr_id": "repo-id", "namespace": "points-mall", "deployment": "points-mall-front",
               "container": "points-mall-front", "replicas": 1}
        entries = menus.flow_entries(row, {"build": 101, "confirm": 102})
        self.assertEqual([item["id"] for item in entries], ["flow-points-mall-front-release"])
        target = entries[0]["targets"]["prod"]
        command = target["commands"]["run"][-1]
        self.assertIn("FLOW_CONFIRM=yes", command)
        self.assertIn("flow-release.sh release", command)
        self.assertIn("FLOW_REPO_DIR=/workspace/jifen-api", command)
        self.assertEqual(target['release_repos'], ['/workspace/jifen-api'])
        self.assertEqual(len(target['status_commands']), 4)
        self.assertTrue(all("logs" not in item["id"] and "resources" not in item["id"] for item in entries))

    def test_all_acs_services_replace_old_actions_without_dropping_other_services(self):
        services = yaml.safe_load((ROOT / 'deployment/flow/services.yaml').read_text())['services']
        ids = yaml.safe_load((ROOT / 'deployment/flow/pipeline-ids.yaml').read_text())['pipelines']
        data = {'projects': [{'id': 'etbst', 'services': [
            {'id': 'api-flow-build', 'targets': {'prod': {}}},
            {'id': 'api-logs', 'targets': {'prod': {'commands': {'run': ['echo logs']}}}}]}]}
        first = menus.update_menu(data, services, ids)
        snapshot = yaml.safe_dump(first)
        second = menus.update_menu(first, services, ids)
        self.assertEqual(yaml.safe_dump(second), snapshot)
        generated = [s for p in second['projects'] for s in p['services'] if s['id'].startswith('flow-')]
        self.assertEqual(len(generated), len(services))
        self.assertTrue(all(s['id'].endswith('-release') for s in generated))
        self.assertEqual([s['id'] for s in second['projects'][0]['services']][-1], 'api-logs')


class PointsMallFrontConfigTests(unittest.TestCase):
    def test_points_mall_flow_uses_the_real_release_worktree_for_three_roles(self):
        services = yaml.safe_load((ROOT / "deployment/flow/services.yaml").read_text())["services"]
        rows = [row for row in services if row["group"] == "points-mall"]
        self.assertEqual([row["id"] for row in rows], ["points-mall-front", "points-mall-back", "points-mall-worker"])
        self.assertTrue(all(row["repo_dir"] == "/Volumes/SSD/work/mall/积分商城/jifen-api" for row in rows))
        front = rows[0]
        self.assertEqual(front["dockerfile"], "Visionisok.Api/Dockerfile")
        self.assertEqual(front["acr_id"], "crr-vdgtaw2phsb1n76h")
        self.assertEqual(front["namespace"], "points-mall")
        self.assertEqual(front["deployment"], "points-mall-front")
        self.assertEqual(front["container"], "points-mall-front")

    def test_generated_front_templates_have_manual_build_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch.object(generator, "OUTPUT", output):
                generator.main()
            build = yaml.safe_load((output / "pipeline-points-mall-front.yaml").read_text())
            confirm = yaml.safe_load((output / "pipeline-points-mall-front-confirm.yaml").read_text())
        self.assertEqual(build["sources"]["source_repo"]["branch"], "release")
        self.assertEqual(build["sources"]["source_repo"]["triggerEvents"], [])
        self.assertEqual(build["stages"]["build_stage"]["jobs"]["build_job"]["steps"]["acr_push"]["with"]["dockerfilePath"], "Visionisok.Api/Dockerfile")
        self.assertEqual(confirm["stages"]["confirm_stage"]["jobs"]["confirm_job"]["component"], "ManualValidate")


class BuildEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.commit = "a" * 40
        self.run = {"pipelineRun": {"sources": [{"data": {"branch": "product/new-retail",
                        "commint": json.dumps([{"commitId": self.commit}])}}],
                        "createTime": 1000, "updateTime": 2000}}
        self.tags = {"Images": [{"Tag": "20260927-" + self.commit[:8],
                                  "Digest": "b" * 64, "ImageCreate": 1500}]}

    def test_configured_source_branch_and_unique_digest(self):
        self.assertEqual(evidence.verify(self.run, self.tags, "product/new-retail")[2], "b" * 64)
        with self.assertRaises(ValueError):
            evidence.verify(self.run, self.tags, "release")
        self.tags["Images"][0]["Digest"] = "wrong"
        with self.assertRaises(ValueError):
            evidence.verify(self.run, self.tags, "product/new-retail")

    def test_duplicate_tag_is_rejected(self):
        self.tags["Images"].append(dict(self.tags["Images"][0]))
        with self.assertRaises(ValueError):
            evidence.verify(self.run, self.tags, "product/new-retail")

    def test_release_evidence_rejects_old_product_branch(self):
        self.run["pipelineRun"]["sources"][0]["data"]["branch"] = "release"
        self.assertEqual(evidence.verify(self.run, self.tags, "release")[0], self.commit)
        with self.assertRaises(ValueError):
            evidence.verify(self.run, self.tags, "product/new-retail")

    def test_commit_history_uses_checked_out_head_only(self):
        commits = [{"commitId": self.commit}, {"commitId": "c" * 40}]
        self.run["pipelineRun"]["sources"][0]["data"]["commint"] = json.dumps(commits)
        self.assertEqual(evidence.verify(self.run, self.tags, "product/new-retail")[0], self.commit)
        self.tags["Images"][0]["Tag"] = "20260927-cccccccc"
        with self.assertRaises(ValueError):
            evidence.verify(self.run, self.tags, "product/new-retail")


class ImageDeployTests(unittest.TestCase):
    def test_zero_replica_patch_only_changes_image(self):
        repo = "ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/dgye-api"
        old, new = repo + "@sha256:" + "a" * 64, repo + "@sha256:" + "b" * 64
        current = {"metadata": {"namespace": "dgye-api", "resourceVersion": "10"},
                   "spec": {"replicas": 0, "template": {"spec": {"containers": [{"name": "dgye-api", "image": old}]}}}}
        patches = []

        def fake_run(*args):
            if args[0] == "aliyun" and args[1] == "sts":
                return json.dumps({"AccountId": deploy.ACCOUNT})
            if args[0] == "aliyun" and args[1] == "cs":
                return json.dumps({"config": "temporary-test-config"})
            if "version" in args:
                return json.dumps({"clientVersion": {"minor": "36"}, "serverVersion": {"minor": "36"}})
            if "patch" in args:
                patches.extend(json.loads(args[args.index("-p") + 1]))
                current["spec"]["template"]["spec"]["containers"][0]["image"] = new
                return "patched"
            if "get" in args:
                return json.dumps(current)
            raise AssertionError(args)

        argv = ["acs-image-deploy.py", "--namespace", "dgye-api", "--deployment", "dgye-api",
                "--container", "dgye-api", "--image", new, "--expected-replicas", "0"]
        with patch.object(sys, "argv", argv), patch.object(deploy, "run", side_effect=fake_run):
            deploy.main()
        self.assertEqual([p["op"] for p in patches], ["test", "test", "test", "replace"])
        self.assertEqual(patches[-1]["path"], "/spec/template/spec/containers/0/image")
        self.assertEqual(current["spec"]["replicas"], 0)

    def test_zero_replica_cannot_expand(self):
        image = "ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/dgye-api@sha256:" + "b" * 64
        argv = ["acs-image-deploy.py", "--namespace", "dgye-api", "--deployment", "dgye-api",
                "--container", "dgye-api", "--image", image, "--expected-replicas", "1"]
        with patch.object(sys, "argv", argv), patch.object(deploy, "run") as fake:
            with self.assertRaises(RuntimeError):
                deploy.main()
            fake.assert_not_called()


if __name__ == "__main__":
    unittest.main()

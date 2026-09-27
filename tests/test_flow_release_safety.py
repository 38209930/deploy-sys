import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = load("flow_evidence", "flow-build-evidence.py")
deploy = load("acs_deploy", "acs-image-deploy.py")
menus = load("flow_menus", "sync-flow-menus.py")


class FlowMenuTests(unittest.TestCase):
    def test_status_command_is_on_target_for_gui_and_cli(self):
        item = menus.entry("flow-api-build", "API Flow 构建", "java", "echo build", "echo status")
        target = item["targets"]["prod"]
        self.assertEqual(target["commands"]["run"][-1], "echo build")
        self.assertEqual(target["status_commands"][-1], "echo status")
        self.assertNotIn("status_commands", target["commands"])


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

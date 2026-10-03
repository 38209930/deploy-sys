import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

DEPLOY = load('points_deploy', 'points-mall-deploy.py')
MENU = load('points_menu', 'configure-points-mall-branches.py')

class BranchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'jifen-api'
        self.remote = self.root / 'origin.git'
        self.run_git(self.root, 'init', '--bare', str(self.remote))
        self.run_git(self.root, 'init', '-b', 'master', str(self.repo))
        self.run_git(self.repo, 'config', 'user.email', 'test@example.invalid')
        self.run_git(self.repo, 'config', 'user.name', 'test')
        (self.repo / 'scripts/deploy').mkdir(parents=True)
        (self.repo / 'scripts/deploy/deploy.prod.env').write_text('synthetic-test-only\n')
        self.commit('base')
        self.run_git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        for branch in ('dev', 'release'):
            self.run_git(self.repo, 'branch', branch)
        self.run_git(self.repo, 'push', 'origin', 'master', 'dev', 'release')

    def run_git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, message):
        self.run_git(self.repo, 'add', '-A')
        self.run_git(self.repo, 'commit', '-m', message)
        return self.run_git(self.repo, 'rev-parse', 'HEAD')

    def advance_dev(self):
        self.run_git(self.repo, 'switch', 'dev')
        (self.repo / 'source.txt').write_text('new dev source')
        head = self.commit('dev source')
        self.run_git(self.repo, 'push', 'origin', 'dev')
        self.run_git(self.repo, 'switch', 'master')
        return head

    def test_test_switches_dev_and_executes_selected_source(self):
        expected = self.advance_dev()
        result = DEPLOY.execute(self.repo, 'test', 'deploy', [sys.executable, '-c',
            "import pathlib; assert pathlib.Path('source.txt').read_text() == 'new dev source'"])
        self.assertEqual(result, 0)
        self.assertEqual(self.run_git(self.repo, 'branch', '--show-current'), 'dev')
        self.assertEqual(self.run_git(self.repo, 'rev-parse', 'HEAD'), expected)

    def test_prod_rejects_dev_not_merged_without_running_command(self):
        self.advance_dev()
        with patch.object(DEPLOY.subprocess, 'run', wraps=subprocess.run) as run:
            with self.assertRaisesRegex(DEPLOY.DeployError, '最新 origin/dev'):
                DEPLOY.execute(self.repo, 'prod', 'deploy', ['never-run'])
        self.assertFalse(any(c.args[0] == ['never-run'] for c in run.call_args_list))

    def test_preserves_registered_local_environment_change(self):
        file = self.repo / 'scripts/deploy/deploy.prod.env'
        file.write_text('synthetic-local-override\n')
        DEPLOY.prepare(self.repo, 'test', 'deploy')
        self.assertEqual(file.read_text(), 'synthetic-local-override\n')

    def test_unrelated_dirty_file_blocks(self):
        (self.repo / 'unrelated.txt').write_text('keep')
        with self.assertRaises(DEPLOY.DeployError):
            DEPLOY.prepare(self.repo, 'test', 'deploy')
        self.assertEqual((self.repo / 'unrelated.txt').read_text(), 'keep')

    def test_existing_release_worktree_selected(self):
        path = self.root / 'release-work'
        self.run_git(self.repo, 'worktree', 'add', str(path), 'release')
        work, head = DEPLOY.prepare(self.repo, 'prod', 'build')
        self.assertEqual(work.resolve(), path.resolve())
        self.assertEqual(self.run_git(self.repo, 'branch', '--show-current'), 'master')

    def test_unpushed_dev_rejected(self):
        self.run_git(self.repo, 'switch', 'dev')
        (self.repo / 'local.txt').write_text('local')
        self.commit('unpushed')
        with self.assertRaisesRegex(DEPLOY.DeployError, '未推送'):
            DEPLOY.prepare(self.repo, 'test', 'deploy')

    def test_failure_never_closes_master(self):
        with patch.object(DEPLOY, 'finish_master') as finish:
            code = DEPLOY.execute(self.repo, 'prod', 'deploy', [sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual(code, 7)
        finish.assert_not_called()

    def test_success_closes_master_only_to_published_commit(self):
        head = self.advance_dev()
        self.run_git(self.repo, 'switch', 'release')
        self.run_git(self.repo, 'merge', '--ff-only', 'dev')
        self.run_git(self.repo, 'push', 'origin', 'release')
        self.run_git(self.repo, 'switch', 'master')
        DEPLOY.execute(self.repo, 'prod', 'deploy', [sys.executable, '-c', 'pass'])
        self.assertEqual(self.run_git(self.repo, 'rev-parse', 'origin/master'), head)
        self.assertEqual(self.run_git(self.repo, 'branch', '--show-current'), 'release')

    def test_stale_flow_artifact_rejected(self):
        file = self.root / 'state.env'
        file.write_text('service=points-mall-back\nlast_status=WAITING_CONFIRM\nsource_commit=old\n')
        with self.assertRaisesRegex(DEPLOY.DeployError, 'SHA'):
            DEPLOY.verify_state(file, 'new', 'points-mall-back')

    def test_release_changes_during_publication_prevent_closure(self):
        work, head = DEPLOY.prepare(self.repo, 'prod', 'build')
        self.advance_dev()
        with self.assertRaises(DEPLOY.DeployError):
            DEPLOY.finish_master(work, head)

class MenuTests(unittest.TestCase):
    def test_scoped_idempotent_updates_and_selected_cwd(self):
        other = {'id': 'other', 'services': [{'id': 'keep', 'targets': {}}]}
        project = {'id': 'jifen', 'services': [
            {'id': 'api-front', 'targets': {'test': {'commands': {'run': ['old']}}, 'prod': {'commands': {'run': ['old prod']}}}},
            {'id': 'miniapp', 'targets': {'test': {'commands': {'run': ['cd /some/repo\nbash scripts/upload-wechat.sh test']}}}},
            {'id': 'flow-points-mall-back-build', 'targets': {'prod': {'commands': {'run': ['cd /tool', 'FLOW_SERVICE=points-mall-back bash scripts/flow-release.sh build']}, 'status_commands': ['keep status']}}}
        ]}
        data = {'projects': [project, other]}
        before = copy.deepcopy(other)
        MENU.update_menu(data, ROOT, ROOT)
        self.assertEqual(other, before)
        target = project['services'][0]['targets']
        self.assertIn('points-mall-test-api.py', target['test']['commands']['run'][0])
        self.assertEqual(target['prod']['commands']['run'][-1], 'exit 1')
        self.assertIn('$POINTS_MALL_SOURCE_DIR', project['services'][1]['targets']['test']['commands']['run'][0])
        self.assertEqual(project['services'][2]['targets']['prod']['status_commands'], ['keep status'])
        snapshot = copy.deepcopy(data)
        MENU.update_menu(data, ROOT, ROOT)
        self.assertEqual(data, snapshot)

    def test_test_targets_use_new_ports(self):
        for role, port in [('front', 3090), ('back', 3091)]:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/points-mall-test-api.py'), role, '--check'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(str(port), result.stdout)
            self.assertNotIn('3040', result.stdout)
            self.assertNotIn('3041', result.stdout)

if __name__ == '__main__':
    unittest.main()

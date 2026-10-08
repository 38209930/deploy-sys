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
POINTS_API = load('points_api', 'points-mall-test-api.py')

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
        self.assertIn('--restart', target['test']['commands']['restart'][0])
        self.assertIn('--status', target['test']['status_commands'][0])
        self.assertEqual(target['prod']['commands']['run'][-1], 'exit 1')
        self.assertIn('$POINTS_MALL_SOURCE_DIR', project['services'][1]['targets']['test']['commands']['run'][0])
        self.assertEqual(project['services'][2]['targets']['prod']['status_commands'], ['keep status'])
        snapshot = copy.deepcopy(data)
        MENU.update_menu(data, ROOT, ROOT)
        self.assertEqual(data, snapshot)

    def test_flow_menu_removes_deleted_release_worktree_path(self):
        project = {'id': 'jifen', 'services': [
            {'id': 'flow-points-mall-back-deploy', 'targets': {'prod': {'commands': {'run': [
                'cd /tool',
                "FLOW_SERVICE=points-mall-back FLOW_REPO_DIR='/Volumes/SSD/work/mall/积分商城/jifen-api-release' python3 /tool/scripts/points-mall-deploy.py prod /repo deploy -- bash scripts/flow-release.sh deploy",
            ]}}}},
        ]}
        MENU.update_menu({'projects': [project]}, ROOT, ROOT)
        command = project['services'][0]['targets']['prod']['commands']['run'][-1]
        self.assertNotIn('jifen-api-release', command)
        self.assertIn('points-mall-deploy.py', command)

    def test_test_targets_use_new_ports(self):
        for role, port in [('front', 3090), ('back', 3091)]:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/points-mall-test-api.py'), role, '--check'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(str(port), result.stdout)
            self.assertNotIn('3040', result.stdout)
            self.assertNotIn('3041', result.stdout)

    def test_restart_restarts_target_once_then_waits_for_readiness(self):
        responses = [
            subprocess.CompletedProcess(['ssh'], 0, 'service_active=active\n', ''),
            subprocess.CompletedProcess(['ssh'], 0, 'readiness_http=200\n', ''),
        ]
        with patch.object(POINTS_API.subprocess, 'run', side_effect=responses) as run:
            result = POINTS_API.restart_service(['ssh'], {'SSHPASS': 'test-only'}, 'jifen90.api', 3090)
        self.assertEqual(result, 'readiness_http=200')
        self.assertEqual(run.call_count, 2)
        self.assertIn('systemctl restart jifen90.api', run.call_args_list[0].args[0][-1])
        self.assertIn('http://172.27.182.78:3090/health/ready', run.call_args_list[1].args[0][-1])

    def test_runtime_status_reads_remote_state_without_restart(self):
        response = subprocess.CompletedProcess(['ssh'], 0, 'service=jifen90.api active=true directory_match=true environment_test=true test_files=true live_http=200 ready_http=200\n', '')
        with patch.object(POINTS_API.subprocess, 'run', return_value=response) as run:
            result = POINTS_API.read_runtime_status(['ssh'], {'SSHPASS': 'test-only'}, '/home/publish/jifen90/api_front', 'jifen90.api', 3090)
        self.assertIn('active=true', result)
        command = run.call_args.args[0][-1]
        self.assertIn('systemctl is-active --quiet jifen90.api', command)
        self.assertIn('/health/live', command)
        self.assertIn('/health/ready', command)
        self.assertNotIn('systemctl restart', command)

if __name__ == '__main__':
    unittest.main()

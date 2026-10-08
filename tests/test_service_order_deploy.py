import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

workflow = load('service-order-deploy')
menus = load('configure-service-order-branches')


class BranchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='serviceorder-menu-test-')
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.repo = self.root / 'repo'
        self.run_git('init', '--bare', str(self.remote), cwd=self.root)
        self.run_git('clone', str(self.remote), str(self.repo), cwd=self.root)
        self.run_git('config', 'user.name', 'Test')
        self.run_git('config', 'user.email', 'test@example.invalid')
        self.run_git('switch', '-c', 'master')
        self.base = self.commit('base')
        self.run_git('push', 'origin', 'master')
        self.run_git('switch', '-c', 'dev')
        self.dev = self.commit('dev')
        self.run_git('push', '-u', 'origin', 'dev')
        self.run_git('switch', '-c', 'release')
        self.run_git('push', '-u', 'origin', 'release')
        self.run_git('switch', '-c', 'fix/menu-test')
        self.state = self.root / 'state'
        self.state.mkdir()
        self.environment = patch.dict(os.environ, {'FLOW_STATE_DIR': str(self.state)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def run_git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.repo, text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, value):
        (self.repo / 'synthetic.txt').write_text(value)
        self.run_git('add', 'synthetic.txt')
        self.run_git('commit', '-m', value)
        return self.run_git('rev-parse', 'HEAD')

    def state_file(self, status='WAITING_CONFIRM', sha=None):
        path = self.state / 'service-order-front.env'
        path.write_text('service=service-order-front\nlast_status=' + status + '\nsource_commit=' + (sha or self.dev) + '\n')
        return path

    def test_test_menu_switches_from_feature_to_dev(self):
        self.assertEqual(workflow.prepare(self.repo, 'test', 'deploy'), self.dev)
        self.assertEqual(self.run_git('branch', '--show-current'), 'dev')

    def test_test_menu_fast_forwards_stale_dev(self):
        self.run_git('branch', '-f', 'dev', self.base)
        self.assertEqual(workflow.prepare(self.repo, 'test', 'deploy'), self.dev)

    def test_missing_local_dev_tracks_remote(self):
        self.run_git('branch', '-D', 'dev')
        workflow.prepare(self.repo, 'test', 'deploy')
        self.assertEqual(self.run_git('rev-parse', '@{u}'), self.dev)

    def test_dirty_tree_stops_before_switch(self):
        (self.repo / 'untracked.txt').write_text('keep')
        with self.assertRaisesRegex(workflow.DeployError, '工作树'):
            workflow.prepare(self.repo, 'test', 'deploy')
        self.assertEqual(self.run_git('branch', '--show-current'), 'fix/menu-test')

    def test_detached_head_is_rejected(self):
        self.run_git('switch', '--detach')
        with self.assertRaisesRegex(workflow.DeployError, 'detached'):
            workflow.prepare(self.repo, 'test', 'deploy')

    def test_unpushed_dev_is_preserved_and_rejected(self):
        self.run_git('switch', 'dev')
        new = self.commit('local only')
        with self.assertRaisesRegex(workflow.DeployError, '未推送'):
            workflow.prepare(self.repo, 'test', 'deploy')
        self.assertEqual(self.run_git('rev-parse', 'HEAD'), new)

    def test_prod_switches_to_release(self):
        self.assertEqual(workflow.prepare(self.repo, 'prod', 'build'), self.dev)
        self.assertEqual(self.run_git('branch', '--show-current'), 'release')

    def test_prod_requires_release_to_include_dev(self):
        self.run_git('switch', 'dev')
        self.commit('dev not merged to release')
        self.run_git('push', 'origin', 'dev')
        self.run_git('switch', 'fix/menu-test')
        with self.assertRaisesRegex(workflow.DeployError, '尚未包含'):
            workflow.prepare(self.repo, 'prod', 'build')
        self.assertEqual(self.run_git('branch', '--show-current'), 'fix/menu-test')

    def test_only_push_action_accepts_unpushed_release(self):
        self.run_git('switch', 'release')
        new = self.commit('release commit')
        self.run_git('switch', 'fix/menu-test')
        with self.assertRaises(workflow.DeployError):
            workflow.prepare(self.repo, 'prod', 'build')
        self.assertEqual(workflow.prepare(self.repo, 'prod', 'push'), new)

    def test_prod_rejects_unpushed_local_dev(self):
        self.run_git('switch', 'dev')
        pending = self.commit('dev not pushed')
        self.run_git('switch', 'fix/menu-test')
        with self.assertRaisesRegex(workflow.DeployError, '本地dev'):
            workflow.prepare(self.repo, 'prod', 'build')
        self.assertEqual(self.run_git('rev-parse', 'dev'), pending)
        self.assertEqual(self.run_git('branch', '--show-current'), 'fix/menu-test')

    def test_master_divergence_blocks_before_deployment(self):
        self.run_git('switch', 'master')
        self.commit('master independent')
        self.run_git('push', 'origin', 'master')
        self.run_git('switch', 'fix/menu-test')
        with self.assertRaisesRegex(workflow.DeployError, '不能快进'):
            workflow.prepare(self.repo, 'prod', 'deploy')

    def test_stale_flow_image_stops_before_command(self):
        self.state_file(sha=self.base)
        marker = self.root / 'executed'
        command = [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']
        with self.assertRaisesRegex(workflow.DeployError, '源码提交'):
            workflow.execute(self.repo, 'prod', 'deploy', command, 'service-order-front')
        self.assertFalse(marker.exists())

    def test_waiting_confirmation_is_not_delivery(self):
        self.state_file()
        with self.assertRaisesRegex(workflow.DeployError, '真实发布'):
            workflow.execute(self.repo, 'prod', 'deploy', [sys.executable, '-c', 'pass'], 'service-order-front')
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.base)

    def test_deploy_failure_does_not_merge_master(self):
        self.state_file()
        self.assertEqual(workflow.execute(self.repo, 'prod', 'deploy', [sys.executable, '-c', 'raise SystemExit(7)'], 'service-order-front'), 7)
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.base)

    def test_build_success_does_not_merge_master(self):
        self.assertEqual(workflow.execute(self.repo, 'prod', 'build', [sys.executable, '-c', 'pass'], 'service-order-front'), 0)
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.base)

    def test_successful_flow_delivery_fast_forwards_master(self):
        path = self.state_file()
        for service in ['service-order-back', 'service-order-worker']:
            (self.state / (service + '.env')).write_text('service=' + service + '\nlast_status=DEPLOY_SUCCESS\nsource_commit=' + self.dev + '\n')
        command = [sys.executable, '-c', f'from pathlib import Path; p=Path({str(path)!r}); p.write_text(p.read_text().replace("WAITING_CONFIRM", "DEPLOY_SUCCESS"))']
        self.assertEqual(workflow.execute(self.repo, 'prod', 'deploy', command, 'service-order-front'), 0)
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.dev)
        self.assertEqual(self.run_git('branch', '--show-current'), 'release')

    def test_single_flow_service_success_waits_for_same_commit_peers(self):
        path = self.state_file()
        for service in ['service-order-back', 'service-order-worker']:
            (self.state / (service + '.env')).write_text('service=' + service + '\nlast_status=DEPLOY_SUCCESS\nsource_commit=' + self.base + '\n')
        command = [sys.executable, '-c', f'from pathlib import Path; p=Path({str(path)!r}); p.write_text(p.read_text().replace("WAITING_CONFIRM", "DEPLOY_SUCCESS"))']
        self.assertEqual(workflow.execute(self.repo, 'prod', 'deploy', command, 'service-order-front'), 0)
        self.assertEqual(workflow.read_state(path)['last_status'], 'DEPLOY_SUCCESS')
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.base)

    def test_successful_static_delivery_fast_forwards_master(self):
        self.assertEqual(workflow.execute(self.repo, 'prod', 'deploy', [sys.executable, '-c', 'pass']), 0)
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.dev)

    def test_dev_changed_during_delivery_does_not_close_master(self):
        workflow.prepare(self.repo, 'prod', 'deploy')
        self.run_git('switch', 'dev')
        self.commit('new dev during release')
        self.run_git('push', 'origin', 'dev')
        self.run_git('switch', 'release')
        with self.assertRaisesRegex(workflow.DeployError, '发布期间dev'):
            workflow.finish_master(self.repo, self.dev)
        self.assertEqual(self.run_git('rev-parse', 'origin/master'), self.base)


class FlowStateRetentionTests(unittest.TestCase):
    def test_source_commit_survives_approval_failure_and_retry(self):
        with tempfile.TemporaryDirectory(prefix='serviceorder-flow-state-') as tmp:
            root = Path(tmp)
            scripts = root / 'scripts'
            scripts.mkdir()
            script = scripts / 'flow-release.sh'
            script.write_bytes((ROOT / 'scripts/flow-release.sh').read_bytes())
            acs = scripts / 'acs-image-deploy.py'
            acs.write_text('raise SystemExit(7)')
            fake = root / 'aliyun'
            fake.write_text("""#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
marker = Path(__file__).with_name('approved')
if args[:2] == ['sts', 'GetCallerIdentity']:
    data = {'AccountId': '1442361567788059'}
elif args[:2] == ['cr', 'get-repo-tag']:
    data = {'Digest': 'b'*64, 'IsSuccess': True, 'Status': 'NORMAL'}
elif 'PassPipelineValidate' in args:
    marker.touch(); data = {'success': True}
elif 'GetPipelineRun' in args:
    data = {'pipelineRun': {'status': 'SUCCESS' if marker.exists() else 'RUNNING', 'stages': [{'stageInfo': {'jobs': [{'status': 'WAITING', 'id': 99, 'name': 'synthetic confirmation'}]}}]}}
else:
    raise SystemExit('unexpected synthetic CLI operation')
print(json.dumps(data))
""")
            fake.chmod(0o700)
            state_dir = root / 'state'
            state_dir.mkdir()
            state = state_dir / 'service-order-front.env'
            commit = 'a' * 40
            state.write_text('service=service-order-front\nlast_status=WAITING_CONFIRM\ndeploy_pipeline_id=22\ndeploy_run_id=33\nsource_commit=' + commit + '\nimage_ref=example/repo@sha256:' + 'b'*64 + '\nimage_tag=synthetic\n')
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], FLOW_STATE_DIR=str(state_dir), FLOW_SERVICE='service-order-front', FLOW_DEPLOY_PIPELINE_ID='22', FLOW_RUN_ID='33', FLOW_CONFIRM='yes', FLOW_IMAGE_REPO='example/repo', FLOW_ACR_INSTANCE_ID='synthetic', FLOW_ACR_REPO_ID='synthetic', FLOW_NAMESPACE='synthetic', FLOW_DEPLOYMENT='synthetic', FLOW_CONTAINER='synthetic')
            for key in ['FLOW_DEPLOY_MODE', 'FLOW_ACCOUNT_ID', 'FLOW_BUILD_TIMEOUT', 'FLOW_POLL_INTERVAL']:
                env.pop(key, None)
            result = subprocess.run(['bash', str(script), 'deploy'], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(workflow.read_state(state)['last_status'], 'APPROVED_PENDING_DEPLOY')
            self.assertEqual(workflow.read_state(state)['source_commit'], commit)
            acs.write_text('raise SystemExit(0)')
            result = subprocess.run(['bash', str(script), 'deploy'], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(workflow.read_state(state)['last_status'], 'DEPLOY_SUCCESS')
            self.assertEqual(workflow.read_state(state)['source_commit'], commit)


class MenuConfigurationTests(unittest.TestCase):
    def fixture(self):
        services = []
        for component in ['front', 'back', 'worker']:
            for action in ['push', 'build', 'deploy']:
                services.append({'id': f'flow-service-order-{component}-{action}', 'targets': {'prod': {'commands': {'run': ['cd /tool', f'FLOW_SERVICE=service-order-{component} FLOW_RELEASE_BRANCH=release bash scripts/flow-release.sh {action}']}}}})
        for sid in ['api-front', 'api-back', 'worker', 'admin-pc', 'h5-oss']:
            targets = {'test': {'commands': {'run': ['cd /workspace', 'CONFIRM_TEST_DEPLOY=YES bash scripts/deploy-test-front.sh']}}}
            if sid in ['admin-pc', 'h5-oss']:
                targets['prod'] = {'commands': {'run': ['cd /workspace', 'CONFIRM_PROD_DEPLOY=YES bash scripts/deploy-prod-pc.sh']}}
            services.append({'id': sid, 'targets': targets})
        services.append({'id': 'flow-service-order-front-logs', 'targets': {'prod': {'commands': {'run': ['read-only logs']}}}})
        return {'projects': [{'id': 'other-project', 'services': []}, {'id': 'service-order', 'services': services}]}

    def test_all_sixteen_commands_are_wrapped_and_other_entries_unchanged(self):
        data = self.fixture()
        old = copy.deepcopy(data)
        menus.update_menu(data)
        services = data['projects'][1]['services']
        commands = [t['commands']['run'][-1] for s in services[:-1] for t in s['targets'].values()]
        self.assertEqual(len(commands), 16)
        self.assertTrue(all('service-order-deploy.py' in x for x in commands))
        self.assertTrue(all(' -- bash scripts/' in x for x in commands))
        self.assertEqual(data['projects'][0], old['projects'][0])
        self.assertEqual(services[-1], old['projects'][1]['services'][-1])
        self.assertIn('FLOW_RELEASE_BRANCH=release', commands[0])
        self.assertIn('CONFIRM_TEST_DEPLOY=YES', commands[9])

    def test_menu_update_is_idempotent(self):
        data = self.fixture()
        menus.update_menu(data)
        old = copy.deepcopy(data)
        menus.update_menu(data)
        self.assertEqual(data, old)

    def test_test_api_entries_have_safe_remote_runtime_status(self):
        data = self.fixture()
        menus.update_menu(data)
        services = {service['id']: service for service in data['projects'][1]['services']}
        for service_id in ('api-front', 'api-back', 'worker'):
            command = services[service_id]['targets']['test']['status_commands']
            self.assertEqual(command, [menus.TEST_RUNTIME_STATUS])
            self.assertIn('migrate-test-runtime-config.sh', command[0])
            self.assertTrue(command[0].endswith(' status'))

    def test_single_multiline_command_block_preserves_structure(self):
        data = self.fixture()
        target = data['projects'][1]['services'][9]['targets']['test']
        target['commands']['run'] = ['cd /workspace\nCONFIRM_TEST_DEPLOY=YES bash scripts/deploy-test-front.sh']
        menus.update_menu(data)
        self.assertEqual(len(target['commands']['run']), 1)
        self.assertTrue(target['commands']['run'][0].startswith('cd /workspace\nCONFIRM_TEST_DEPLOY=YES python3 '))
        self.assertTrue(target['commands']['run'][0].endswith(' -- bash scripts/deploy-test-front.sh'))

    def test_changed_entry_is_not_silently_replaced(self):
        data = self.fixture()
        data['projects'][1]['services'][0]['targets']['prod']['commands']['run'] = ['unexpected command']
        with self.assertRaises(menus.ConfigError):
            menus.update_menu(data)


if __name__ == '__main__':
    unittest.main()

import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acs = load('restart_acs', 'acs-image-deploy.py')
ecs = load('restart_ecs', 'ecs-test-restart.py')
menus = load('restart_menus', 'configure-service-restarts.py')
flow = load('restart_flow_menus', 'sync-flow-menus.py')


class AcsRestartTests(unittest.TestCase):
    def setUp(self):
        self.image = 'ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-dotnet-prod/demo@sha256:' + 'a' * 64
        self.current = dict(metadata=dict(namespace='demo', name='demo', resourceVersion='10', generation=1),
            spec=dict(replicas=1, template=dict(metadata=dict(annotations={'existing': 'preserved'}),
                      spec=dict(containers=[dict(name='demo', image=self.image)]))),
            status=dict(observedGeneration=1, replicas=1, updatedReplicas=1, readyReplicas=1, availableReplicas=1))
        self.commands = []
        self.argv = ['acs-image-deploy.py', '--namespace', 'demo', '--deployment', 'demo',
                     '--container', 'demo', '--restart', '--expected-replicas', '1']

    def fake_run(self, *args):
        self.commands.append(args)
        if args[:2] == ('aliyun', 'sts'):
            return json.dumps(dict(AccountId=acs.ACCOUNT))
        if args[:2] == ('aliyun', 'cs'):
            return json.dumps(dict(config='fake-config'))
        if 'version' in args:
            return json.dumps(dict(clientVersion=dict(minor='36'), serverVersion=dict(minor='36')))
        if 'get' in args:
            return json.dumps(self.current)
        if 'patch' in args:
            operations = json.loads(args[args.index('-p') + 1])
            self.assertEqual([op['op'] for op in operations[:4]], ['test'] * 4)
            annotation = operations[-1]
            self.assertEqual(annotation['path'], '/spec/template/metadata/annotations')
            self.current['spec']['template']['metadata']['annotations'] = annotation['value']
            self.current['metadata']['generation'] += 1
            return 'patched'
        if 'rollout' in args:
            self.current['status']['observedGeneration'] = self.current['metadata']['generation']
            return 'ready'
        raise AssertionError(args)

    def run_main(self):
        with patch.object(sys, 'argv', self.argv), patch.object(acs, 'run', side_effect=self.fake_run):
            acs.main()

    def test_restart_only_changes_annotation_and_waits_for_rollout(self):
        before = copy.deepcopy(self.current['spec'])
        self.run_main()
        timestamp = self.current['spec']['template']['metadata']['annotations'].pop('kubectl.kubernetes.io/restartedAt')
        self.assertTrue(timestamp)
        self.assertEqual(self.current['spec'], before)
        self.assertEqual(sum('patch' in cmd for cmd in self.commands), 1)
        self.assertEqual(sum('rollout' in cmd for cmd in self.commands), 1)

    def test_unready_paused_unpinned_or_wrong_replicas_never_patch(self):
        for change in ('unready', 'paused', 'unpinned', 'replicas', 'old-replicas'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'unready': self.current['status']['readyReplicas'] = 0
                if change == 'paused': self.current['spec']['paused'] = True
                if change == 'unpinned': self.current['spec']['template']['spec']['containers'][0]['image'] = 'demo:latest'
                if change == 'replicas': self.current['spec']['replicas'] = 2
                if change == 'old-replicas': self.current['status']['replicas'] = 2
                with self.assertRaises(RuntimeError): self.run_main()
                self.assertFalse(any('patch' in cmd for cmd in self.commands))

    def test_zero_replicas_rejected_before_cloud_access(self):
        self.argv[-1] = '0'
        with self.assertRaises(RuntimeError): self.run_main()
        self.assertEqual(self.commands, [])

    def test_concurrent_patch_failure_is_not_retried(self):
        original = self.fake_run
        def conflict(*args):
            if 'patch' in args:
                self.commands.append(args)
                raise RuntimeError('resourceVersion test failed')
            return original(*args)
        with patch.object(sys, 'argv', self.argv), patch.object(acs, 'run', side_effect=conflict):
            with self.assertRaises(RuntimeError): acs.main()
        self.assertEqual(sum('patch' in cmd for cmd in self.commands), 1)
        self.assertFalse(any('rollout' in cmd for cmd in self.commands))


class EcsRestartTests(unittest.TestCase):
    def run_remote(self, environment='Test', health=True, worker=False):
        commands = []
        def fake_run(args, **kwargs):
            commands.append(args)
            prop = args[args.index('-p') + 1] if '-p' in args else None
            values = {'LoadState': 'loaded', 'WorkingDirectory': '/test', 'MainPID': '123',
                      'Environment': f'ASPNETCORE_ENVIRONMENT={environment} ASPNETCORE_URLS=http://0.0.0.0:3000'}
            return subprocess.CompletedProcess(args, 0, values.get(prop, ''), '')
        target = dict(unit='demo.api', directory='/test', worker=worker, java=False, port=None)
        output = io.StringIO()
        response = io.BytesIO()
        response.status = 200
        with patch('sys.stdin', io.StringIO(json.dumps(target))), patch('subprocess.run', side_effect=fake_run), \
             patch('time.sleep'), patch('urllib.request.urlopen', side_effect=None if health else OSError('not ready'),
                                       return_value=response), redirect_stdout(output), redirect_stderr(output):
            try:
                exec(compile(ecs.REMOTE, '<ecs-remote>', 'exec'), {})
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, commands, output.getvalue()

    def test_test_api_restarts_once_and_checks_health(self):
        code, commands, output = self.run_remote()
        self.assertEqual(code, 0)
        self.assertEqual(sum('restart' in c for c in commands), 1)
        self.assertIn('ready=true', output)

    def test_production_environment_is_rejected_before_restart(self):
        code, commands, _ = self.run_remote(environment='Production')
        self.assertEqual(code, 1)
        self.assertFalse(any('restart' in c for c in commands))

    def test_failed_health_does_not_repeat_restart(self):
        code, commands, _ = self.run_remote(health=False)
        self.assertEqual(code, 1)
        self.assertEqual(sum('restart' in c for c in commands), 1)

    def test_worker_requires_stable_process(self):
        code, commands, output = self.run_remote(worker=True)
        self.assertEqual(code, 0)
        self.assertEqual(sum('MainPID' in c for c in commands), 3)
        self.assertIn('readiness=systemd', output)

    def test_env_loader_suppresses_source_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.env'
            path.write_text('echo private-source-output\nDEPLOY_HOST=127.0.0.1\nOTHER=private-value\n')
            self.assertEqual(ecs.env_values(path, ['DEPLOY_HOST']), {'DEPLOY_HOST': '127.0.0.1'})


class RestartMenuTests(unittest.TestCase):
    def test_surgical_update_preserves_publish_and_static_targets(self):
        row = dict(id='demo', namespace='demo', deployment='demo', container='demo', replicas=1)
        data = {'projects': [dict(id='jifen', services=[
            dict(id='api-front', targets={'test': {'commands': {'run': [menus.OLD_ROOTS[0]+'/scripts/points-mall-deploy.py']}}}),
            dict(id='admin-oss', targets={'test': {'commands': {'run': ['echo static']}}}),
            dict(id='flow-demo-release', targets={'prod': {'commands': {'run': ['echo release']}}})]) ]}
        menus.update_menu(data, [row])
        snapshot = copy.deepcopy(data)
        menus.update_menu(data, [row])
        self.assertEqual(data, snapshot)
        services = data['projects'][0]['services']
        self.assertNotIn(menus.OLD_ROOTS[0], services[0]['targets']['test']['commands']['run'][0])
        self.assertNotIn('restart', services[1]['targets']['test']['commands'])
        self.assertEqual(services[2]['targets']['prod']['commands']['run'], ['echo release'])
        self.assertIn('--restart', services[2]['targets']['prod']['commands']['restart'][0])

    def test_zero_replica_flow_has_no_restart(self):
        row = dict(id='dgye-api', name='DGYE', kind='java', branch='release', repo_dir='/source',
                   acr_id='id', namespace='dgye-api', deployment='dgye-api', container='dgye-api', replicas=0)
        target = flow.flow_entries(row, dict(build=1, confirm=2))[0]['targets']['prod']
        self.assertNotIn('restart', target['commands'])


if __name__ == '__main__':
    unittest.main()

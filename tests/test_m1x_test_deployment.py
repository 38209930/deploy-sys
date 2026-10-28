import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


menu = load('m1x_menu', 'configure-m1x-test.py')
api = load('m1x_test_api', 'm1x-test-api.py')


class M1XTestDeploymentTests(unittest.TestCase):
    def test_menu_preserves_production_and_other_projects_and_is_idempotent(self):
        data = {'projects': [{'id': 'other', 'services': []}, {'id': 'm1x', 'services': [
            {'id': sid, 'targets': {'prod': {'commands': {'run': ['existing production command']}}}}
            for sid in ('flow-m1x-api-release', 'flow-m1x-worker-release', 'manage-oss', 'exam-oss')]}]}
        original = copy.deepcopy(data)
        menu.update_menu(data)
        once = copy.deepcopy(data)
        menu.update_menu(data)
        self.assertEqual(data, once)
        self.assertEqual(data['projects'][0], original['projects'][0])
        services = {s['id']: s for s in data['projects'][1]['services']}
        for old in original['projects'][1]['services']:
            self.assertEqual(services[old['id']]['targets']['prod'], old['targets']['prod'])
        self.assertEqual(set(services['m1x-api-test']['targets']), {'test'})
        self.assertNotIn('test', services['flow-m1x-worker-release']['targets'])
        for sid, bucket in [('manage-oss', 'm1x-manage-test'), ('exam-oss', 'm1x-exam-test')]:
            command = '\n'.join(services[sid]['targets']['test']['commands']['run'])
            self.assertIn('M1X_OSS_BUCKET=' + bucket + ' ', command)
            self.assertIn("M1X_OSS_BUILD_COMMAND='npm run build:test'", command)

    def test_export_does_not_write_application_or_deployment_configs(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name in ['pom.xml', 'train-web/src/main/resources/application-prod.yml',
                         'deploy/private.env', 'train-web/src/main/resources/mapper/Account.xml']:
                data = b'fixture'
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        with tempfile.TemporaryDirectory() as directory, patch.object(api.subprocess, 'check_output', return_value=stream.getvalue()) as command:
            root = Path(directory)
            api.export_source(root)
            self.assertTrue((root / 'pom.xml').exists())
            self.assertTrue((root / 'train-web/src/main/resources/mapper/Account.xml').exists())
            self.assertFalse((root / 'train-web/src/main/resources/application-prod.yml').exists())
            self.assertFalse((root / 'deploy').exists())
            self.assertEqual(command.call_args.args[0][-1], api.COMMIT)

    def test_config_bearing_and_worker_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / 'api.jar'
            with zipfile.ZipFile(jar, 'w') as archive:
                archive.writestr('BOOT-INF/classes/com/ruishi/train/TrainApplication.class', b'fixture')
            api.validate_artifact(jar)
            with zipfile.ZipFile(jar, 'a') as archive:
                archive.writestr('BOOT-INF/classes/application.yml', b'fixture')
            with self.assertRaises(RuntimeError):
                api.validate_artifact(jar)
            with zipfile.ZipFile(jar, 'w') as archive:
                archive.writestr('BOOT-INF/classes/WorkerApplication.class', b'fixture')
            with self.assertRaises(RuntimeError):
                api.validate_artifact(jar)

    def test_check_does_not_connect_or_build(self):
        with patch.object(api.sys, 'argv', ['m1x-test-api.py', 'check']), \
             patch.object(api, 'Connection') as connection, patch.object(api, 'build_api') as build:
            api.main()
        connection.assert_not_called()
        build.assert_not_called()

    def test_failed_start_restores_previous_jar_without_changing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'releases').mkdir()
            (root / 'config').mkdir()
            jar = root / 'releases/api-88cacbc.jar'
            jar.write_bytes(b'old-api')
            stage = root / ('releases/.upload-' + 'a' * 32 + '.jar')
            stage.write_bytes(b'new-api')
            for name in ('application.yml', 'api.env'):
                (root / 'config' / name).write_bytes(b'private-config-fixture')
            starts = []

            def systemctl(command, **kwargs):
                if command[1] == 'start':
                    starts.append(command)
                    if len(starts) == 1:
                        raise api.subprocess.CalledProcessError(1, command)
                if 'WorkingDirectory' in command:
                    return str(root)
                if 'ExecStart' in command:
                    return str(jar) + ' --spring.config.location=file:/opt/m1x-test/config/application.yml'
                return 'active'

            response = io.BytesIO(b'{"status":"UP"}')
            response.status = 200
            remote = api.REMOTE.replace("root=pathlib.Path('/opt/m1x-test')", 'root=pathlib.Path(' + repr(str(root)) + ')')
            request = io.StringIO(api.json.dumps({'action': 'deploy', 'stage': str(stage),
                                                 'sha256': hashlib.sha256(b'new-api').hexdigest()}))
            output = io.StringIO()
            with patch('sys.stdin', request), patch('subprocess.check_output', side_effect=systemctl), \
                 patch('pwd.getpwnam', return_value=SimpleNamespace(pw_uid=0, pw_gid=0)), \
                 patch('os.chown'), patch('urllib.request.urlopen', return_value=response), \
                 redirect_stdout(output), redirect_stderr(output), self.assertRaises(SystemExit) as result:
                exec(remote, {})
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(len(starts), 2)
            self.assertEqual(jar.read_bytes(), b'old-api')
            self.assertFalse(stage.exists())
            self.assertIn('已恢复上一版', output.getvalue())
            for name in ('application.yml', 'api.env'):
                self.assertEqual((root / 'config' / name).read_bytes(), b'private-config-fixture')


if __name__ == '__main__':
    unittest.main()

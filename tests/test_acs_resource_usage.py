import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('resources', Path(__file__).resolve().parents[1] / 'scripts/acs-resource-usage.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class ResourceQueryTests(unittest.TestCase):
    def test_wrong_account_never_requests_cluster_credentials(self):
        with patch.object(resources, 'cloud', return_value={'AccountId': 'wrong'}) as cloud, patch('sys.argv', ['resources', '--namespace', 'demo', '--deployment', 'demo']):
            with self.assertRaisesRegex(RuntimeError, '账号不匹配'):
                resources.main()
            self.assertEqual(cloud.call_count, 1)

    def test_credentials_cleaned_on_kubernetes_failure(self):
        paths = []
        def failed_call(*args):
            paths.append(Path(args[args.index('--kubeconfig') + 1]))
            self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
            raise RuntimeError('connection failed')
        with patch.object(resources, 'cloud', side_effect=[{'AccountId': resources.ACCOUNT}, {'config': 'test-only'}]), patch.object(resources, 'call', side_effect=failed_call), patch('sys.argv', ['resources', '--namespace', 'demo', '--deployment', 'demo']):
            with self.assertRaises(RuntimeError):
                resources.main()
        self.assertFalse(paths[0].exists())

    def test_selector_keeps_expression_scope(self):
        self.assertEqual(resources.selector_text({'matchLabels': {'app': 'demo'}, 'matchExpressions': [{'key': 'role', 'operator': 'In', 'values': ['api', 'worker']}]}), 'app=demo,role in (api,worker)')
        with self.assertRaises(RuntimeError):
            resources.selector_text({})

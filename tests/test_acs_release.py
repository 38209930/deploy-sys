"""用临时 Git 仓库和假的云端命令验证完整 ACS 发布，不访问真实云端。"""
import json
import os
from pathlib import Path
import subprocess
import unittest

import test_release_selection as fixtures


STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
root = Path(os.environ['FAKE_ROOT'])
with (root/'calls').open('a') as f: f.write(Path(sys.argv[0]).name+' '+ ' '.join(a)+'\\n')
head = os.environ['FAKE_HEAD']
digest = 'b'*64
image = os.environ['FLOW_IMAGE_REPO']+'@sha256:'+digest
def out(v): print(json.dumps(v))
if Path(sys.argv[0]).name == 'kubectl':
    if 'version' in a: out({'clientVersion':{'minor':'36'},'serverVersion':{'minor':'36'}})
    elif 'patch' in a: (root/'patched').touch(); print('patched')
    elif 'rollout' in a:
        if (root/'fail-rollout').exists(): sys.exit(1)
        print('rolled out')
    elif 'get' in a:
        current = image if (root/'patched').exists() else os.environ['FLOW_IMAGE_REPO']+'@sha256:'+'a'*64
        out({'metadata':{'namespace':'synthetic','resourceVersion':'1','generation':1},
             'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'api','image':current}]}}},
             'status':{'observedGeneration':1,'updatedReplicas':1,'readyReplicas':1,'availableReplicas':1}})
    else: raise SystemExit('unexpected kubectl call')
elif a[0]=='sts': out({'AccountId':'1442361567788059'})
elif a[0]=='cs': out({'config':'synthetic-test-config'})
elif a[0]=='cr':
    if a[1]=='list-repo-tag': out({'Images':[{'Tag':'20261009-'+head[:8],'Digest':digest,'ImageCreate':1500}]})
    elif a[1]=='get-repo-tag': out({'Digest':digest,'IsSuccess':True,'Status':'NORMAL'})
    else: raise SystemExit('unexpected cr call')
elif a[0]=='devops':
    pid=a[a.index('--pipelineId')+1]
    if a[1]=='StartPipelineRun': out({'pipelineRunId':123 if pid=='100' else 456})
    elif a[1]=='PassPipelineValidate': (root/'approved').touch(); out({})
    elif a[1]=='GetPipelineRun':
        if pid=='100':
            status='FAIL' if (root/'fail-build').exists() else 'RUNNING' if (root/'pending-build').exists() else 'SUCCESS'
            out({'pipelineRun':{'status':status,
                 'sources':[{'data':{'branch':'release','commint':json.dumps([{'commitId':head}])}}],
                 'createTime':1000,'updateTime':2000,'stages':[]}})
        else:
            status='SUCCESS' if (root/'approved').exists() else 'RUNNING'
            out({'pipelineRun':{'status':status,'stages': [] if status=='SUCCESS' else
                 [{'stageInfo':{'jobs':[{'id':789,'status':'WAITING','name':'confirm'}]}}]}})
    else: raise SystemExit('unexpected devops call')
else: raise SystemExit('unexpected aliyun call')
'''


class AcsReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReleaseSelectionTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)
        self.root = self.fixture.root
        self.repo = self.fixture.repo
        self.fixture.g(self.repo, 'switch', 'release')
        self.head = self.fixture.g(self.repo, 'rev-parse', 'HEAD')
        self.script = Path(__file__).resolve().parent.parent / 'scripts/flow-release.sh'
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        for name in ('aliyun', 'kubectl'):
            path = bin_dir/name
            path.write_text(STUB)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],
                        FAKE_ROOT=str(self.root), FAKE_HEAD=self.head,
                        FLOW_PIPELINE_ID='100', FLOW_DEPLOY_PIPELINE_ID='200', FLOW_SERVICE='synthetic',
                        FLOW_REPO_DIR=str(self.repo), FLOW_STATE_DIR=str(self.root/'state'),
                        FLOW_ACR_INSTANCE_ID='synthetic', FLOW_ACR_REPO_ID='synthetic',
                        FLOW_IMAGE_REPO='ruishi-prod-registry-vpc.cn-beijing.cr.aliyuncs.com/ruishi-java-prod/synthetic',
                        FLOW_NAMESPACE='synthetic', FLOW_DEPLOYMENT='api', FLOW_CONTAINER='api',
                        FLOW_EXPECTED_REPLICAS='1', FLOW_RELEASE_BRANCH='release', FLOW_CONFIRM='yes',
                        FLOW_BUILD_RUN_ID='', FLOW_RUN_ID='', FLOW_DEPLOY_MODE='local')

    def execute(self):
        return subprocess.run(['bash', str(self.script), 'release'], env=self.env, text=True,
                              capture_output=True, timeout=30)

    def calls(self):
        return (self.root/'calls').read_text() if (self.root/'calls').exists() else ''

    def test_single_action_pushes_builds_confirms_deploys_and_verifies(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('发布完成', result.stdout)
        self.assertIn('last_status=DEPLOY_SUCCESS', (self.root/'state/synthetic.env').read_text())
        calls = self.calls()
        self.assertEqual(calls.count('StartPipelineRun'), 2)
        self.assertIn('PassPipelineValidate', calls)
        self.assertIn('rollout status', calls)

    def test_no_confirmation_cannot_start_cloud_operations(self):
        self.env['FLOW_CONFIRM'] = 'no'
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), '')

    def test_failed_build_cannot_confirm_or_update_acs(self):
        (self.root/'fail-build').touch()
        self.assertNotEqual(self.execute().returncode, 0)
        calls = self.calls()
        self.assertNotIn('PassPipelineValidate', calls)
        self.assertNotIn('kubectl', calls)
        self.assertEqual(calls.count('StartPipelineRun'), 1)

    def test_failed_rollout_reuses_image_and_still_checks_rollout(self):
        (self.root/'fail-rollout').touch()
        first = self.execute()
        self.assertNotEqual(first.returncode, 0)
        self.assertIn('last_status=APPROVED_PENDING_DEPLOY', (self.root/'state/synthetic.env').read_text())
        (self.root/'fail-rollout').unlink()
        second = self.execute()
        self.assertEqual(second.returncode, 0, second.stdout+second.stderr)
        self.assertIn('复用当前 release', second.stdout)
        self.assertIn('继续检查 rollout', second.stdout)
        self.assertEqual(self.calls().count('StartPipelineRun'), 2)
        self.assertEqual(self.calls().count('rollout status'), 2)
        self.assertEqual(self.calls().count('PassPipelineValidate'), 1)

    def test_different_source_commit_cannot_start_confirmation(self):
        self.env['FAKE_HEAD'] = 'c'*40
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('源码提交', result.stderr)
        self.assertEqual(self.calls().count('StartPipelineRun'), 1)
        self.assertNotIn('kubectl', self.calls())

    def test_wait_timeout_is_resumed_without_another_start(self):
        self.env['FLOW_BUILD_TIMEOUT'] = '0'
        (self.root/'pending-build').touch()
        self.assertNotEqual(self.execute().returncode, 0)
        (self.root/'pending-build').unlink()
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('继续跟踪本次构建', result.stdout)
        self.assertEqual(self.calls().count('StartPipelineRun'), 2)

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'merge-apollo-admin.py'


class ApolloAdminMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'origin.git'
        self.repo = self.root / 'pc'
        self.repo.mkdir()
        self.command(self.root, 'git', 'init', '--bare', str(self.remote))
        self.command(self.repo, 'git', 'init', '-b', 'master')
        self.git('config', 'user.name', 'Integration Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('remote', 'add', 'origin', str(self.remote))
        (self.repo / 'base.txt').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.git('branch', 'release')
        self.git('push', 'origin', 'master', 'release')
        self.git('checkout', '-b', 'feature/admin-change')
        (self.repo / 'feature.txt').write_text('feature\n')
        self.git('add', '.')
        self.git('commit', '-m', 'feature')
        self.before = self.refs()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.npm = self.bin / 'npm'
        self.npm.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$BUILD_LOG"\nexit "${BUILD_EXIT:-0}"\n')
        self.npm.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        BUILD_LOG=str(self.root / 'build.log'))

    def command(self, cwd, *args, **kwargs):
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True, **kwargs).stdout.strip()

    def git(self, *args):
        return self.command(self.repo, 'git', *args)

    def refs(self):
        return self.command(self.root, 'git', '--git-dir=' + str(self.remote), 'show-ref')

    def merge(self):
        return subprocess.run(['python3', str(SCRIPT), '--repo', str(self.repo)],
                              capture_output=True, text=True, env=self.env)

    def colleague_commit(self, filename, content):
        other = self.root / 'colleague'
        self.command(self.root, 'git', 'clone', '-b', 'master', str(self.remote), str(other))
        self.command(other, 'git', 'config', 'user.name', 'Colleague')
        self.command(other, 'git', 'config', 'user.email', 'colleague@example.invalid')
        (other / filename).write_text(content)
        self.command(other, 'git', 'add', '.')
        self.command(other, 'git', 'commit', '-m', 'colleague')
        self.command(other, 'git', 'push', 'origin', 'master')
        return other

    def test_success_includes_colleague_master_and_preserves_branch(self):
        self.colleague_commit('colleague.txt', 'latest master\n')
        result = self.merge()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'feature/admin-change')
        heads = {line.split()[0] for line in self.refs().splitlines()}
        self.assertEqual(heads, {self.git('rev-parse', 'HEAD')})
        self.assertTrue((self.repo / 'feature.txt').exists())
        self.assertTrue((self.repo / 'colleague.txt').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual((self.root / 'build.log').read_text().splitlines(),
                         ['ci --no-audit --no-fund', 'run build:prod'])

    def test_release_as_pending_branch(self):
        self.git('checkout', 'release')
        self.git('merge', '--ff-only', 'feature/admin-change')
        result = self.merge()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'release')
        self.assertEqual(len({line.split()[0] for line in self.refs().splitlines()}), 1)

    def test_release_extra_changes_are_built_before_master_push(self):
        self.git('checkout', 'release')
        (self.repo / 'release-only.txt').write_text('release\n')
        self.git('add', '.')
        self.git('commit', '-m', 'release extra')
        self.git('push', 'origin', 'release')
        self.git('checkout', 'feature/admin-change')
        result = self.merge()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.repo / 'release-only.txt').exists())
        self.assertEqual((self.root / 'build.log').read_text().count('run build:prod'), 2)

    def test_rejected_master_push_leaves_all_remote_branches_unchanged(self):
        hook = self.remote / 'hooks' / 'update'
        hook.write_text('#!/bin/sh\n[ "$1" != refs/heads/master ]\n')
        hook.chmod(0o755)
        result = self.merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), self.before)

    def test_build_failure_does_not_push_or_change_local_head(self):
        head = self.git('rev-parse', 'HEAD')
        self.env['BUILD_EXIT'] = '7'
        result = self.merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), self.before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_conflict_does_not_push_or_leave_local_conflict(self):
        (self.repo / 'base.txt').write_text('feature change\n')
        self.git('commit', '-am', 'feature conflict')
        self.colleague_commit('base.txt', 'master change\n')
        before = self.refs()
        result = self.merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), before)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertFalse((self.root / 'build.log').exists())

    def test_remote_change_during_build_stops_before_push(self):
        other = self.colleague_commit('colleague.txt', 'first\n')
        self.env['COLLEAGUE_REPO'] = str(other)
        self.npm.write_text('''#!/bin/sh
if [ "$1" = run ]; then
  printf 'second\\n' > "$COLLEAGUE_REPO/colleague.txt"
  git -C "$COLLEAGUE_REPO" commit -am second >/dev/null
  git -C "$COLLEAGUE_REPO" push origin master >/dev/null
fi
''')
        release_before = self.command(self.root, 'git', '--git-dir=' + str(self.remote), 'rev-parse', 'release')
        result = self.merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('构建期间远端分支已更新', result.stderr)
        self.assertEqual(self.command(self.root, 'git', '--git-dir=' + str(self.remote), 'rev-parse', 'release'), release_before)
        self.assertNotIn('refs/heads/feature/admin-change', self.refs())

    def test_dirty_worktree_is_rejected(self):
        (self.repo / 'uncommitted.txt').write_text('keep\n')
        result = self.merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.refs(), self.before)
        self.assertEqual((self.repo / 'uncommitted.txt').read_text(), 'keep\n')


if __name__ == '__main__':
    unittest.main()

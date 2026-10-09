from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import deploysys
import deploysys_gui
import deploysys_release as release
from deploysys_store import ConfigError


class ReleaseSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source repo'
        self.remote = self.root / 'origin.git'
        self.data = self.root / 'data'
        self.data.mkdir()
        self.tool = self.root / 'tool'
        self.tool.mkdir()
        self.g(self.root, 'init', '--bare', str(self.remote))
        self.g(self.root, 'init', '-b', 'master', str(self.repo))
        self.g(self.repo, 'config', 'user.name', 'test')
        self.g(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'base.txt').write_text('base')
        self.commit('base')
        self.g(self.repo, 'branch', 'release')
        self.g(self.repo, 'branch', 'dev')
        self.g(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.g(self.repo, 'push', 'origin', 'master', 'release', 'dev')
        self.g(self.repo, 'switch', 'dev')
        self.commands = [f'cd {shlex.quote(str(self.repo))}', 'npm run build:prod']

    def g(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, title):
        self.g(self.repo, 'add', '-A')
        self.g(self.repo, 'commit', '-m', title)
        return self.g(self.repo, 'rev-parse', 'HEAD')

    def advance(self, branch='dev', filename='new.txt', value='new'):
        self.g(self.repo, 'switch', branch)
        (self.repo / filename).write_text(value)
        head = self.commit(branch)
        self.g(self.repo, 'push', 'origin', branch)
        return head

    def plan(self):
        return release.plan_release('prod', self.commands, '执行', self.tool, self.data)

    def test_only_commits_missing_from_release_are_candidates_and_evidence_is_exact_sha(self):
        head = self.advance()
        snapshot = release.build_snapshot(self.commands, self.tool)
        release.record_build(snapshot, self.data, 'admin')
        plan = self.plan()
        candidate = plan[0]['candidates'][0]
        self.assertEqual(candidate['name'], 'dev')
        self.assertEqual(candidate['aliases'], ['origin/dev'])
        self.assertEqual(candidate['ahead'], 1)
        self.assertTrue(candidate['build'])
        self.assertEqual(candidate['head'], head)
        self.advance(filename='second.txt')
        self.assertIsNone(self.plan()[0]['candidates'][0]['build'])

    def test_selected_branches_merged_pushed_and_release_selected(self):
        head = self.advance()
        self.g(self.repo, 'switch', '-c', 'unfinished', 'master')
        self.advance('unfinished', 'unfinished.txt')
        plan = self.plan()
        selected = [{'repo': str(self.repo), 'ref': 'refs/heads/dev'}]
        messages = []
        release.apply_release(plan, selected, self.commands, messages.append)
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'release')
        self.assertEqual(self.g(self.repo, 'rev-parse', 'HEAD'), self.g(self.repo, 'rev-parse', 'origin/release'))
        self.assertEqual(self.g(self.repo, 'merge-base', 'release', head), head)
        self.assertFalse((self.repo / 'unfinished.txt').exists())
        self.assertTrue(any('合并 dev' in x for x in messages))

    def test_no_selection_switches_without_merging_dev(self):
        self.advance()
        base = self.g(self.repo, 'rev-parse', 'release')
        release.apply_release(self.plan(), [], self.commands, lambda _: None)
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'release')
        self.assertEqual(self.g(self.repo, 'rev-parse', 'HEAD'), base)

    def test_dirty_files_stop_but_environment_override_survives(self):
        self.advance()
        (self.repo / '.env.production').write_text('synthetic-only')
        self.commit('test config')
        (self.repo / '.env.production').write_text('local override')
        # release needs the same tracked config to preserve this local difference.
        self.g(self.repo, 'branch', '-f', 'release', 'dev')
        self.g(self.repo, 'push', 'origin', 'release')
        release.apply_release(self.plan(), [], self.commands, lambda _: None)
        self.assertEqual((self.repo / '.env.production').read_text(), 'local override')
        (self.repo / 'unrelated.txt').write_text('keep')
        with self.assertRaisesRegex(ConfigError, '未提交'):
            self.plan()
        self.assertEqual((self.repo / 'unrelated.txt').read_text(), 'keep')

    def test_branch_changed_while_selecting_blocks_before_switch(self):
        self.advance()
        plan = self.plan()
        self.advance(filename='later.txt')
        with self.assertRaisesRegex(ConfigError, '已变化'):
            release.apply_release(plan, [], self.commands, lambda _: None)
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'dev')

    def test_unknown_selection_cannot_run_git_mutations(self):
        plan = self.plan()
        with self.assertRaisesRegex(ConfigError, '候选列表'):
            release.apply_release(plan, [{'repo': str(self.repo), 'ref': 'refs/heads/not-real'}], self.commands, lambda _: None)
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'dev')

    def test_release_worktree_used_and_double_quoted_source_path_rewritten(self):
        head = self.advance()
        work = self.root / 'release checkout'
        self.g(self.repo, 'worktree', 'add', str(work), 'release')
        commands = [f'cd "{self.repo}"', 'npm run build:prod']
        updated, _ = release.apply_release(self.plan(), [{'repo': str(self.repo), 'ref': 'refs/heads/dev'}], commands, lambda _: None)
        self.assertEqual(updated[0], f'cd "{work}"')
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'dev')
        self.assertEqual(self.g(work, 'merge-base', 'release', head), head)

    def test_merge_conflict_kept_and_no_push_or_deployment(self):
        self.advance(filename='base.txt', value='dev')
        self.advance('release', 'base.txt', 'release')
        self.g(self.repo, 'switch', 'dev')
        plan = self.plan()
        remote = self.g(self.repo, 'rev-parse', 'origin/release')
        with self.assertRaisesRegex(ConfigError, '合并失败'):
            release.apply_release(plan, [{'repo': str(self.repo), 'ref': 'refs/heads/dev'}], self.commands, lambda _: None)
        self.assertEqual(self.g(self.repo, 'rev-parse', 'origin/release'), remote)
        self.assertTrue(self.g(self.repo, 'rev-parse', 'MERGE_HEAD'))

    def test_test_environment_status_and_restarts_do_not_change_branches(self):
        for target, commands, action in [('test', self.commands, '执行'), ('prod', self.commands, '状态检查'),
                ('prod', ['bash scripts/flow-release.sh status'], 'run'), ('prod', ['systemctl restart api'], 'restart')]:
            self.assertIsNone(release.plan_release(target, commands, action, self.tool, self.data))
        self.assertEqual(self.g(self.repo, 'branch', '--show-current'), 'dev')

    def test_custom_frontend_scripts_and_explicit_sources_are_checked(self):
        for script in ('oss', 'deploy:server', 'release:h5', 'build:prod'):
            commands = [f'cd {shlex.quote(str(self.repo))}', 'npm run ' + script]
            self.assertTrue(release.needs_release('prod', commands, 'run'))
        commands = [f'python3 branch_flow.py --repo {shlex.quote(str(self.repo))} prod -- npm run build:prod']
        self.assertEqual(release.source_repos(commands, self.tool), [str(self.repo)])
        config = {'release_repos': [str(self.repo)], 'release_required': True}
        plan = release.plan_release('prod', ['bash scripts/custom.sh'], 'run', self.tool, self.data, target_cfg=config)
        self.assertEqual(plan[0]['repo'], str(self.repo))

    def test_monitor_rollback_restart_and_migration_inside_deploy_directory_do_not_switch(self):
        for script in ('restart-live-api-front.sh', 'rollback-web.sh', 'health-check.sh', 'migrate-api.sh'):
            commands = [f'cd {shlex.quote(str(self.repo))}', f'bash scripts/deploy/{script} prod']
            self.assertFalse(release.needs_release('prod', commands, 'run'))

    def test_missing_deploy_source_fails_explicitly(self):
        with self.assertRaisesRegex(ConfigError, 'release_repos'):
            release.plan_release('prod', ['bash deploy-api.sh'], 'run', self.tool, self.data)

    def test_worktree_subdirectory_is_rewritten_and_hidden_wrapper_is_blocked(self):
        work = self.root / 'release checkout'
        self.g(self.repo, 'worktree', 'add', str(work), 'release')
        commands = [f'cd {shlex.quote(str(self.repo / "subdir"))}', 'npm run build:prod']
        config = {'release_repos': [str(self.repo)]}
        plan = release.plan_release('prod', commands, 'run', self.tool, self.data, target_cfg=config)
        updated, _ = release.apply_release(plan, [], commands, lambda _: None)
        self.assertIn(str(work / 'subdir'), updated[0])
        with self.assertRaisesRegex(ConfigError, '包装命令'):
            release.plan_release('prod', ['bash deploy-api.sh'], 'run', self.tool, self.data, target_cfg=config)

    def test_flow_manifest_resolves_repo_and_build_state_marks_exact_commit(self):
        head = self.advance()
        folder = self.tool / 'deployment/flow'
        folder.mkdir(parents=True)
        (folder / 'services.yaml').write_text(f'services:\n  - id: api\n    repo_dir: "{self.repo}"\n')
        state = self.data / 'flow-state'
        state.mkdir(parents=True)
        (state / 'api.env').write_text(f'service=api\nlast_status=WAITING_CONFIRM\nsource_commit={head}\n')
        plan = release.plan_release('prod', ['FLOW_SERVICE=api bash scripts/flow-release.sh deploy'], 'run', self.tool, self.data)
        self.assertTrue(plan[0]['candidates'][0]['build'])

    def test_tool_worktrees_are_never_source_repositories(self):
        self.g(self.root, 'init', '-b', 'main', str(self.tool))
        self.g(self.tool, 'config', 'user.email', 'test@example.invalid')
        self.g(self.tool, 'config', 'user.name', 'test')
        (self.tool / 'x').write_text('x')
        self.g(self.tool, 'add', 'x')
        self.g(self.tool, 'commit', '-m', 'x')
        work = self.root / 'tool-work'
        self.g(self.tool, 'worktree', 'add', '-b', 'feature', str(work))
        self.assertEqual(release.source_repos([f'cd {self.tool}', f'FLOW_REPO_DIR={shlex.quote(str(self.repo))} bash scripts/flow-release.sh build'], work), [str(self.repo)])

    def test_cli_multiple_selection_and_cancel(self):
        self.advance()
        plan = self.plan()
        selected = release.prompt_selection(plan, lambda _: '1', lambda _: None)
        self.assertEqual(selected, [{'repo': str(self.repo), 'ref': 'refs/heads/dev'}])
        self.assertIsNone(release.prompt_selection(plan, lambda _: '0', lambda _: None))
        with self.assertRaises(ConfigError):
            release.prompt_selection(plan, lambda _: '99', lambda _: None)

    def test_missing_remote_release_does_not_create_branch(self):
        self.g(self.repo, 'push', 'origin', '--delete', 'release')
        self.g(self.repo, 'update-ref', '-d', 'refs/remotes/origin/release')
        with self.assertRaisesRegex(ConfigError, '缺少 release'):
            self.plan()

    def test_failed_or_changed_build_cannot_mark_head_success(self):
        snapshot = release.build_snapshot(self.commands, self.tool)
        self.advance()
        release.record_build(snapshot, self.data, 'admin')
        self.assertEqual(release.evidence(self.data), {})

    def test_gui_returns_selection_before_launch_and_rejects_changed_commands(self):
        self.advance()
        target = {'commands': {'run': self.commands}}
        project = {'id': 'p', 'services': [{'id': 's', 'targets': {'prod': target}}]}
        request = {'project_id': 'p', 'service_id': 's', 'target_name': 'prod'}
        with patch.object(deploysys, 'load_project_snapshot') as snapshot, patch.object(deploysys, 'ROOT', self.tool), \
             patch.object(deploysys, 'DATA_DIR', self.data), patch.object(deploysys_gui.EXECUTIONS, 'start') as start:
            snapshot.return_value.data = {'projects': [project]}
            result = deploysys_gui.start_execution(request)
            self.assertIn('release_plan', result)
            start.assert_not_called()
            request.update(release_plan=result['release_plan'], release_command_hash=result['release_command_hash'], release_selection=[])
            target['commands']['run'].append('echo changed')
            with self.assertRaisesRegex(ConfigError, '已变化'):
                deploysys_gui.start_execution(request)
            start.assert_not_called()

    def test_flow_stale_artifact_stops_before_running_command(self):
        self.advance()
        commands = [f'FLOW_REPO_DIR={shlex.quote(str(self.repo))} FLOW_SERVICE=api bash scripts/flow-release.sh deploy']
        plan = release.plan_release('prod', commands, '执行', self.tool, self.data)
        with patch.object(deploysys, 'ROOT', self.tool), patch.object(deploysys, 'DATA_DIR', self.data), \
             patch.object(deploysys, 'LOGS_DIR', self.root / 'logs'), patch.object(deploysys.CommandRunner, 'run_block') as run:
            results, _ = deploysys.run_action_commands({'id': 'p'}, {'id': 's'}, 'prod', {}, '执行', commands, {},
                lambda _: None, release_plan=plan, release_selection=[{'repo': str(self.repo), 'ref': 'refs/heads/dev'}])
            run.assert_not_called()
            self.assertEqual(results[0].exit_code, 1)
            self.assertIn('先执行准备发布', results[0].output)

    def test_multiple_selected_branches_are_merged(self):
        first = self.advance()
        self.g(self.repo, 'switch', '-c', 'feature/second', 'master')
        second = self.advance('feature/second', 'second.txt')
        selected = [{'repo': str(self.repo), 'ref': f'refs/heads/{branch}'} for branch in ('dev', 'feature/second')]
        release.apply_release(self.plan(), selected, self.commands, lambda _: None)
        for head in (first, second):
            self.assertEqual(self.g(self.repo, 'merge-base', 'release', head), head)

    def test_gui_confirmed_plan_launches_with_only_selected_branches(self):
        self.advance()
        target = {'commands': {'run': self.commands}}
        project = {'id': 'p', 'services': [{'id': 's', 'targets': {'prod': target}}]}
        request = {'project_id': 'p', 'service_id': 's', 'target_name': 'prod'}
        with patch.object(deploysys, 'load_project_snapshot') as snapshot, patch.object(deploysys, 'ROOT', self.tool), \
             patch.object(deploysys, 'DATA_DIR', self.data), patch.object(deploysys_gui.EXECUTIONS, 'start') as start, \
             patch.object(deploysys_gui.EXECUTIONS, '_summary', return_value={'id': 'test'}):
            snapshot.return_value.data = {'projects': [project]}
            result = deploysys_gui.start_execution(request)
            selected = [{'repo': str(self.repo), 'ref': 'refs/heads/dev'}]
            request.update(release_plan=result['release_plan'], release_command_hash=result['release_command_hash'], release_selection=selected)
            self.assertEqual(deploysys_gui.start_execution(request)['execution'], {'id': 'test'})
            self.assertEqual(start.call_args.args[-1], selected)

    def test_flow_source_can_be_found_from_same_services_prepare_menu(self):
        self.advance()
        commands = ['FLOW_SERVICE=api bash scripts/flow-release.sh deploy']
        project = {'services': [{'targets': {'prod': {'commands': {'run': [
            f'FLOW_SERVICE=api FLOW_REPO_DIR={shlex.quote(str(self.repo))} bash scripts/flow-release.sh push']}}}}]}
        plan = release.plan_release('prod', commands, 'run', self.tool, self.data, project)
        self.assertEqual(plan[0]['repo'], str(self.repo))

    def test_only_successful_build_is_recorded_by_runner(self):
        commands = [f'cd {shlex.quote(str(self.repo))}', 'echo synthetic-build']
        with patch.object(deploysys, 'ROOT', self.tool), patch.object(deploysys, 'DATA_DIR', self.data), \
             patch.object(deploysys, 'LOGS_DIR', self.root / 'logs'), patch.object(deploysys.CommandRunner, 'run_block') as run:
            run.return_value = deploysys.CommandResult('synthetic', 1, 'failed')
            deploysys.run_action_commands({'id': 'p'}, {'id': 's'}, 'test', {}, 'build', commands, {}, lambda _: None)
            self.assertEqual(release.evidence(self.data), {})
            run.return_value = deploysys.CommandResult('synthetic', 0, 'success')
            deploysys.run_action_commands({'id': 'p'}, {'id': 's'}, 'test', {}, 'build', commands, {}, lambda _: None)
            self.assertEqual(len(release.evidence(self.data)), 1)

    def test_flow_push_accepts_release_worktree_git_file(self):
        self.advance()
        work = self.root / 'release-work'
        self.g(self.repo, 'worktree', 'add', str(work), 'release')
        script = Path(release.__file__).parent / 'scripts/flow-release.sh'
        env = dict(os.environ, FLOW_REPO_DIR=str(work), FLOW_SERVICE='synthetic',
                   FLOW_STATE_DIR=str(self.data / 'flow-state'), FLOW_RELEASE_BRANCH='release',
                   FLOW_PIPELINE_ID='1')
        result = subprocess.run(['bash', str(script), 'push'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('本地与远端一致', result.stdout)


if __name__ == '__main__':
    unittest.main()

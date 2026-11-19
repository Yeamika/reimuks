"""External board builds must retain shared caches and consume linked exports."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import addons
import build
import output_paths
from board_exports import output_path, relative_path
from board_userspace import install_component


class OutputRouting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        env = dict(os.environ)
        for key in ('REIMUKS_BUILD_ROOT', 'REIMUKS_LEGACY_BUILD_ROOT', 'REIMUKS_BOOT_ROOT',
                    'REIMUKS_SHARED_BUILD_ROOT', 'REIMUKS_BOARD'):
            env.pop(key, None)
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        for name in ('BUILD', 'SHARED_BUILD', 'BOARD', 'DISTRIBUTION', 'TOOLS'):
            value = getattr(build, name)
            self.addCleanup(setattr, build, name, value)
        build.SHARED_BUILD = self.base/'shared'

    def test_defaults_are_separate_for_each_board(self):
        self.assertEqual(output_paths.build_root('w202ds', repo=self.base),
                         self.base/'build/boards/w202ds')
        self.assertEqual(output_paths.build_root('polaris', repo=self.base),
                         self.base/'build/boards/polaris')
        self.assertFalse((self.base/'build').exists())

    def test_project_selection_moves_board_outputs_but_preserves_shared_packages(self):
        paths = []
        for name in ('project-a', 'project-b'):
            with patch.dict(os.environ, REIMUKS_BUILD_ROOT=str(self.base/name)):
                build.select_board('w202ds')
                paths.append((build.profile_directory('kde'), build.artifact_directory(),
                              build.package_cache('apt-kde'), build.shared_distribution()))
        self.assertEqual(paths[0][0], paths[1][0])  # The configured distro is reusable.
        self.assertNotEqual(paths[0][1], paths[1][1])
        self.assertEqual(paths[0][2:], paths[1][2:])
        self.assertTrue(paths[0][2].is_relative_to(self.base/'shared'))

    def test_switching_board_refreshes_backend_without_leaking_previous_output(self):
        with patch.dict(os.environ, REIMUKS_BUILD_ROOT=str(self.base/'w202ds')):
            build.select_board('w202ds')
            first = build.kernel_directory()
        with patch.dict(os.environ, REIMUKS_SHARED_BUILD_ROOT=str(self.base/'shared')):
            build.select_board('polaris')
            self.assertEqual(build.kernel_directory(), self.base/'shared/boards/polaris/kernel')
            self.assertNotEqual(first, build.kernel_directory())
            self.assertIn('/cache/boards/polaris/', str(build.package_cache('apt-board-server', board=True)))

    def test_common_apps_stay_in_shared_distribution_storage(self):
        with patch.dict(os.environ, REIMUKS_BUILD_ROOT=str(self.base/'board')), \
                patch.object(sys, 'argv', ['addons.py', 'pack', '--profile', 'kde']), \
                patch.object(addons, 'pack', return_value={}) as package, \
                contextlib.redirect_stdout(io.StringIO()):
            build.select_board('w202ds')
            addons.main()
        _, cache, output = package.call_args.args
        self.assertTrue(cache.is_relative_to(self.base/'shared'))
        self.assertTrue(output.is_relative_to(self.base/'shared'))
        self.assertFalse((self.base/'board').exists())

    def test_plan_reports_external_root_without_creating_it(self):
        output = self.base/'external'
        result = subprocess.run([sys.executable, '-B', str(ROOT/'reimuks.py'),
                                 '--board', 'w202ds', '--target', 'initramfs',
                                 '--build-root', str(output), '--plan'],
                                check=True, text=True, capture_output=True)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['build_root'], str(output))
        self.assertEqual(plan['shared_build'], str(ROOT/'build'))
        self.assertFalse(output.exists())

    def test_distribution_build_does_not_load_a_board(self):
        import layers
        with patch.object(layers, 'plan', side_effect=AssertionError('board dependency')):
            self.assertIn('systemd-sysv', build.packages('server'))
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/distribution.py'), '--plan'],
                                env=dict(os.environ, REIMUKS_BOARD='no_such_board'),
                                text=True, capture_output=True, check=True)
        self.assertFalse(json.loads(result.stdout)['board_required'])

    def test_board_dependency_install_is_offline_and_does_not_change_distro_source(self):
        import layers
        build.select_board('w202ds')
        state = build.package_cache('apt-board-server', board=True)
        package = state/'archives/dependency.deb'
        package.parent.mkdir(parents=True)
        package.write_bytes(b'authenticated dependency')
        (state/'fetch-complete.json').write_text(json.dumps({
            'board': 'w202ds', 'profile': 'server', 'packages': layers.board_dependencies('server'),
            'distribution': build.identity(build.board_distribution(build.DEFAULT)),
            'archives': {package.name: build.digest(package)}}))
        with patch.object(build, 'apt', side_effect=AssertionError('unexpected network')):
            self.assertEqual(layers.fetch_board('server'), state)
        work = self.base/'board-work'
        work.mkdir()
        saved = work/'fakeroot.state'
        saved.write_text('ownership')
        manifest = {'packages': [{'file': 'board.deb'}]}
        with patch.object(layers, 'pack_board', return_value=manifest), \
                patch.object(build, 'artifact_directory', return_value=self.base/'board-artifacts'), \
                patch.object(build, 'proot') as runner:
            layers.install_packages(self.base/'rootfs', work, saved, 'server')
        script = (work/'install-layers.sh').read_text()
        self.assertIn('/board-packages/dependency.deb', script)
        self.assertIn(f'{state}/archives:/board-packages', runner.call_args.args[2])
        self.assertFalse(build.profile_directory('server').exists())
        package.write_bytes(b'changed dependency')
        with self.assertRaisesRegex(ValueError, 'changed'):
            layers.checked_board_cache('server')

    def test_external_hardware_staging_installs_and_stays_contained(self):
        board = self.base/'board'
        hardware = board/'kernel'
        source = hardware/'Devices/gpu/userspace'
        (source/'rootfs').mkdir(parents=True)
        (self.base/'linux-build').mkdir()
        (hardware/'output').symlink_to(self.base/'linux-build', target_is_directory=True)
        artifact = hardware/'output/userspace/gpu/rootfs/usr/lib/driver.so'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'compiled driver')
        (source/'artifacts.json').write_text(json.dumps({
            'schema': 1, 'base': 'project', 'rootfs': 'output/userspace/gpu/rootfs',
            'required': ['usr/lib/driver.so']}))
        (hardware/'board-userspace.json').write_text(json.dumps({
            'schema': 1, 'board': 'test', 'build': {'output': 'output/userspace'},
            'components': {'gpu': {'userspace': 'Devices/gpu/userspace'}}}))
        (board/'board.json').write_text(json.dumps({
            'schema': 1, 'board': 'test', 'userspace_manifest': 'kernel/board-userspace.json'}))
        root = self.base/'rootfs'
        root.mkdir()
        install_component(root, board, 'gpu')
        self.assertEqual((root/'usr/lib/driver.so').read_bytes(), b'compiled driver')
        with self.assertRaises(ValueError):
            relative_path(hardware, 'output/userspace')
        with self.assertRaises(ValueError):
            output_path(hardware, 'output/../unrelated', 'output/userspace')
        with self.assertRaises(ValueError):
            output_path(hardware, '/etc/passwd', 'output/userspace')
        outside = self.base/'outside'
        outside.mkdir()
        (hardware/'output/userspace/escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            output_path(hardware, 'output/userspace/escape/file', 'output/userspace')


if __name__ == '__main__':
    unittest.main()

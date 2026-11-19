"""Polaris routing must not consume W202DS sources or board policies."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import boot
import build
import overlay_registry
import board_userspace
from distributions import DEFAULT, identity, load_distribution, sources_list


class PolarisRegistrationTest(unittest.TestCase):
    def test_source_and_boot_projects_are_distinct_and_resolve(self):
        board, config = boot.boards()['polaris']
        self.assertNotEqual((board/'kernel').resolve(), (board/'boot').resolve())
        self.assertTrue((board/'kernel/config/kernel-source.json').is_file())
        for key in ('kernel_builder', 'kernel_exporter', 'boot_builder'):
            self.assertTrue((board/config[key]).is_file(), key)
        self.assertEqual(config['profiles'], ['desktop/server'])

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(ROOT/'reimuks.py'),
                               '--board', 'polaris', *arguments],
                              capture_output=True, text=True)

    def test_supported_targets_plan_without_backend_builds(self):
        targets = ['kernel', 'kernel-runtime', 'uefi', 'efi', 'initramfs', 'userspace', 'rootfs']
        result = self.cli('--target', *targets, '--profile', 'desktop/server', '--plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(set(plan['targets']), set(targets))
        self.assertEqual(plan['board'], 'polaris')
        self.assertEqual(plan['profiles'], ['server'])

    def test_server_profile_is_layered_and_unported_desktops_fail(self):
        plan = self.cli('--target', 'userspace', 'rootfs', '--profile', 'desktop/server', '--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual(json.loads(plan.stdout)['board'], 'polaris')
        for profile in ('desktop/kde', 'desktop/gnome', 'desktop/niri'):
            with self.subTest(profile=profile):
                result = self.cli('--target', 'rootfs', '--profile', profile)
                self.assertEqual(result.returncode, 2)
                self.assertIn('placeholder', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_server_overlay_selection_is_board_scoped(self):
        catalog = overlay_registry.catalog('polaris')
        self.assertEqual(catalog['profiles']['server']['kernel'], 'polaris-kernel')
        selected = {layer['reference']: layer['selected_by'] for layer in catalog['layers']}
        self.assertEqual(selected['polaris-kernel'], ['server'])
        self.assertEqual(selected['polaris-hardware'], ['server'])
        self.assertEqual(selected['polaris-server'], ['server'])
        board, _ = boot.boards()['polaris']
        layers = board_userspace.policy_layers(board, 'desktop/server')
        self.assertEqual(len(layers), 3)
        self.assertEqual(layers[0]['_file_overlays'], [
            ROOT/'overlays/services/powerkey/files',
            board/'overlays/polaris-hardware/files'
        ])
        self.assertEqual(layers[1], {})
        self.assertEqual(layers[2]['_file_overlays'], [
            board/'overlays/polaris-server/files'
        ])
        self.assertEqual(layers[0]['rootfs_artifacts'][0]['required_elf'],
                         ['usr/libexec/reimuks-powerkey'])

    def test_shared_power_key_state_machine(self):
        compiler = shutil.which('cc') or shutil.which('gcc')
        if not compiler:
            self.skipTest('Host C compiler unavailable')
        source = ROOT/'devices/polaris/tests/server_power_key.c'
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp)/'power-key-state-test'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=5)

    def test_firmware_repository_is_scoped_and_in_identity(self):
        baseline = load_distribution(DEFAULT)
        with patch.object(build, 'BOARD', 'polaris'):
            polaris = build.board_distribution(DEFAULT)
        with patch.object(build, 'BOARD', 'w202ds'):
            w202ds = build.board_distribution(DEFAULT)
        self.assertIn('non-free-firmware', polaris['components'])
        self.assertEqual(w202ds, baseline)
        self.assertNotEqual(identity(polaris), identity(w202ds))
        self.assertIn('non-free-firmware', sources_list(polaris, target=True))

    def test_initramfs_uses_only_polaris_helpers(self):
        board, config = boot.boards()['polaris']
        for destination, source in config['initramfs_policy_files'].items():
            self.assertTrue((board/source).is_file())
            self.assertNotIn('w202', destination + source)
        hook = board/'initramfs/rootfs/usr/lib/reimuks/initramfs.d/20-hardware'
        self.assertTrue(hook.stat().st_mode & 0o111)
        self.assertIn('reimuks.break=initramfs', hook.read_text())
        self.assertIn('bin/w202-usb-gadget', config['kernel_policy']['initramfs_forbidden_paths'])
        self.assertIn('overlays/polaris-hardware/files', config['initramfs_policy_files']['bin/polaris-usb-gadget'])


if __name__ == '__main__':
    unittest.main()

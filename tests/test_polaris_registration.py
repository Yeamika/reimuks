"""A scaffold must never fall through to another board's build inputs."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import boot


class PolarisRegistrationTest(unittest.TestCase):
    def test_source_and_boot_projects_are_distinct_and_resolve(self):
        board, config = boot.boards()['polaris']
        self.assertEqual(config['supported_targets'], [])
        self.assertNotEqual((board/'kernel').resolve(), (board/'boot').resolve())
        self.assertTrue((board/'kernel/config/kernel-source.json').is_file())
        self.assertTrue((board/config['boot_builder']).is_file())

    def test_all_cli_targets_fail_before_backend_import_or_build(self):
        for target in ('uefi', 'efi', 'initramfs', 'rootfs'):
            with self.subTest(target=target):
                result = subprocess.run([sys.executable, '-B', str(ROOT/'reimuks.py'),
                                         '--board', 'polaris', '--target', target],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('Polaris 7.1-rc1', result.stderr)
                self.assertNotIn('import matching kernel', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_direct_boot_dispatch_rejects_before_subprocess_or_workdir(self):
        board, config = boot.boards()['polaris']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(boot, 'REPO', root), patch.object(boot.subprocess, 'run') as run:
                for stage in ('all', 'uefi', 'efi'):
                    with self.assertRaisesRegex(ValueError, 'Polaris 7.1-rc1'):
                        boot.build_board('polaris', board, config, stage, root/'artifacts')
                run.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

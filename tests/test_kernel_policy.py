import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from pack import validate_kernel_config


class KernelPolicyTest(unittest.TestCase):
    def test_accepts_normal_initramfs_kernel(self):
        validate_kernel_config('''
CONFIG_CMDLINE="console=tty1 loglevel=4"
# CONFIG_CMDLINE_FORCE is not set
# CONFIG_W202DS_DIAG_RECOVERY is not set
''')

    def test_rejects_recovery_driver(self):
        with self.assertRaisesRegex(SystemExit, 'W202DS_DIAG_RECOVERY'):
            validate_kernel_config('CONFIG_W202DS_DIAG_RECOVERY=y\n')

    def test_rejects_recovery_module(self):
        with self.assertRaisesRegex(SystemExit, 'W202DS_DIAG_RECOVERY'):
            validate_kernel_config('CONFIG_W202DS_DIAG_RECOVERY=m\n')

    def test_rejects_diagnostic_initramfs_arguments(self):
        config = 'CONFIG_CMDLINE="console=tty1 rdinit=/w202diag w202ds_diag=M12"\n'
        with self.assertRaisesRegex(SystemExit, 'normal initramfs kernel'):
            validate_kernel_config(config)

    def test_rejects_other_forced_early_init(self):
        with self.assertRaisesRegex(SystemExit, 'normal initramfs kernel'):
            validate_kernel_config('CONFIG_CMDLINE="rdinit=/bin/sh"\n')


if __name__ == '__main__':
    unittest.main()

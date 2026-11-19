"""Keep the first Linux console available when selecting a systemd target."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'boot_bundle', Path(__file__).resolve().parents[1] / 'scripts/boot_bundle.py')
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


class BootOptionsTest(unittest.TestCase):
    def test_target_preserves_kernel_console_and_scanout_clock_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '.config'
            config.write_text('CONFIG_CMDLINE_FROM_BOOTLOADER=y\n'
                              'CONFIG_CMDLINE="console=tty1 loglevel=7 clk_ignore_unused"\n')
            self.assertEqual(BUNDLE.boot_options('systemd.unit=multi-user.target', config),
                             'console=tty1 loglevel=7 clk_ignore_unused systemd.unit=multi-user.target')

    def test_extend_does_not_duplicate_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '.config'
            config.write_text('CONFIG_CMDLINE_EXTEND=y\nCONFIG_CMDLINE="console=tty1"\n')
            self.assertEqual(BUNDLE.boot_options('systemd.unit=graphical.target', config),
                             'systemd.unit=graphical.target')

    def test_force_cannot_silently_ignore_selected_target(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '.config'
            config.write_text('CONFIG_CMDLINE_FORCE=y\nCONFIG_CMDLINE="console=tty1"\n')
            with self.assertRaises(ValueError):
                BUNDLE.boot_options('systemd.unit=multi-user.target', config)

    def test_optional_config_preserves_existing_callers_and_rejects_multiline(self):
        self.assertEqual(BUNDLE.boot_options('systemd.unit=multi-user.target'),
                         'systemd.unit=multi-user.target')
        for options in ('x\ny', 'x\ry', 'x' * 1024):
            with self.assertRaises(ValueError):
                BUNDLE.boot_options(options)


if __name__ == '__main__':
    unittest.main()

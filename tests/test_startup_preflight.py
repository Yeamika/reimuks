"""Regression checks for missing conditional startup helpers and login."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from startup_preflight import verify


class StartupPreflight(unittest.TestCase):
    def test_accidental_host_helper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'usr/libexec').mkdir(parents=True)
            elf = bytearray(64)
            elf[:6] = b'\x7fELF\x02\x01'
            elf[18] = 62  # x86_64
            (root/'usr/libexec/board-helper').write_bytes(elf)
            with self.assertRaisesRegex(ValueError, 'Expected ARM64 helper'):
                verify(root, 'server', lambda *args, **kwargs: None)

    def test_missing_conditional_helper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'usr/libexec').mkdir(parents=True)
            (root/'usr/libexec/display').write_text(
                '#!/bin/sh\nif test ! -d /sys/class/backlight/display; then\n'
                ' /usr/libexec/backlight-attach\nfi\n')
            def runner(root, command, **kwargs):
                if command[-1] == '/usr/libexec/backlight-attach':
                    self.assertFalse((root/command[-1].lstrip('/')).exists())
                    raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                verify(root, 'server', runner)

    def test_target_execution_required_and_failure_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def runner(root, command, **kwargs):
                calls.append(command)
                if command == ['/usr/bin/login', '--help']:
                    raise subprocess.CalledProcessError(127, command)
            with self.assertRaises(subprocess.CalledProcessError):
                verify(Path(directory), 'kde', runner)
            self.assertEqual(calls[-1], ['/usr/bin/login', '--help'])


if __name__ == '__main__':
    unittest.main()

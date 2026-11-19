import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServerHallPolicy(unittest.TestCase):
    def test_display_transitions_lost_events_and_failed_updates(self):
        compiler = shlex.split(os.environ.get('HOSTCC', 'cc'))
        if not shutil.which(compiler[0]):
            self.skipTest('Host C compiler unavailable; set HOSTCC')
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'test-server-hall'
            subprocess.run([*compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'devices/w202ds/overlays/w202ds-hall-overlay/tests/test-server-hall.c'),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()

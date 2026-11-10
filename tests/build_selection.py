"""Reject unsupported selections before downloads or output creation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SelectionTest(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable,str(ROOT/'reimuks.py'),*args],capture_output=True,text=True)

    def test_list(self):
        result=self.cli('--list-boards')
        self.assertEqual(result.returncode,0)
        self.assertIn('desktop/server, desktop/kde',result.stdout)

    def test_placeholders_do_not_start_build(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            output=Path(temp)/'must-not-exist'
            for profile in ['server','desktop/gnome','desktop/niri']:
                result=self.cli('--board','w202ds','--target','uefi','rootfs',
                                '--profile',profile,'--output',str(output))
                self.assertEqual(result.returncode,2)
                self.assertIn('placeholder',result.stderr)
                self.assertFalse(output.exists())

    def test_unknown_board_and_missing_output(self):
        self.assertEqual(self.cli('--board','unknown','--target','uefi').returncode,2)
        result=self.cli('--board','w202ds','--target','efi')
        self.assertEqual(result.returncode,2)
        self.assertIn('output',result.stderr)


if __name__ == '__main__': unittest.main()

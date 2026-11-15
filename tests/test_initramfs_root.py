"""Execute the initramfs root-selector shell against DT property fixtures."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UUID = '12345678-1234-5678-9abc-123456789abc'
OLD = 'abcdef01-2345-6789-abcd-0123456789ab'


class RootSelection(unittest.TestCase):
    def run_selector(self, canonical=None, legacy=None, cmdline=''):
        text = (ROOT/'initramfs/init').read_text()
        selector = text.split('# EFI writes a canonical UUID', 1)[1]
        selector = 'root=' + selector.split('root=', 1)[1]
        selector = selector.split('bootlog "root selector: $root"', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name, data in [('pj4edk2,root-partuuid', canonical), ('w202,root-partuuid', legacy)]:
                if data is not None:
                    (base/name).write_bytes(data)
            (base/'cmdline').write_text(cmdline)
            selector = selector.replace('/sys/firmware/devicetree/base/chosen/', str(base)+'/')
            selector = selector.replace('/proc/cmdline', str(base/'cmdline'))
            return subprocess.run(['/bin/sh'], input='rescue() { echo "$*" >&2; exit 42; }\n'+selector+'\nprintf "%s" "$root"\n', text=True, capture_output=True)

    def test_shared_property_and_legacy_loader(self):
        for new, old, expected in [(UUID.encode()+b'\0', None, UUID), (None, OLD.encode()+b'\0', OLD), (UUID.encode()+b'\0', OLD.encode()+b'\0', UUID)]:
            result = self.run_selector(new, old, 'root=PARTUUID='+OLD)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'PARTUUID='+expected)

    def test_malformed_canonical_does_not_silently_use_legacy(self):
        for data in [UUID.encode(), UUID.encode()+b'X', b'z'+UUID[1:].encode()+b'\0', UUID.replace('-', '_').encode()+b'\0']:
            result = self.run_selector(data, OLD.encode()+b'\0')
            self.assertEqual(result.returncode, 42)

    def test_command_line_fallback_and_missing_root(self):
        result = self.run_selector(cmdline='console=tty1 root=PARTUUID='+UUID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'PARTUUID='+UUID)
        self.assertEqual(self.run_selector().returncode, 42)


if __name__ == '__main__':
    unittest.main()

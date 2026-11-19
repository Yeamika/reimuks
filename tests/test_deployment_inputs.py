"""A private overlay must satisfy the board's runtime input contract."""
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import user_overlay


class DeploymentInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = {
            'schema': 1,
            'files': ['private/android/vendor/bin/loader', 'private/cmdline'],
            'directories': ['private/android'],
            'symlinks': {'private/firmware': '../firmware'},
            'contains': {'private/cmdline': ['modem=shutdown']},
        }
        self.private = [
            ('private/android', 'directory', ''),
            ('private/android/vendor/bin/loader', 'file', 'loader'),
            ('private/cmdline', 'file', 'bootmode=normal modem=shutdown'),
            ('private/firmware', 'symlink', '../firmware'),
        ]

    def archive(self, path, items):
        with tarfile.open(path, 'w:gz') as archive:
            for name, kind, value in items:
                info = tarfile.TarInfo(name)
                if kind == 'directory':
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif kind == 'symlink':
                    info.type = tarfile.SYMTYPE
                    info.linkname = value
                    archive.addfile(info)
                else:
                    data = value.encode()
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

    def merge(self):
        base = self.root / 'base.tar.gz'
        overlay = self.root / 'private.tar.gz'
        output = self.root / 'deployment.tar.gz'
        self.archive(base, [('usr/lib/reimuks/deployment-requirements.json',
                             'file', json.dumps(self.contract))])
        self.archive(overlay, self.private)
        user_overlay.merge(base, overlay, output)
        return output

    def test_complete_private_runtime_is_publishable(self):
        self.assertTrue(self.merge().is_file())

    def test_nv_only_overlay_cannot_publish_an_enabled_modem(self):
        self.private = [('private/nv/device.img', 'file', 'same device nv')]
        with self.assertRaisesRegex(ValueError, 'Missing deployment input'):
            self.merge()
        self.assertFalse((self.root / 'deployment.tar.gz').exists())

    def test_empty_binary_is_rejected(self):
        self.private[1] = (self.private[1][0], 'file', '')
        with self.assertRaisesRegex(ValueError, 'nonempty regular file'):
            self.merge()

    def test_wrong_firmware_link_is_rejected(self):
        self.private[-1] = ('private/firmware', 'symlink', '/dev/mmcblk0')
        with self.assertRaisesRegex(ValueError, 'Unexpected deployment symlink'):
            self.merge()

    def test_wrong_boot_token_is_rejected(self):
        self.private[2] = ('private/cmdline', 'file', 'modem=running')
        with self.assertRaisesRegex(ValueError, 'required deployment token'):
            self.merge()

    def test_private_overlay_cannot_weaken_base_contract(self):
        self.private.append(('usr/lib/reimuks/deployment-requirements.json',
                             'file', '{"schema":1}'))
        with self.assertRaisesRegex(ValueError, 'must come from the base image'):
            self.merge()

    def test_unsafe_contract_path_is_rejected(self):
        self.contract['files'] = ['../outside']
        with self.assertRaisesRegex(ValueError, 'Unsafe deployment requirement'):
            self.merge()

    def test_boards_without_a_contract_keep_generic_merge(self):
        base = self.root / 'base.tar.gz'
        overlay = self.root / 'private.tar.gz'
        self.archive(base, [('etc/example', 'file', 'base')])
        self.archive(overlay, [('etc/example', 'file', 'user')])
        user_overlay.merge(base, overlay, self.root / 'deployment.tar.gz')
        with tarfile.open(self.root / 'deployment.tar.gz') as archive:
            self.assertEqual(archive.extractfile('etc/example').read(), b'user')


if __name__ == '__main__':
    unittest.main()

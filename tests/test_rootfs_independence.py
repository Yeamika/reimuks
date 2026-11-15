"""Rootfs packaging must work without imported kernel artifacts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pack


class RootfsIndependence(unittest.TestCase):
    def test_pack_without_kernel_manifest_or_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'kde/rootfs'
            work = base / 'kde/work'
            output = base / 'artifacts'
            (root / 'etc').mkdir(parents=True)
            (root / 'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
            work.mkdir()
            (work / 'configured').touch()
            (work / 'dpkg-audit.txt').touch()
            (work / 'packages.tsv').write_text('')

            def archive(*args):
                script = (work / 'archive.sh').read_text()
                self.assertNotIn('depmod', script)
                self.assertIn('--exclude=./usr/lib/modules', script)
                self.assertIn('--exclude=./boot/Image-*', script)
                (output / 'desktop-kde-arm64-rootfs.tar.gz.part').write_bytes(b'archive')

            with patch.object(pack.backend, 'kernel_directory', side_effect=AssertionError('kernel dependency')), \
                 patch.object(pack.backend, 'check_rootfs'), \
                 patch.object(pack.backend, 'configure_locale'), \
                 patch.object(pack.backend, 'profile_directory', return_value=base / 'kde'), \
                 patch.object(pack.backend, 'distribution_build', return_value=base), \
                 patch.object(pack.backend, 'artifact_directory', return_value=output), \
                 patch.object(pack, 'install_board_rootfs') as install, \
                 patch.object(pack, 'prepare_board_rootfs'), \
                 patch.object(pack, 'verify_startup', return_value={'hardware_tested': False}), \
                 patch.object(pack, 'proot', side_effect=archive):
                pack.rootfs('kde')
            install.assert_called_once_with(root, 'kde', pack.backend.board_directory())
            manifest = json.loads((output / 'kde.manifest.json').read_text())
            self.assertTrue(manifest['kernel_independent'])
            self.assertNotIn('kernel', manifest)
            self.assertFalse((output / 'desktop-kde-arm64-rootfs.tar.gz.part').exists())


if __name__ == '__main__':
    unittest.main()

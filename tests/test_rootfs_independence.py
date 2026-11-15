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
            root.chmod(0o775)
            (root / 'etc').chmod(0o775)
            (root / 'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
            work.mkdir()
            (work / 'configured').touch()
            (work / 'clean-rootfs-v1').touch()
            (work / 'dpkg-audit.txt').touch()
            (work / 'packages.tsv').write_text('')
            (work / 'fakeroot.state').touch()

            def archive(*args):
                staged = work/'package-rootfs'
                self.assertEqual(staged.stat().st_mode & 0o777, 0o755)
                self.assertEqual((staged/'etc').stat().st_mode & 0o777, 0o755)
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
                 patch.object(pack, 'install_layer_packages', return_value={}) as install, \
                 patch.object(pack, 'verify_startup', return_value={'hardware_tested': False}), \
                 patch.object(pack, 'compress_rootfs', side_effect=archive):
                pack.rootfs('kde')
                # A removed integration file from the previous pack must not
                # survive in either the configured source or the next package.
                stale = work/'package-rootfs/obsolete-board-file'
                stale.parent.mkdir(parents=True)
                stale.write_text('previous package')
                pack.rootfs('kde')
                self.assertFalse(stale.exists())
            self.assertEqual(install.call_count, 2)
            self.assertEqual(install.call_args.args, (work/'package-rootfs', work, work/'package-fakeroot.state', 'kde'))
            self.assertFalse((root/'usr/lib/reimuks/distribution.json').exists())
            manifest = json.loads((output / 'kde.manifest.json').read_text())
            self.assertTrue(manifest['kernel_independent'])
            self.assertNotIn('kernel', manifest)
            self.assertFalse((output / 'desktop-kde-arm64-rootfs.tar.gz.part').exists())


if __name__ == '__main__':
    unittest.main()

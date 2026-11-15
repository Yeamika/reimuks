"""Repeated builds replace fixed outputs and retain independent boot stages."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import boot
import build
import pack


class BootOutputTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root/'artifacts'
        self.work = self.root/'work'

    def deliver(self, stage, files, directory=None):
        directory = directory or self.work
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for name, data in files.items():
            file = directory/name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
            artifacts[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        record = {'board': 'test', 'stage': stage, 'artifacts': artifacts}
        (directory/'firmware-manifest.json').write_text(json.dumps(record))

    def test_partial_build_retains_other_stage_and_repeated_build_has_no_history(self):
        self.deliver('all', {'firmware.img': b'firmware', 'app.efi': b'old app'})
        boot.publish(self.work, self.output)
        for data in (b'new app', b'latest app'):
            self.deliver('efi', {'app.efi': data})
            boot.publish(self.work, self.output)
        self.assertEqual((self.output/'firmware.img').read_bytes(), b'firmware')
        self.assertEqual((self.output/'app.efi').read_bytes(), b'latest app')
        record = json.loads((self.output/'firmware-manifest.json').read_text())
        self.assertEqual(len(record['builds']), 2)
        self.assertEqual(set(record['builds'][0]['artifacts']), {'firmware.img'})
        self.assertEqual(set(boot.verify(self.output, 'firmware-manifest.json')),
                         {'firmware.img', 'app.efi'})

    def test_full_rebuild_removes_obsolete_artifacts(self):
        self.deliver('all', {'old.img': b'old'})
        boot.publish(self.work, self.output)
        self.deliver('all', {'new.img': b'new'})
        boot.publish(self.work, self.output)
        self.assertFalse((self.output/'old.img').exists())
        self.assertEqual((self.output/'new.img').read_bytes(), b'new')

    def test_corrupt_build_cannot_replace_previous_delivery(self):
        self.deliver('uefi', {'firmware.img': b'old'})
        boot.publish(self.work, self.output)
        self.deliver('uefi', {'firmware.img': b'new'})
        (self.work/'firmware.img').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            boot.publish(self.work, self.output)
        self.assertEqual((self.output/'firmware.img').read_bytes(), b'old')
        boot.verify(self.output, 'firmware-manifest.json')

    def test_build_reuses_one_work_directory_and_removes_it_after_success(self):
        board = self.root/'devices/test'
        (board/'boot').mkdir(parents=True)
        (board/'boot/build.py').touch()
        work = self.root/'build/boot/test'
        calls = []
        def compile(argv, check):
            directory = Path(argv[argv.index('--output')+1])
            calls.append(directory)
            self.assertEqual(directory, work)
            self.assertFalse(directory.exists())
            self.deliver('uefi', {'firmware.img': str(len(calls)).encode()}, directory)
        with patch.object(boot, 'REPO', self.root), patch.object(boot.subprocess, 'run', compile):
            for _ in range(2):
                boot.build_board('test', board, {'boot_builder': 'boot/build.py'},
                                 'uefi', self.output)
                self.assertFalse(work.exists())
        self.assertEqual(calls, [work, work])
        self.assertEqual((self.output/'firmware.img').read_bytes(), b'2')

    def test_failed_build_preserves_published_files_and_fixed_failure_directory(self):
        board = self.root/'devices/test'
        (board/'boot').mkdir(parents=True)
        (board/'boot/build.py').touch()
        self.deliver('uefi', {'firmware.img': b'old'})
        boot.publish(self.work, self.output)
        work = self.root/'build/boot/test'
        def fail(argv, check):
            work.mkdir()
            (work/'error.log').write_text('build failed')
            raise subprocess.CalledProcessError(1, argv)
        with patch.object(boot, 'REPO', self.root), patch.object(boot.subprocess, 'run', fail):
            with self.assertRaises(subprocess.CalledProcessError):
                boot.build_board('test', board, {'boot_builder': 'boot/build.py'},
                                 'uefi', self.output)
        self.assertTrue((work/'error.log').is_file())
        self.assertEqual((self.output/'firmware.img').read_bytes(), b'old')


class InitramfsOutputTest(unittest.TestCase):
    def test_repack_replaces_work_tree_without_keeping_old_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            kernel = directory/'kernel'
            (kernel/'modules/test-release').mkdir(parents=True)
            (kernel/'manifest.json').write_text(json.dumps({
                'release': 'test-release', 'image_sha256': 'example'}))
            (kernel/'config').write_text('# CONFIG_W202DS_DIAG_RECOVERY is not set\n')
            server = directory/'initramfs-tools'
            for name in ('bin/busybox', 'sbin/blkid', 'lib/aarch64-linux-gnu/libblkid.so.1',
                         'lib/aarch64-linux-gnu/libc.so.6', 'lib/aarch64-linux-gnu/ld-linux-aarch64.so.1'):
                file = server/'root/usr'/name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'fixture')
            output = directory/'artifacts'
            root = directory/'initramfs/root'
            with patch.object(pack, 'BUILD', directory), patch.object(build, 'BUILD', directory), \
                    patch.object(build, 'check_rootfs'), patch.object(pack, 'install_board_initramfs'), \
                    patch.object(pack, 'proot'), patch.object(pack, 'legacy_lz4', lambda data: data):
                pack.initramfs()
                (root/'obsolete-file').touch()
                pack.initramfs()
            self.assertFalse((root/'obsolete-file').exists())
            self.assertNotIn(b'obsolete-file', (output/'initramfs-arm64.cpio.lz4').read_bytes())
            self.assertEqual(set(directory.glob('initramfs*')), {directory/'initramfs', directory/'initramfs-tools'})


if __name__ == '__main__':
    unittest.main()

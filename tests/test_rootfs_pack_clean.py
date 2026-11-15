"""Private overlays must not contaminate base packages or follow archive links."""
from pathlib import Path
import io
import gzip
import subprocess
import os
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import pack as rootfs_pack
import user_overlay
from verify import verify_base_metadata
from tree_cleanup import remove_tree
from board_userspace import install_template
from fakeroot_state import relocate


class CleanPackaging(unittest.TestCase):
    def test_password_overlay_preserves_new_base_service_accounts(self):
        base=b'root:!:1:0:99999:7:::\nreimuks:!:1:0:99999:7:::\nservice:!*:1:0:99999:7:::\n'
        private=b'root:$6$example:1:0:99999:7:::\nreimuks:$6$example:1:0:99999:7:::\n'
        result=user_overlay.merge_passwords(base,private)
        self.assertIn(b'service:!*:',result)
        self.assertIn(b'root:$6$example:',result)
        self.assertEqual(len(result.splitlines()),3)

    def test_host_python_caches_in_source_templates_never_enter_rootfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';root=Path(tmp)/'root';root.mkdir()
            cache=source/'usr/libexec/__pycache__';cache.mkdir(parents=True)
            (cache/'obsolete.cpython-312.pyc').write_bytes(b'old compiled code')
            (source/'usr/libexec/old.pyc').write_bytes(b'old compiled code')
            (source/'usr/libexec/current').write_text('current runtime')
            install_template(root,source)
            self.assertFalse((root/'usr/libexec/__pycache__').exists())
            self.assertFalse((root/'usr/libexec/old.pyc').exists())
            self.assertTrue((root/'usr/libexec/current').is_file())

    def test_cleanup_handles_restricted_directories_without_following_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'staging';outside=Path(tmp)/'outside';outside.mkdir()
            (outside/'keep').write_text('retained')
            restricted=root/'host-rootfs/nested';restricted.mkdir(parents=True)
            (restricted/'link').symlink_to(outside,target_is_directory=True)
            restricted.chmod(0);restricted.parent.chmod(0)
            remove_tree(root)
            self.assertFalse(root.exists())
            self.assertEqual((outside/'keep').read_text(),'retained')

    def test_host_compression_stream_and_failed_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'image.gz.part'
            rootfs_pack.compress_stream([sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'payload')"],os.environ,output)
            self.assertEqual(gzip.decompress(output.read_bytes()),b'payload')
            with self.assertRaises(subprocess.CalledProcessError):
                rootfs_pack.compress_stream([sys.executable,'-c','raise SystemExit(7)'],os.environ,output)

    def test_templates_preserve_package_directories_and_strip_source_group_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';source=Path(tmp)/'source'
            (root/'etc/polkit-1/rules.d').mkdir(parents=True)
            (root/'etc/polkit-1/rules.d').chmod(0o750)
            (source/'etc/polkit-1/rules.d').mkdir(parents=True)
            f=source/'etc/polkit-1/rules.d/example';f.write_text('policy');f.chmod(0o664)
            (source/'etc/polkit-1/rules.d').chmod(0o775)
            install_template(root,source)
            self.assertEqual((root/'etc/polkit-1/rules.d').stat().st_mode & 0o777,0o750)
            self.assertEqual((root/'etc/polkit-1/rules.d/example').stat().st_mode & 0o777,0o644)

    def test_relocate_keeps_package_ownership_on_new_inodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';copy=Path(tmp)/'copy';root.mkdir();copy.mkdir()
            (root/'shadow').touch();(copy/'shadow').touch()
            info=(root/'shadow').stat();new=(copy/'shadow').stat()
            source=Path(tmp)/'state';dest=Path(tmp)/'copied-state'
            source.write_text(f'dev={info.st_dev:x},ino={info.st_ino},mode=100640,uid=0,gid=42,nlink=1,rdev=0\n')
            relocate(source,dest,root,copy)
            self.assertIn(f'ino={new.st_ino},mode=100640,uid=0,gid=42',dest.read_text())

    def test_base_verifier_rejects_private_keys_permissions_and_old_residue(self):
        passwords='root:!:0:0:0:0:::\nreimuks:!:0:0:0:0:::\n'
        info=tarfile.TarInfo('usr/bin');info.type=tarfile.DIRTYPE;info.mode=0o755
        verify_base_metadata({'usr/bin':info}, passwords)
        info.mode=0o775
        with self.assertRaisesRegex(AssertionError,'Writable'):
            verify_base_metadata({'usr/bin':info}, passwords)
        for path in ['etc/ssh/ssh_host_ed25519_key','state/cache','etc/shadow-']:
            with self.assertRaises(AssertionError):
                verify_base_metadata({path:tarfile.TarInfo(path)}, passwords)
        for password in ('$6$hash','!$6$hash'):
            with self.assertRaisesRegex(AssertionError,'bare locked'):
                verify_base_metadata({}, passwords.replace('root:!:', 'root:'+password+':'))

    def test_legacy_contaminated_staging_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);work=base/'work';work.mkdir()
            (work/'configured').touch();(work/'dpkg-audit.txt').touch()
            with patch.object(rootfs_pack.backend,'check_rootfs'),patch.object(rootfs_pack.backend,'profile_directory',return_value=base):
                with self.assertRaisesRegex(SystemExit,'reassemble'):
                    rootfs_pack.rootfs('kde')

    def test_private_package_merge_preserves_base_and_account_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'private';source.mkdir()
            (source/'home/reimuks/.ssh').mkdir(parents=True)
            key=source/'home/reimuks/.ssh/authorized_keys';key.write_text('test key');key.chmod(0o600)
            original=base/'base.tar.gz'
            with tarfile.open(original,'w:gz') as tf:
                info=tarfile.TarInfo('etc/passwd');data=b'reimuks:x:1234:2345::/home/reimuks:/bin/sh\n';info.size=len(data);tf.addfile(info,io.BytesIO(data))
                info=tarfile.TarInfo('home/reimuks');info.type=tarfile.DIRTYPE;info.mode=0o750;info.uid=1234;info.gid=2345;tf.addfile(info)
            overlay=base/'private.tar.gz';result=base/'deployment.tar.gz'
            before=original.read_bytes();user_overlay.pack(source,overlay);user_overlay.merge(original,overlay,result)
            self.assertEqual(before,original.read_bytes())
            with tarfile.open(result) as tf:
                info=tf.getmember('home/reimuks/.ssh/authorized_keys')
                self.assertEqual((info.mode,info.uid,info.gid),(0o600,1234,2345))
                self.assertEqual(tf.getmember('home/reimuks').mode,0o750)
            self.assertEqual(overlay.stat().st_mode & 0o777,0o600)

    def test_overlay_cannot_write_through_base_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);original=base/'base.tar.gz';overlay=base/'overlay.tar.gz'
            with tarfile.open(original,'w:gz') as tf:
                info=tarfile.TarInfo('alias');info.type=tarfile.SYMTYPE;info.linkname='etc';tf.addfile(info)
            with tarfile.open(overlay,'w:gz') as tf:
                info=tarfile.TarInfo('alias/file');tf.addfile(info,io.BytesIO())
            with self.assertRaisesRegex(ValueError,'non-directory'):
                user_overlay.merge(original,overlay,base/'deployment.tar.gz')


if __name__ == '__main__':
    unittest.main()

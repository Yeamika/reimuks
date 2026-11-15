"""Host-staged overlays must not inherit metadata from reused package inodes."""
from pathlib import Path
import os
import stat
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from fakeroot_state import snapshot, reconcile, relocate


class FakerootState(unittest.TestCase):
    def test_preserves_package_owners_and_discards_stale_or_changed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'root';root.mkdir()
            existing=root/'owned';existing.write_text('package data')
            changed=root/'changed';changed.write_text('before')
            config=root/'.config';config.mkdir()
            node=root/'fake-device';node.touch()
            before=snapshot(root)
            def record(path, mode=None):
                info=path.stat()
                return f'dev={info.st_dev:x},ino={info.st_ino},mode={mode or info.st_mode:o},uid=123,gid=456,nlink=1,rdev=0\n'
            source=base/'state'
            source.write_text(record(existing)+record(changed)+record(config,stat.S_IFREG|0o644)+record(node,stat.S_IFCHR|0o600)+record(root))
            changed.write_text('host replacement')
            (root/'new').touch()  # Parent directory remains package-owned.
            dest=base/'archive-state'
            reconcile(source,dest,root,before)
            result=dest.read_text()
            self.assertIn(record(existing),result)
            self.assertIn(record(root),result)
            self.assertIn(record(node,stat.S_IFCHR|0o600),result)
            self.assertIn(record(changed),result)
            self.assertNotIn(record(config,stat.S_IFREG|0o644),result)


if __name__=='__main__':unittest.main()

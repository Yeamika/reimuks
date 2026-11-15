"""ESP image creation verifies FAT readback and preserves prior output on failure."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import esp

TOOLS=Path(__file__).resolve().parents[1]/'build/esp-tools/bin'


@unittest.skipUnless((TOOLS/'mcopy').exists() and (TOOLS/'mkfs.fat').exists(), 'native ESP test tools not prepared')
class EspImageTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.tree=self.base/'tree'
        app=self.tree/'EFI/BOOT/BOOTAA64.EFI'
        app.parent.mkdir(parents=True)
        app.write_bytes(b'ESP container test payload')
        self.output=self.base/'esp.img'

    def test_real_fat_image_readback(self):
        record=esp.create(self.tree,self.output,64,TOOLS)
        self.assertEqual(self.output.stat().st_size,64*1024**2)
        self.assertEqual(record['sha256'],esp.digest(self.output))
        self.assertEqual(record,json.loads(self.output.with_suffix('.img.json').read_text()))
        self.assertEqual(set(record['files']),{'EFI/BOOT/BOOTAA64.EFI'})

    def test_failed_copy_preserves_previous_image(self):
        self.output.write_bytes(b'previous verified image')
        original=esp.subprocess.run
        def fail_copy(command,**kwargs):
            if Path(command[0]).name=='mcopy':
                raise subprocess.CalledProcessError(1,command)
            return original(command,**kwargs)
        with patch.object(esp.subprocess,'run',fail_copy):
            with self.assertRaises(subprocess.CalledProcessError):
                esp.create(self.tree,self.output,64,TOOLS)
        self.assertEqual(self.output.read_bytes(),b'previous verified image')
        self.assertEqual(list(self.base.glob('.esp.img-*')),[])

    def test_case_collisions_and_symlinks_rejected(self):
        (self.tree/'efi').mkdir()
        with self.assertRaisesRegex(ValueError,'collision'):
            esp.create(self.tree,self.output,64,TOOLS)
        (self.tree/'efi').rmdir()
        (self.tree/'link').symlink_to('EFI')
        with self.assertRaisesRegex(ValueError,'links'):
            esp.create(self.tree,self.output,64,TOOLS)
        self.assertFalse(self.output.exists())


if __name__=='__main__': unittest.main()

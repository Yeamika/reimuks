"""REIMUKS checks delivered artifact identity without knowing board layouts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from verify_boot import verify


class BootArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.name = 'board/firmware.img'
        self.path = self.directory/self.name
        self.path.parent.mkdir()
        self.path.write_bytes(b'opaque board output')
        self.record = {'stage': 'uefi', 'artifacts': {self.name: {
            'bytes': self.path.stat().st_size,
            'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()}}}
        self.save()

    def save(self):
        (self.directory/'manifest.json').write_text(json.dumps(self.record))

    def test_uefi_output_is_opaque_to_reimuks(self):
        self.assertEqual(verify(self.directory, 'manifest.json'), self.record['artifacts'])

    def test_changed_artifact_is_rejected(self):
        self.path.write_bytes(b'Opaque board output')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            verify(self.directory, 'manifest.json')

    def test_artifact_cannot_escape_collection_directory(self):
        self.record['artifacts'] = {'../outside.img': self.record['artifacts'][self.name]}
        self.save()
        with self.assertRaisesRegex(ValueError, 'escapes output directory'):
            verify(self.directory, 'manifest.json')

    def test_empty_manifest_is_rejected(self):
        self.record['artifacts'] = {}
        self.save()
        with self.assertRaisesRegex(ValueError, 'no boot artifacts'):
            verify(self.directory, 'manifest.json')


if __name__ == '__main__':
    unittest.main()

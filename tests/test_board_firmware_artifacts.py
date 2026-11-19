"""Regression: mandatory board firmware cannot disappear from a rootfs package."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from board_userspace import install_component, validate_rootfs_inputs
import pack


class FirmwareArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.userspace = self.base/'component'
        (self.userspace/'rootfs').mkdir(parents=True)
        self.payload = self.userspace/'stage/usr/lib/firmware/controller.bin'
        self.payload.parent.mkdir(parents=True)
        self.payload.write_bytes(b'matching controller firmware')
        self.name = 'usr/lib/firmware/controller.bin'
        self.digest = hashlib.sha256(self.payload.read_bytes()).hexdigest()
        self.data = {'schema':1, 'rootfs':'stage', 'required':[self.name],
                     'required_sha256':{self.name:self.digest}}
        self.root = self.base/'target'
        self.root.mkdir()
        mock = patch('board_userspace.component', return_value=self.userspace)
        mock.start()
        self.addCleanup(mock.stop)

    def install(self):
        (self.userspace/'artifacts.json').write_text(json.dumps(self.data))
        install_component(self.root, self.base, 'test-controller')

    def test_installed_firmware_has_target_hash_receipt(self):
        self.install()
        self.assertEqual((self.root/self.name).read_bytes(), self.payload.read_bytes())
        receipt = self.root/'usr/lib/reimuks/firmware/test-controller.sha256'
        self.assertEqual(receipt.read_text(), self.digest+'  '+self.name+'\n')

    def test_missing_firmware_stops_packaging(self):
        self.payload.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing test-controller'):
            self.install()

    def test_wrong_firmware_stops_packaging_before_install(self):
        self.payload.write_bytes(b'different controller')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.install()
        self.assertFalse((self.root/self.name).exists())

    def test_missing_board_firmware_fails_all_desktops_before_install(self):
        (self.userspace/'artifacts.json').write_text(json.dumps(self.data))
        self.payload.unlink()
        with patch('board_userspace.policy_layers', return_value=[{'components':['test-controller']}]):
            for profile in ('server', 'gnome', 'kde'):
                with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'Missing test-controller'):
                    validate_rootfs_inputs(self.base, profile)
        self.assertFalse((self.root/self.name).exists())

    def test_board_validation_precedes_distribution_access(self):
        with patch.object(pack, 'validate_board_inputs', side_effect=ValueError('missing firmware')), \
             patch.object(pack.backend, 'check_rootfs') as distribution:
            with self.assertRaisesRegex(ValueError, 'missing firmware'):
                pack.rootfs('gnome')
            distribution.assert_not_called()

    def test_hash_cannot_refer_to_an_undeclared_file(self):
        self.data['required'] = []
        with self.assertRaisesRegex(ValueError, 'Invalid required artifact hash'):
            self.install()


if __name__ == '__main__':
    unittest.main()

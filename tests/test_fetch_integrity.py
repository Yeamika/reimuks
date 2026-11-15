"""Incomplete or stale package caches must not produce partial rootfs trees."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import build
import parallel_fetch


class FetchIntegrityTest(unittest.TestCase):
    def test_parallel_fetch_can_match_standard_desktop_recommendations(self):
        with patch.object(parallel_fetch.subprocess, 'check_output', return_value='') as plan:
            parallel_fetch.prefetch(Path('.'), ['kde-standard'], install_recommends=True)
            self.assertIn('--install-recommends', plan.call_args.args[0])
            self.assertNotIn('--no-install-recommends', plan.call_args.args[0])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.state = self.base/'apt-kde'
        (self.state/'archives').mkdir(parents=True)
        self.package = self.state/'archives/example.deb'
        self.package.write_bytes(b'authenticated archive')
        self.receipt = {
            'distribution': build.identity(build.DISTRIBUTION),
            'profile': build.resolve_profile('kde', build.DISTRIBUTION),
            'archives': {self.package.name: hashlib.sha256(self.package.read_bytes()).hexdigest()}}

    def save(self):
        (self.state/'fetch-complete.json').write_text(json.dumps(self.receipt))

    def rejected(self, message):
        with patch.object(build, 'profile_directory', return_value=self.base/'kde'):
            with self.assertRaisesRegex(SystemExit, message):
                build.assemble('kde', self.state)
        self.assertFalse((self.base/'kde').exists())

    def test_parallel_fetch_accepts_sha256_only_repository_records(self):
        data = self.package.read_bytes()
        plan = "'https://packages.example/example.deb' example.deb %d\n" % len(data)
        metadata = 'Filename: pool/example.deb\nSHA256: '+hashlib.sha256(data).hexdigest()+'\n'
        with patch.object(parallel_fetch.subprocess, 'check_output', side_effect=[plan, metadata]), \
                patch.object(parallel_fetch.subprocess, 'run') as download:
            parallel_fetch.prefetch(self.state, ['example'])
            download.assert_not_called()
        self.package.write_bytes(b'corrupted')
        with patch.object(parallel_fetch.subprocess, 'check_output', side_effect=[plan, metadata]), \
                patch.object(parallel_fetch.subprocess, 'run'):
            with self.assertRaises((ValueError, FileNotFoundError)):
                parallel_fetch.prefetch(self.state, ['example'])

    def test_incomplete_download(self):
        self.rejected('fetch is incomplete')

    def test_profile_changed(self):
        self.receipt['profile'] = {}
        self.save()
        self.rejected('selection changed')

    def test_archive_corrupted(self):
        self.save()
        self.package.write_bytes(b'corrupt')
        self.rejected('changed or is missing')

    def test_unrecorded_archive(self):
        self.save()
        (self.state/'archives/unexpected.deb').touch()
        self.rejected('cache changed')

    def test_package_selection_refresh_keeps_cache_and_invalidates_receipt(self):
        self.save()
        marker = self.state/'distribution.json'
        marker.write_text(json.dumps({'id': 'previous-selection'}))
        build.bind_distribution(self.state, refresh_cache=True)
        self.assertTrue(self.package.is_file())
        self.assertFalse((self.state/'fetch-complete.json').exists())
        self.assertEqual(json.loads(marker.read_text()), build.identity(build.DISTRIBUTION))

    def test_configured_rootfs_identity_remains_strict(self):
        marker = self.state/'distribution.json'
        marker.write_text(json.dumps({'id': 'previous-selection'}))
        with self.assertRaisesRegex(ValueError, 'fresh rootfs'):
            build.bind_distribution(self.state)


if __name__ == '__main__':
    unittest.main()

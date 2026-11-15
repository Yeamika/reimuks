"""Optional applications stay outside the base selection and retain APT semantics."""
from pathlib import Path
import hashlib
import json
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import addons
import apt_selection
import build


class ApplicationBundle(unittest.TestCase):
    def test_selects_solver_versions_and_ignores_other_cached_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);(state/'archives').mkdir()
            for name in ('app_1.deb','app_2.deb','unrelated.deb'):(state/'archives'/name).touch()
            def output(command,**kwargs):
                if command[0]=='apt-get':return 'Inst app (2 stable [arm64])\n'
                name=Path(command[2]).name
                version='2' if name=='app_2.deb' else '1'
                package='unrelated' if name=='unrelated.deb' else 'app'
                return f'Package: {package}\nVersion: {version}\nArchitecture: arm64\n'
            with patch.object(apt_selection.subprocess,'check_output',side_effect=output):
                result=apt_selection.selected_archives(state,['app'])
            self.assertEqual(result,[state/'archives/app_2.deb'])

    def test_missing_dependency_archive_fails_before_packaging(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(apt_selection.subprocess,'check_output',return_value='Inst dependency (1 stable [arm64])\n'):
            with self.assertRaisesRegex(ValueError,'Missing selected'):
                apt_selection.selected_archives(Path(tmp),['app'])

    def test_bundle_contains_offline_installer_dependencies_and_chrome_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);package=state/'app.deb';package.write_bytes(b'package payload')
            receipt={'distribution':addons.identity(build.DISTRIBUTION),'archives':{package.name:hashlib.sha256(package.read_bytes()).hexdigest()}}
            (state/'fetch-complete.json').write_text(json.dumps(receipt))
            output=state/'bundle.tar.gz'
            with patch.object(addons,'selected_archives',return_value=[package]):
                result=addons.pack('kde',state,output)
            self.assertIn('google-chrome-stable',result['applications'])
            with tarfile.open(output) as archive:
                installer=archive.extractfile('install.sh').read().decode()
                self.assertIn('--no-download',installer)
                self.assertIn('apt-get',installer)
                self.assertEqual(archive.extractfile('packages/app.deb').read(),b'package payload')
                self.assertIn('rootfs/usr/bin/reimuks-chrome',archive.getnames())
                self.assertIn('SHA256SUMS',archive.getnames())

    def test_changed_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);package=state/'app.deb';package.write_bytes(b'changed')
            receipt={'distribution':addons.identity(build.DISTRIBUTION),'archives':{package.name:'0'*64}}
            (state/'fetch-complete.json').write_text(json.dumps(receipt))
            with patch.object(addons,'selected_archives',return_value=[package]):
                with self.assertRaisesRegex(ValueError,'authenticated'):
                    addons.pack('kde',state,state/'bundle.tar.gz')
            self.assertFalse((state/'bundle.tar.gz').exists())

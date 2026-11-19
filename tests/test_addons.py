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
    def test_board_base_contract_does_not_require_optional_browser(self):
        from board_userspace import verification_policy
        for policy in verification_policy(Path(__file__).resolve().parents[1]/'devices/w202ds','kde'):
            self.assertNotIn('usr/bin/reimuks-chrome',policy.get('files', []))

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


class ApplicationSources(unittest.TestCase):
    def configure(self, root):
        namespace = {'__name__': 'test_app_configuration'}
        exec(addons.CONFIGURE, namespace)
        namespace['configure'](root)

    def test_upgrade_removes_only_generated_duplicate_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = root/'etc/apt/sources.list.d'
            sources.mkdir(parents=True)
            (sources/'reimuks-apps.list').write_text('deb [arch=arm64 signed-by=/usr/share/keyrings/reimuks-microsoft.asc] https://packages.microsoft.com/repos/code stable main\n')
            generated = sources/'vscode.sources'
            generated.write_text('### THIS FILE IS AUTOMATICALLY CONFIGURED ###\nTypes: deb\nURIs: https://packages.microsoft.com/repos/code\nSuites: stable\nComponents: main\nSigned-By: /usr/share/keyrings/microsoft.gpg\n')
            user = sources/'other.sources'
            user.write_text('Types: deb\nURIs: https://example.org/packages\n')
            self.configure(root)
            self.assertFalse(generated.exists())
            self.assertTrue(user.exists())
            self.configure(root)

    def test_user_repository_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = root/'etc/apt/sources.list.d'
            sources.mkdir(parents=True)
            (sources/'reimuks-apps.list').write_text('deb https://packages.microsoft.com/repos/code stable main\n')
            user = sources/'vscode.sources'
            user.write_text('Types: deb\nURIs: https://packages.microsoft.com/repos/code\nSigned-By: /usr/share/keyrings/owner.asc\n')
            self.configure(root)
            self.assertTrue(user.exists())

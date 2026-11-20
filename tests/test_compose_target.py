"""Verify target assembly consumes published bytes and preserves layer boundaries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1]/'reimuks.py'


class ComposeTarget(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.pool = self.root/'pool'
        self.target = self.root/'recipe.json'
        self.output = self.root/'out'/'device.tar'

    def layer(self, name, filename, content, **metadata):
        directory = self.pool/name
        directory.mkdir(parents=True)
        path = directory/filename
        path.write_bytes(content)
        (directory/'package.json').write_text(json.dumps(dict(
            schema=1, id=name, architecture='arm64',
            files={filename: hashlib.sha256(content).hexdigest()}, **metadata)))
        return path

    def recipe(self, *layers, **metadata):
        self.target.write_text(json.dumps(dict(
            schema=1, id='workstation', architecture='arm64', board='w202ds',
            distribution='debian/trixie', layers=[f'{name}/package.json' for name in layers], **metadata)))

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(ENTRY), '--target', 'compose',
                               '--compose-config', str(self.target), '--package-root', str(self.pool),
                               '--output', str(self.output), *arguments], text=True, capture_output=True)

    def test_plan_and_assemble_only_the_selected_packages(self):
        kernel = self.layer('kernel', 'linux.tar.gz', b'reused kernel', board='w202ds')
        self.layer('base', 'distribution.tar.gz', b'prebuilt rootfs', distribution='debian/trixie')
        self.layer('demo', 'local.deb', b'overlay package', requires=['base'])
        self.layer('unused', 'unused.tar.gz', b'unselected')
        self.recipe('kernel', 'base', 'demo')
        plan = self.cli('--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual([item['id'] for item in json.loads(plan.stdout)['layers']], ['kernel', 'base', 'demo'])
        self.assertFalse(self.output.parent.exists())
        result = self.cli('--board', 'w202ds')
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.output) as bundle:
            self.assertEqual(bundle.getnames(), [
                'manifest.json', 'layers/kernel/package.json', 'layers/kernel/linux.tar.gz',
                'layers/base/package.json', 'layers/base/distribution.tar.gz',
                'layers/demo/package.json', 'layers/demo/local.deb', 'SHA256SUMS',
            ])
            for line in bundle.extractfile('SHA256SUMS').read().decode().splitlines():
                digest, name = line.split('  ', 1)
                self.assertEqual(digest, hashlib.sha256(bundle.extractfile(name).read()).hexdigest())
            self.assertEqual(bundle.extractfile('layers/kernel/linux.tar.gz').read(), kernel.read_bytes())
        first = self.output.read_bytes()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), first)

    def test_reject_wrong_order_scope_and_missing_inputs(self):
        self.layer('demo', 'demo.tar.gz', b'demo', requires=['base'], board='w202ds')
        self.layer('base', 'base.tar.gz', b'base', distribution='other/distro')
        for selected, error in [
            (('demo', 'base'), 'required layer base must appear earlier'),
            (('base', 'demo'), 'does not match target'),
            (('unknown',), 'Missing file'),
            (('../escape',), 'Invalid relative path'),
        ]:
            with self.subTest(selected=selected):
                self.recipe(*selected)
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(self.output.parent.exists())

    def test_source_layer_is_prepared_on_demand_and_reused(self):
        self.layer('kernel', 'linux.tar.gz', b'kernel', board='w202ds')
        self.recipe('kernel')
        source = {'id': 'powerkey-interface', 'receipt': 'board-interface/package.json',
                  'producer': 'devices/w202ds/overlays/w202ds-powerkey-interface/package.py',
                  'requires': ['kernel']}
        recipe = json.loads(self.target.read_text())
        recipe['layers'].append(source)
        self.target.write_text(json.dumps(recipe))
        receipt = self.pool/source['receipt']

        plan = self.cli('--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual(json.loads(plan.stdout)['layers'][-1]['action'], 'build')
        self.assertFalse(receipt.parent.exists())
        first = self.cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        with tarfile.open(self.output) as bundle:
            payload = bundle.extractfile('layers/powerkey-interface/powerkey-interface-w202ds.tar.gz')
            with tarfile.open(fileobj=payload) as layer:
                interface = layer.getmember('usr/libexec/reimuks-display-toggle')
                self.assertTrue(interface.mode & 0o111)
        self.output.unlink()
        generated = receipt.stat().st_mtime_ns
        second = self.cli()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(receipt.stat().st_mtime_ns, generated)

    def test_corrupt_input_does_not_publish_a_partial_bundle(self):
        path = self.layer('kernel', 'linux.tar.gz', b'correct')
        self.recipe('kernel')
        path.write_bytes(b'changed')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_named_app_overlays_are_optional_and_precede_user_layers(self):
        self.layer('distribution', 'base.tar.gz', b'distro')
        prefix = self.pool/'apps/debian/trixie/arm64'
        prefix.mkdir(parents=True)
        for group in ('remote', 'gui-test', 'unselected'):
            layer = self.layer('apps-'+group, f'{group}.tar.gz', group.encode(),
                               distribution='debian/trixie', requires=['distribution'])
            layer.parent.rename(prefix/group)
        self.layer('settings', 'settings.tar.gz', b'user settings', private=True,
                   requires=['apps-remote'])
        self.recipe('distribution')
        original = self.target.read_bytes()
        args = ('--app-overlay', 'remote', '--app-overlay', 'gui-test',
                '--user-overlay', 'settings/package.json')
        expected = ['distribution', 'apps-remote', 'apps-gui-test', 'settings']
        plan = self.cli(*args, '--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual([item['id'] for item in json.loads(plan.stdout)['layers']], expected)
        self.assertFalse(self.output.exists())
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.output) as bundle:
            manifest = json.load(bundle.extractfile('manifest.json'))
            self.assertEqual([item['id'] for item in manifest['layers']], expected)
            for group in ('remote', 'gui-test'):
                self.assertEqual(bundle.extractfile(f'layers/apps-{group}/{group}.tar.gz').read(),
                                 group.encode())
        self.assertEqual(self.target.read_bytes(), original)

    def test_preset_inherits_base_and_appends_named_extras(self):
        self.layer('distribution', 'rootfs.tar.gz', b'distro')
        pool = self.pool/'apps/debian/trixie/arm64'
        pool.mkdir(parents=True)
        for name in ('remote', 'gui-test'):
            overlay = self.layer('apps-'+name, 'app.tar.gz', name.encode(),
                                 distribution='debian/trixie', requires=['distribution'])
            overlay.parent.rename(pool/name)
        private = self.layer('passkey', 'user.tar.gz', b'settings', private=True)
        destination = self.pool/'private/w202ds/passkey'
        destination.parent.mkdir(parents=True)
        private.parent.rename(destination)
        self.recipe('distribution')
        self.target.rename(self.root/'base.json')
        self.target.write_text(json.dumps(dict(
            schema=1, id='remote-workstation', architecture='arm64', board='w202ds',
            distribution='debian/trixie', extends='base.json', app_overlays=['remote'],
            user_overlays=['passkey'])))

        build = self.cli('--app-overlay', 'gui-test')
        self.assertEqual(build.returncode, 0, build.stderr)
        with tarfile.open(self.output) as bundle:
            manifest = json.load(bundle.extractfile('manifest.json'))
            self.assertTrue(manifest['private'])
            self.assertEqual([item['id'] for item in manifest['layers']],
                             ['distribution', 'apps-remote', 'apps-gui-test', 'passkey'])

    def test_explicit_private_bundle_has_restricted_access(self):
        self.layer('local-user', 'settings.tar.gz', b'private settings', private=True)
        self.recipe('local-user')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('allow_private', result.stderr)
        self.recipe('local-user', allow_private=True)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        with tarfile.open(self.output) as bundle:
            self.assertEqual(bundle.getmember('layers/local-user/settings.tar.gz').mode, 0o600)


    def test_cli_appends_multiple_private_layers_in_order_without_editing_recipe(self):
        self.layer('base', 'base.tar.gz', b'base')
        login = self.layer('login', 'settings.tar.gz', b'login', private=True, requires=['base'])
        theme = self.layer('theme', 'theme.tar.gz', b'theme', private=True, requires=['login'])
        self.recipe('base')
        recipe = self.target.read_bytes()
        args = ('--user-overlay', 'login/package.json', '--user-overlay', 'theme/package.json')
        plan = self.cli(*args, '--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual([x['id'] for x in json.loads(plan.stdout)['layers']], ['base', 'login', 'theme'])
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), recipe)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        with tarfile.open(self.output) as bundle:
            manifest = json.load(bundle.extractfile('manifest.json'))
            self.assertTrue(manifest['private'])
            self.assertEqual([x['id'] for x in manifest['layers']], ['base', 'login', 'theme'])
            for name, path in [('login', login), ('theme', theme)]:
                payload = f'layers/{name}/{path.name}'
                self.assertEqual(bundle.getmember(payload).mode, 0o600)
                self.assertEqual(bundle.extractfile(payload).read(), path.read_bytes())

    def test_cli_private_opt_in_does_not_include_other_recipe_layers(self):
        self.layer('base', 'base.tar.gz', b'base')
        self.layer('login', 'settings.tar.gz', b'login', private=True)
        self.layer('other', 'other.tar.gz', b'other', private=True)
        self.recipe('base', 'other')
        result = self.cli('--user-overlay', 'login/package.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('other: private layer requires allow_private', result.stderr)
        self.recipe('base')
        self.layer('public', 'extras.tar.gz', b'extras')
        result = self.cli('--user-overlay', 'public/package.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--user-overlay requires a private package receipt', result.stderr)
        self.assertFalse(self.output.parent.exists())

    def test_named_user_layers_build_from_sources_with_no_prebuilt_private_packages(self):
        self.layer('distribution', 'base.tar.gz', b'base')
        self.layer('desktop-kde', 'kde.tar.gz', b'desktop', requires=['distribution'])
        self.recipe('distribution', 'desktop-kde')
        sources = self.root/'inputs'
        login = sources/'w202ds/passkey/etc/hostname'
        login.parent.mkdir(parents=True)
        login.write_text('fixture-host\n')
        wallpaper = sources/'w202ds/kde-theme/wallpaper.png'
        wallpaper.parent.mkdir(parents=True)
        wallpaper.write_bytes(bytes.fromhex(
            '89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02'
            '0000000b4944415478da63fcff1f0003030200ef80575f0000000049454e44ae426082'))
        args = ('--user-input-root', str(sources), '--user-overlay', 'passkey',
                '--user-overlay', f'kde-theme={wallpaper}')
        plan = self.cli(*args, '--plan')
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual([(x['id'], x['action']) for x in json.loads(plan.stdout)['layers'][-2:]],
                         [('passkey', 'build'), ('kde-theme', 'build')])
        self.assertFalse(self.output.parent.exists())
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.pool/'private').exists())
        with tarfile.open(self.output) as bundle:
            manifest = json.load(bundle.extractfile('manifest.json'))
            self.assertEqual([x['id'] for x in manifest['layers'][-2:]], ['passkey', 'kde-theme'])
            receipt = json.load(bundle.extractfile('layers/passkey/package.json'))
            self.assertEqual(receipt['board'], 'w202ds')
            with tarfile.open(fileobj=bundle.extractfile('layers/passkey/passkey-overlay.tar.gz')) as overlay:
                self.assertEqual(overlay.extractfile('etc/hostname').read(), login.read_bytes())
            with tarfile.open(fileobj=bundle.extractfile('layers/kde-theme/kde-theme-overlay.tar.gz')) as overlay:
                self.assertEqual(overlay.extractfile('home/reimuks/Pictures/Wallpapers/reimuks-wallpaper.png').read(),
                                 wallpaper.read_bytes())

    @unittest.skipUnless(shutil.which('openssl'), 'requires openssl for TLS fixtures')
    def test_rexeterm_only_packages_board_credentials_and_an_arm64_server(self):
        self.layer('distribution', 'base.tar.gz', b'base')
        self.recipe('distribution')
        source = self.root/'rexeterm'
        source.mkdir()
        for role in ('server', 'client'):
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec',
                            '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-days', '1',
                            '-subj', f'/CN={role}', '-keyout', f'{role}-key.pem',
                            '-out', f'{role}-cert.pem'], cwd=source, check=True, capture_output=True)
        binary = source/'rexed'
        elf = b'\x7fELF\x02\x01\x01'+bytes(9)+b'\x03\x00'
        option = f'--user-overlay=rexeterm={source}'

        binary.write_bytes(elf+b'\x3e\x00')
        wrong_arch = self.cli(option)
        self.assertNotEqual(wrong_arch.returncode, 0)
        self.assertIn('ARM64 Linux ELF', wrong_arch.stderr)
        self.assertFalse(self.output.exists())

        binary.write_bytes(elf+b'\xb7\x00')
        result = self.cli(option)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        with tarfile.open(self.output) as bundle:
            receipt = json.load(bundle.extractfile('layers/rexeterm/package.json'))
            self.assertEqual((receipt['private'], receipt['board'], receipt['architecture']),
                             (True, 'w202ds', 'arm64'))
            with tarfile.open(fileobj=bundle.extractfile('layers/rexeterm/rexeterm-overlay.tar.gz')) as layer:
                config = 'home/reimuks/.config/rexed'
                files = {member.name for member in layer if member.isfile()}
                self.assertEqual(files, {f'{config}/{name}' for name in (
                    'server-cert.pem', 'server-key.pem', 'server.json',
                    'users/reimuks/client-cert.pem', 'users/reimuks/config.json',
                )} | {'usr/bin/rexed', 'usr/lib/systemd/system/rexed.service'})
                self.assertEqual(layer.getmember(f'{config}/server-key.pem').mode, 0o600)
                self.assertEqual(layer.extractfile(f'{config}/users/reimuks/client-cert.pem').read(),
                                 (source/'client-cert.pem').read_bytes())


if __name__ == '__main__':
    unittest.main()

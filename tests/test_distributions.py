"""Offline checks for distro selection, inheritance and cache separation."""
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import distributions as registry
import build


class DistributionTest(unittest.TestCase):
    def setUp(self):
        self.distro = registry.load_distribution()

    def tearDown(self):
        build.select_distribution(registry.DEFAULT)

    def test_cli_lists_distributions_and_rejects_unknown_before_outputs(self):
        result = subprocess.run([sys.executable, str(ROOT/'reimuks.py'), '--list-distributions'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('debian/trixie', result.stdout)
        result = subprocess.run([sys.executable, str(ROOT/'reimuks.py'), '--distribution', '../bad',
                                 '--board', 'w202ds', '--target', 'rootfs'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_debian_packages_and_target_are_resolved_through_inheritance(self):
        base = registry.resolve_profile('desktop/server', self.distro)
        kde = registry.resolve_profile('desktop/kde', self.distro)
        self.assertEqual(base['target'], 'multi-user.target')
        self.assertEqual(kde['target'], 'graphical.target')
        self.assertTrue(set(base['packages']) <= set(kde['packages']))
        self.assertIn('kde-standard', kde['packages'])
        self.assertIn('kde-standard', kde['required_packages'])
        self.assertTrue(kde['install_recommends'])
        self.assertFalse(base['install_recommends'])
        self.assertNotIn('vulkan-tools', base['packages'])
        self.assertNotIn('libvulkan1', base['packages'])
        self.assertIn('openssh-server', base['required_packages'])
        self.assertIn('systemd-timesyncd', base['packages'])
        self.assertIn('wpasupplicant', base['packages'])
        self.assertEqual(kde['display_protocol'], 'wayland')
        self.assertNotIn('xwayland', kde['packages'])
        self.assertIn('systemd-sysv', kde['required_packages'])
        self.assertEqual(kde['display_manager'], 'sddm')

    def test_desktop_mappings_delegate_standard_components_to_meta_packages(self):
        kde = self.distro['profiles']['desktop/kde']
        gnome = self.distro['profiles']['desktop/gnome']
        self.assertNotIn('plasma-workspace', kde['packages'])
        self.assertNotIn('systemsettings', kde['packages'])
        self.assertNotIn('gnome-shell', gnome['packages'])
        self.assertNotIn('nautilus', gnome['packages'])
        # Keep verification independent from the compact direct package list.
        self.assertIn('systemsettings', kde['required_packages'])
        self.assertIn('gnome-control-center', gnome['required_packages'])

    def test_additional_apps_and_signed_repositories_are_desktop_only(self):
        apps = {'google-chrome-stable', 'code', 'btop', 'fastfetch', 'vim', 'lazygit'}
        for profile in ('kde', 'gnome'):
            spec = registry.resolve_profile(profile, self.distro)
            self.assertFalse(apps & set(spec['packages']))
            self.assertFalse(apps & set(spec['required_packages']))
            self.assertNotIn('dl.google.com', registry.sources_list(self.distro, target=True, profile=profile))
            sources = registry.sources_list(self.distro, target=True, profile=profile, include_apps=True)
            self.assertIn('signed-by=/usr/share/keyrings/reimuks-google.asc', sources)
            self.assertIn('https://packages.microsoft.com/repos/code', sources)
            self.assertIn('libvulkan1', spec['packages'])
        server = registry.resolve_profile('server', self.distro)
        self.assertNotIn('google-chrome-stable', server['packages'])
        self.assertNotIn('code', server['packages'])
        self.assertNotIn('dl.google.com', registry.sources_list(self.distro, profile='server'))

    def test_kde_login_and_session_do_not_start_x_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build.configure_display('kde', root)
            login = (root/'etc/sddm.conf.d/20-reimuks-wayland.conf').read_text()
            self.assertIn('DisplayServer=wayland', login)
            service = (root/'etc/systemd/user/plasma-kwin_wayland.service.d/20-reimuks-wayland.conf').read_text()
            self.assertIn('ExecStart=\nExecStart=/usr/bin/kwin_wayland_wrapper\n', service)
            self.assertNotIn('--xwayland', service)

    def test_fetch_uses_each_profiles_recommendation_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state/'archives').mkdir()
            for profile, expected in [('kde', '--install-recommends'),
                                      ('gnome', '--install-recommends'),
                                      ('server', '--no-install-recommends')]:
                with self.subTest(profile=profile), \
                        patch.object(build, 'apt_state', return_value=state), \
                        patch.object(build, 'apt') as apt, \
                        patch('apt_selection.selected_archives', return_value=[]):
                    build.fetch(profile)
                    install = apt.call_args_list[-1].args
                    self.assertIn(expected, install)
                    if profile == 'kde':
                        self.assertIn('kde-standard', install)
                    elif profile == 'gnome':
                        self.assertIn('gnome', install)

    def test_plasma_version_floor_rejects_old_missing_and_prerelease_packages(self):
        specification = {'minimum_package_versions': {'example-package': '6.3.6'}}
        packages = specification['minimum_package_versions']
        registry.check_package_versions(specification, dict.fromkeys(packages, '4:6.3.6-1'))
        registry.check_package_versions(specification, dict.fromkeys(packages, '4:6.9.0-1'))
        for version in ('4:6.3.3-1', '4:6.2.5-2', '4:6.3.6~beta1-1'):
            with self.assertRaisesRegex(ValueError, 'requires >= 6.3.6'):
                registry.check_package_versions(specification, dict.fromkeys(packages, version))
        with self.assertRaisesRegex(ValueError, 'missing'):
            registry.check_package_versions(specification, {})

    def test_gnome_inherits_base_without_kde(self):
        base = registry.resolve_profile('server', self.distro)
        gnome = registry.resolve_profile('gnome', self.distro)
        self.assertEqual(gnome['target'], 'graphical.target')
        self.assertEqual(gnome['display_manager'], 'gdm3')
        self.assertTrue(set(base['packages']) <= set(gnome['packages']))
        self.assertIn('gnome-shell', gnome['required_packages'])
        self.assertIn('gnome', gnome['packages'])
        self.assertIn('gnome', gnome['required_packages'])
        self.assertTrue(gnome['install_recommends'])
        self.assertNotIn('sddm', gnome['packages'])
        self.assertNotIn('plasma-workspace', gnome['packages'])

    def test_mapping_files_are_not_distributions_and_split_preserves_identity(self):
        raw = json.loads((ROOT/'distributions/debian/trixie.json').read_text())
        self.assertIsInstance(raw['profiles']['desktop/kde'], str)
        self.assertEqual(set(registry.distributions()), {'debian/trixie'})
        inline = copy.deepcopy(raw)
        for name, relative in raw['profiles'].items():
            inline['profiles'][name] = json.loads((ROOT/'distributions/debian'/relative).read_text())
        inline["additional_packages"] = copy.deepcopy(self.distro["additional_packages"])
        inline["desktop_common"] = copy.deepcopy(self.distro["desktop_common"])
        self.assertEqual(registry.identity(inline), registry.identity(self.distro))

    def test_referenced_mapping_changes_identity_and_invalid_paths_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo/'distributions/debian'
            base.mkdir(parents=True)
            shutil.copytree(ROOT/"distributions/debian/trixie/keys", base/"trixie/keys")
            raw = copy.deepcopy(self.distro)
            mapping = copy.deepcopy(raw['profiles']['desktop/gnome'])
            raw['profiles']['desktop/gnome'] = 'trixie/desktop/gnome.json'
            definition = base/'trixie.json'
            definition.write_text(json.dumps(raw))
            file = base/'trixie/desktop/gnome.json'
            file.parent.mkdir(parents=True)
            file.write_text(json.dumps(mapping))
            before = registry.identity(registry.load_distribution(repo=repo))
            mapping['packages'].append('test-package')
            file.write_text(json.dumps(mapping))
            self.assertNotEqual(before, registry.identity(registry.load_distribution(repo=repo)))
            for reference in ('../outside.json', '/outside.json', 'missing.json'):
                raw['profiles']['desktop/gnome'] = reference
                definition.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    registry.load_distribution(repo=repo)

    def test_distribution_controls_both_build_and_installed_sources(self):
        distro = copy.deepcopy(self.distro)
        distro['build_repositories'] = [{'uri': 'https://mirror.example/debian', 'suite': 'bookworm'}]
        distro['target_repositories'] = [{'uri': 'https://target.example/debian', 'suite': 'bookworm-security'}]
        self.assertEqual(registry.sources_list(distro, keyring='/keys/test.gpg'),
                         'deb [signed-by=/keys/test.gpg] https://mirror.example/debian bookworm main\n')
        self.assertEqual(registry.sources_list(distro, target=True),
                         'deb https://target.example/debian bookworm-security main\n')

    def test_other_release_cannot_reuse_default_rootfs_or_cache(self):
        other = copy.deepcopy(self.distro)
        other['id'] = 'debian/bookworm'
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, 'BUILD', Path(tmp)):
            old = build.profile_directory('kde')
            with patch.object(build, 'DISTRIBUTION', other):
                self.assertNotEqual(build.profile_directory('kde'), old)
                self.assertEqual(build.artifact_directory(), Path(tmp)/'distributions/debian/bookworm/artifacts')

    def test_apt_cache_uses_selected_release_and_signed_sources_without_downloading(self):
        other = copy.deepcopy(self.distro)
        other['id'] = 'debian/bookworm'
        other['suite'] = 'bookworm'
        other['build_repositories'] = [{'uri': 'https://mirror.example/debian', 'suite': 'bookworm'}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, 'BUILD', Path(tmp)), \
                patch.object(build, 'DISTRIBUTION', other):
            state = build.apt_state('apt-kde', 'arm64')
            self.assertTrue(state.is_relative_to(Path(tmp)/'distributions/debian/bookworm'))
            sources = (state/'sources.list').read_text()
            self.assertIn('signed-by=', sources)
            self.assertIn('https://mirror.example/debian bookworm main', sources)
            self.assertNotIn(' trixie ', sources)
            self.assertEqual(json.loads((state/'distribution.json').read_text())['id'], 'debian/bookworm')

    def test_cache_rejects_changed_distribution_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            build.bind_distribution(directory)
            other = copy.deepcopy(self.distro)
            other['build_repositories'][0]['uri'] = 'https://other.example/debian'
            with patch.object(build, 'DISTRIBUTION', other):
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    build.bind_distribution(directory)

    def test_legacy_rootfs_must_match_selected_os_release(self):
        registry.check_os_release('ID=debian\nVERSION_CODENAME=trixie\n', self.distro)
        with self.assertRaisesRegex(ValueError, 'distribution mismatch'):
            registry.check_os_release('ID=debian\nVERSION_CODENAME=bookworm\n', self.distro)

    def test_unsupported_profile_and_backend_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'placeholder'):
            registry.resolve_profile('desktop/niri', self.distro)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            file = repo/'distributions/example/stable.json'
            file.parent.mkdir(parents=True)
            unsupported = self.distro | {'id': 'example/stable', 'backend': 'rpm'}
            file.write_text(json.dumps(unsupported))
            with self.assertRaisesRegex(ValueError, 'backend'):
                registry.load_distribution('example/stable', repo)


if __name__ == '__main__':
    unittest.main()

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from board_userspace import install_initramfs, install_rootfs, install_template
import board_userspace


class UserspaceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'rootfs'
        self.root.mkdir()
        self.artifacts = Path(self.directory.name) / 'desktop-artifacts'
        header = b'\x7fELF\x02\x01' + b'\0' * 12 + b'\xb7\x00'
        import json
        policy = json.loads((ROOT / 'devices/w202ds/rootfs/policy.json').read_text())
        for layer in [policy['desktop_common'], *policy['profiles'].values()]:
            for artifact in layer.get('rootfs_artifacts', []):
                for filename in artifact['required_elf']:
                    binary = self.artifacts / artifact['rootfs'] / filename
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    binary.write_bytes(header)
            for artifact in layer.get('control_artifacts', []):
                for name in artifact['executables']:
                    binary = self.artifacts / artifact['rootfs'] / 'usr/libexec' / name
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    binary.write_bytes(header)
        self.artifact_patch = patch.object(board_userspace, 'ARTIFACT_ROOT', self.artifacts)
        self.artifact_patch.start()
        self.addCleanup(self.artifact_patch.stop)

    def exports(self, board):
        import json
        hardware = board / 'kernel'
        components = {p.parent.name: {'userspace': str(p.relative_to(hardware))}
                      for p in hardware.glob('Devices/*/userspace')}
        (hardware / 'board-userspace.json').write_text(json.dumps({
            'schema': 1, 'board': 'test-board', 'components': components}))
        (board / 'board.json').write_text(json.dumps({
            'board': 'test-board', 'architecture': 'arm64', 'userspace_manifest': 'kernel/board-userspace.json'}))

    def stage(self, profile):
        install_rootfs(self.root, profile)

    def test_legacy_vpu_runtime_is_rejected_and_service_stays_masked(self):
        import tarfile
        policy = board_userspace.verification_policy(ROOT / 'devices/w202ds', 'kde')[0]
        mask = tarfile.TarInfo('etc/systemd/system/w202-vpu.service')
        mask.type = tarfile.SYMTYPE
        mask.linkname = '/dev/null'
        rules = {name: policy[name] for name in ('absent_prefixes', 'link_targets')}
        members = {mask.name: mask}
        board_userspace.verify_archive([rules], members, {})
        for name in ('opt/w202ds/vpu/android/w202-avc-worker',
                     'opt/w202ds/vpu/android/vendor/lib64/decoder.so'):
            with self.assertRaises(AssertionError):
                board_userspace.verify_archive([rules], {**members, name: tarfile.TarInfo(name)}, {})
        mask.linkname = 'another.service'
        with self.assertRaises(AssertionError):
            board_userspace.verify_archive([rules], members, {})

    def test_current_templates_override_cached_artifacts_without_losing_binaries(self):
        import json
        board = Path(self.directory.name) / 'cached-board'
        source = board / 'kernel/Devices/modem/userspace'
        template = source / 'rootfs/usr/libexec/start'
        template.parent.mkdir(parents=True)
        template.write_text('current startup ordering')
        staging = source / 'stage/usr/libexec'
        staging.mkdir(parents=True)
        (staging / 'start').write_text('obsolete startup ordering')
        (staging / 'native').write_bytes(b'native executable')
        (source / 'artifacts.json').write_text(json.dumps({
            'schema': 1, 'rootfs': 'stage', 'required': ['usr/libexec/native']}))
        self.exports(board)
        board_userspace.install_component(self.root, board, 'modem')
        self.assertEqual((self.root / 'usr/libexec/start').read_text(), 'current startup ordering')
        self.assertEqual((self.root / 'usr/libexec/native').read_bytes(), b'native executable')

    def test_shared_library_symlinks_can_be_installed_repeatedly(self):
        source = Path(self.directory.name)/'library-template'
        source.mkdir()
        (source/'libexample.so.1').write_bytes(b'library')
        (source/'libexample.so').symlink_to('libexample.so.1')
        for _ in range(2):
            install_template(self.root, source)
        self.assertTrue((self.root/'libexample.so').is_symlink())
        self.assertEqual((self.root/'libexample.so').read_bytes(), b'library')

    def test_generated_board_artifacts_inherited_and_required(self):
        import json
        board = Path(self.directory.name) / 'board'
        shutil.copytree(ROOT / 'devices/w202ds/rootfs', board / 'rootfs')
        source = board / 'kernel/Devices/gpu/userspace'
        (source / 'rootfs').mkdir(parents=True)
        artifact = source / 'output/rootfs/usr/share/vulkan/icd.d/panfrost_icd.json'
        artifact.parent.mkdir(parents=True)
        artifact.write_text('board ICD')
        (source / 'artifacts.json').write_text(json.dumps({
            'schema': 1, 'rootfs': 'output/rootfs',
            'required': ['usr/share/vulkan/icd.d/panfrost_icd.json']}))
        policy = json.loads((board / 'rootfs/policy.json').read_text())
        policy['common']['components'] = []
        policy['common']['components'] = ['gpu']
        policy['desktop_common']['components'] = []
        policy['profiles']['desktop/server'].pop('components', None)
        (board / 'rootfs/policy.json').write_text(json.dumps(policy))
        modules = self.root / 'usr/lib/modules/test/kernel'
        modules.mkdir(parents=True)
        (modules / 'panfrost.ko').touch()
        for profile in ('desktop/server', 'desktop/kde', 'desktop/gnome'):
            self.exports(board)
            install_rootfs(self.root, profile, board)
            installed = self.root / 'usr/share/vulkan/icd.d/panfrost_icd.json'
            self.assertEqual(installed.read_text(), 'board ICD')
            installed.unlink()
        artifact.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing gpu userspace artifact'):
            install_rootfs(self.root, 'desktop/kde', board)

    def test_templates_preserve_saved_nm_connection_by_uuid_and_filename(self):
        source = Path(self.directory.name) / 'defaults'
        defaults = source / 'etc/NetworkManager/system-connections'
        defaults.mkdir(parents=True)
        content = '[connection]\nuuid=51067143-44f5-5076-92b2-c08a884061bb\nautoconnect=true\n'
        (defaults / 'example.nmconnection').write_text(content)
        connections = self.root / 'etc/NetworkManager/system-connections'
        connections.mkdir(parents=True)
        custom = connections / 'my-ethernet.nmconnection'
        saved = content.replace('autoconnect=true', 'autoconnect=false')
        custom.write_text(saved)
        install_template(self.root, source)
        self.assertEqual(custom.read_text(), saved)
        default = connections / 'example.nmconnection'
        self.assertFalse(default.exists())
        custom.unlink()
        install_template(self.root, source)
        self.assertEqual(default.read_text(), content)
        default.write_text(saved)
        install_template(self.root, source)
        self.assertEqual(default.read_text(), saved)

    def test_ssh_is_independent_of_legacy_hardware_readiness(self):
        dropins = self.root / 'etc/systemd/system/ssh.service.d'
        dropins.mkdir(parents=True)
        legacy = dropins / '20-w202-ready.conf'
        keys = dropins / '20-w202ds-hostkeys.conf'
        key_config = '[Unit]\nRequires=w202ds-ssh-hostkeys.service\n'
        keys.write_text(key_config)
        for profile in ('desktop/server', 'desktop/kde', 'desktop/gnome'):
            with self.subTest(profile=profile):
                legacy.write_text('[Unit]\nRequires=w202-ready.service\n')
                self.stage(profile)
                self.stage(profile)
                self.assertFalse(legacy.exists())
                self.assertEqual(keys.read_text(), key_config)

    def test_gnome_uses_common_hardware_without_server_or_kde_policy(self):
        self.stage('gnome')
        self.assertTrue((self.root / 'usr/libexec/w202-usb-gadget').exists())
        wants = self.root / 'etc/systemd/system/multi-user.target.wants'
        self.assertFalse((wants / 'systemd-networkd.service').is_symlink())
        self.assertFalse((wants / 'w202-display-login.service').is_symlink())
        self.assertFalse((self.root / 'etc/systemd/logind.conf.d/60-w202-lid.conf').exists())
        self.assertFalse((self.root / 'usr/share/kwin').exists())

    def test_shared_controls_and_services_are_identical_across_desktops(self):
        for profile in ('kde', 'gnome'):
            with self.subTest(profile=profile):
                target = Path(self.directory.name) / profile
                target.mkdir()
                install_rootfs(target, profile)
                for name in ('device-controls', 'gnss-control', 'bluetooth-state'):
                    self.assertTrue(os.access(target / 'usr/libexec' / ('w202-' + name), os.X_OK))
                self.assertTrue((target / 'usr/lib/systemd/system/w202-hall-input.service').exists())
                self.assertTrue((target / 'usr/lib/systemd/system/w202-gnss.service').exists())
                self.assertEqual((target / 'usr/libexec/w202-hardware-controls').exists(), profile == 'kde')
                self.assertEqual((target / 'usr/libexec/w202-tablet-mode').exists(), profile == 'kde')
        self.stage('server')
        self.assertFalse((self.root / 'usr/libexec/w202-device-controls').exists())

    def test_missing_or_wrong_architecture_controls_fail_before_staging(self):
        binary = self.artifacts / 'device-controls/rootfs/usr/libexec/w202-device-controls'
        binary.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing board integration'):
            self.stage('gnome')
        self.assertFalse(list(self.root.iterdir()))
        binary.write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + b'\x3e\x00')
        with self.assertRaisesRegex(ValueError, 'ELF64 for arm64'):
            self.stage('kde')
        self.assertFalse(list(self.root.iterdir()))

    def test_graphical_profiles_use_wayland_login(self):
        self.stage('gnome')
        config = (self.root / 'etc/gdm3/daemon.conf').read_text()
        self.assertIn('WaylandEnable=true', config)
        self.assertIn('XorgEnable=false', config)
        self.assertIn('PreferredDisplayServer=wayland', config)
        self.stage('kde')
        config = (self.root / 'etc/sddm.conf.d/60-reimuks-wayland.conf').read_text()
        self.assertIn('DisplayServer=wayland', config)
        self.assertIn('CompositorCommand=kwin_wayland', config)
        self.assertIn('[X11]\nSessionDir=/usr/share/reimuks/no-x11-sessions', config)
        self.assertFalse(list((self.root / 'usr/share/reimuks/no-x11-sessions').glob('*.desktop')))

    def test_server_without_audio(self):
        self.stage('server')
        for name in ('w202-usb-gadget', 'w202-display-prepare', 'w202-display-login'):
            self.assertTrue(os.access(self.root / 'usr/libexec' / name, os.X_OK))
        self.assertTrue((self.root / 'usr/libexec/w202-audio-start').exists())
        wants = self.root / 'etc/systemd/system/multi-user.target.wants'
        self.assertEqual((wants / 'w202-display-login.service').readlink(),
                         Path('/usr/lib/systemd/system/w202-display-login.service'))
        self.assertTrue((wants / 'systemd-networkd.service').is_symlink())
        self.assertFalse((wants / 'w202-hall.service').is_symlink())
        lid = self.root / 'etc/systemd/logind.conf.d/60-w202-lid.conf'
        self.assertIn('HandleLidSwitch=ignore', lid.read_text())

    def test_audio_from_component_and_idempotent_install(self):
        modules = self.root / 'usr/lib/modules/test-release/updates/w202ds'
        modules.mkdir(parents=True)
        (modules / 'w202_audio_card.ko').touch()
        self.stage('server')
        self.stage('server')
        source = ROOT / 'devices/w202ds/kernel/Devices/audio/userspace/rootfs/usr/libexec/w202-audio-start'
        installed = self.root / 'usr/libexec/w202-audio-start'
        self.assertEqual(installed.read_bytes(), source.read_bytes())
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertTrue((self.root / 'etc/systemd/system/multi-user.target.wants/w202-audio.service').is_symlink())

    def test_guarded_charge_policy_for_both_desktop_profiles(self):
        modules = self.root / 'usr/lib/modules/test-release/updates/w202ds'
        modules.mkdir(parents=True)
        (modules / 'w202_bq_control.ko').touch()
        for profile in ('desktop/server', 'desktop/kde'):
            with self.subTest(profile=profile):
                self.stage(profile)
                self.assertTrue(os.access(self.root / 'usr/libexec/w202-charging', os.X_OK))
                unit = self.root / 'usr/lib/systemd/system/w202-charging.service'
                self.assertIn('Environment=CHARGE_BEHAVIOUR=inhibit-charge', unit.read_text())
                self.assertIn('CHARGE_BEHAVIOUR=auto',
                              (self.root / 'etc/default/w202-charging').read_text())
                enabled = self.root / 'etc/systemd/system/multi-user.target.wants/w202-charging.service'
                self.assertEqual(enabled.readlink(), Path('/usr/lib/systemd/system/w202-charging.service'))

    def test_charging_userspace_is_independent_of_installed_kernel(self):
        self.stage('desktop/server')
        self.assertTrue((self.root / 'usr/libexec/w202-charging').exists())
        self.assertTrue((self.root / 'etc/systemd/system/multi-user.target.wants/w202-charging.service').is_symlink())

    def test_kde_keeps_usb_without_server_console_or_networkd(self):
        networkd = self.root / 'etc/systemd/system/multi-user.target.wants/systemd-networkd.service'
        networkd.parent.mkdir(parents=True)
        networkd.symlink_to('/usr/lib/systemd/system/systemd-networkd.service')
        self.stage('kde')
        self.assertFalse(networkd.is_symlink())
        self.assertFalse((self.root / 'usr/libexec/w202-display-login').exists())
        self.assertTrue((self.root / 'usr/lib/systemd/system/w202-bsp.service').exists())
        self.assertTrue((self.root / 'usr/libexec/w202-display-prepare').exists())
        self.assertTrue((self.root / 'usr/libexec/w202-usb-gadget').is_file())
        self.assertTrue((self.root / 'etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service').is_symlink())
        network = (self.root / 'etc/systemd/network/80-w202-usb.network').read_text()
        config = (self.root / 'etc/default/w202-usb-gadget').read_text()
        address = next(line.split('=', 1)[1] for line in network.splitlines()
                       if line.startswith('Address='))
        self.assertIn(f'USB_ADDRESS={address}\n', config)

    def test_kde_delegates_lid_actions_to_desktop(self):
        self.stage('desktop/kde')
        self.assertFalse((self.root / 'etc/systemd/logind.conf.d/60-w202-lid.conf').exists())
        mapping = self.root / 'etc/modprobe.d/w202-hall.conf'
        self.assertIn('options w202_hall switch_code=-1', mapping.read_text())
        self.assertTrue((self.root / 'usr/share/kwin/scripts/w202ds-tablet-keyboard/metadata.json').is_file())

    def test_rootfs_does_not_inspect_or_require_kernel_modules(self):
        self.stage('desktop/server')
        self.assertFalse((self.root / 'usr/lib/modules').exists())
        self.assertTrue((self.root / 'etc/modprobe.d/w202-hall.conf').exists())

    def test_configurable_hall_module_accepts_profile_mapping(self):
        modules = self.root / 'usr/lib/modules/test-release/updates/w202ds'
        modules.mkdir(parents=True)
        (modules / 'w202_hall.ko').write_bytes(b'\0parmtype=switch_code:int\0')
        self.stage('desktop/kde')
        self.assertIn('switch_code=-1', (self.root / 'etc/modprobe.d/w202-hall.conf').read_text())
        self.assertTrue((self.root / 'etc/systemd/system/multi-user.target.wants/w202-hall-input.service').is_symlink())
        self.assertIn('--active-delay-ms 2000', (self.root / 'usr/lib/systemd/system/w202-hall-input.service').read_text())

    def test_reimuks_overrides_component_defaults(self):
        board = Path(self.directory.name) / 'board'
        shutil.copytree(ROOT / 'devices/w202ds/rootfs', board / 'rootfs')
        components = ROOT / 'devices/w202ds/kernel/Devices'
        for name in ('usb3', 'drm'):
            shutil.copytree(components / name / 'userspace/rootfs',
                            board / 'kernel/Devices' / name / 'userspace/rootfs')
        relative = 'usr/libexec/w202-usb-gadget'
        default = board / 'rootfs/common' / relative
        default.parent.mkdir(parents=True, exist_ok=True)
        default.write_text('common override\n')
        override = board / 'rootfs/profiles/desktop/server' / relative
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text('profile override\n')
        import json
        policy_file = board / 'rootfs/policy.json'
        data = json.loads(policy_file.read_text())
        data['common']['components'] = ['usb3', 'drm']
        policy_file.write_text(json.dumps(data))
        self.exports(board)
        install_rootfs(self.root, 'desktop/server', board)
        self.assertEqual((self.root / relative).read_text(), 'profile override\n')

    def test_initramfs_reuses_board_transport_and_policy(self):
        install_initramfs(self.root)
        board = ROOT / 'devices/w202ds'
        source = board / 'kernel/Devices/usb3/userspace/rootfs/usr/libexec/w202-usb-gadget'
        installed = self.root / 'bin/w202-usb-gadget'
        self.assertEqual(installed.read_bytes(), source.read_bytes())
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertEqual((self.root / 'etc/default/w202-usb-gadget').read_bytes(),
                         (board / 'rootfs/common/etc/default/w202-usb-gadget').read_bytes())
        hook = self.root / 'usr/lib/reimuks/initramfs.d/20-hardware'
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertNotIn('voltage_offset_uv', (ROOT / 'initramfs/init').read_text())

    def test_unknown_profile_is_rejected_before_staging(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported board rootfs profile'):
            self.stage('niri')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_wcn_recovery_policy_with_fake_hardware(self):
        board = ROOT / 'devices/w202ds'
        shutil.copytree(board / 'kernel/Devices/wcn/userspace/rootfs', self.root, dirs_exist_ok=True)
        shutil.copytree(board / 'rootfs/optional/wcn', self.root, dirs_exist_ok=True)
        subprocess.run([sys.executable, '-B', str(board / 'tests/wcn-recovery.py'),
                        str(self.root), str(Path(self.directory.name) / 'wcn-tests')], check=True)


if __name__ == '__main__':
    unittest.main()

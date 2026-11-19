"""Layer packages must have independent ownership and enforce real dependencies."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build
import layers
import pack
from board_userspace import service_link


class LayerPackages(unittest.TestCase):
    def test_timer_policy_installs_a_systemd_unit_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = 'timers.target.wants/w202-wifi-recover.timer'
            service_link(root, relative, 'w202-wifi-recover.timer')
            self.assertEqual((root/'etc/systemd/system'/relative).readlink(),
                             Path('/usr/lib/systemd/system/w202-wifi-recover.timer'))
            with self.assertRaises(ValueError):
                service_link(root, relative, '../outside.timer')

    def test_apt_can_resolve_local_bundle_without_sources_or_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'root';root.mkdir();cache=base/'packages'
            package=layers.package_tree(root,cache,'reimuks-test',[],'de-common')
            canonical=cache/f'reimuks-test_{package["version"]}_arm64.deb'
            (cache/package['file']).rename(canonical)
            (base/'status').touch();(base/'sources.list').touch()
            (base/'empty').mkdir();(base/'lists/partial').mkdir(parents=True)
            arguments=['apt-get','--download-only','--no-download','--no-install-recommends','-y']
            for key,value in {
                'Dir::State::status':base/'status','Dir::State::lists':base/'lists',
                'Dir::Cache':base/'cache','Dir::Cache::archives':str(cache)+'/',
                'Dir::Etc::main':'-','Dir::Etc::parts':base/'empty',
                'Dir::Etc::sourcelist':base/'sources.list','Dir::Etc::sourceparts':base/'empty',
                'APT::Architecture':'arm64',
            }.items(): arguments += ['-o',f'{key}={value}']
            subprocess.run([*arguments,'install',str(canonical)],check=True,capture_output=True,text=True)

    def test_base_and_desktop_composition_keep_source_clean_and_install_in_order(self):
        for base_only in (True, False):
            with self.subTest(base_only=base_only), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp);source=base/'server/rootfs';work=base/'server/work';output=base/'artifacts'
                (source/'etc').mkdir(parents=True);work.mkdir(parents=True)
                (source/'etc/shadow').write_text('root:!::::::::\nreimuks:!::::::::\n')
                for name in ('configured','clean-rootfs-v1','dpkg-audit.txt','fakeroot.state','packages.tsv'):
                    (work/name).touch()
                cache=base/'cache';cache.mkdir();(cache/'fetch-complete.json').write_text('{"archives": {}}')
                order=[]
                def desktop(root,*args):
                    order.append('de');(root/'etc/desktop-installed').touch()
                def board(root,work,*args):
                    self.assertTrue((root/'etc/desktop-installed').exists())
                    order.append('board');(work/'packages.tsv').touch();return {'packages':[]}
                def compress(root,work,output,profile):
                    (output/f'desktop-{profile}-arm64-rootfs.tar.gz.part').write_bytes(b'archive')
                with patch.object(build,'check_rootfs') as check, \
                     patch.object(build,'profile_directory',side_effect=lambda p:base/p), \
                     patch.object(build,'distribution_build',return_value=base), \
                     patch.object(build,'shared_distribution',return_value=base), \
                     patch.object(build,'composition_directory',return_value=base/'board-work'), \
                     patch.object(build,'artifact_directory',return_value=output), \
                     patch.object(build,'configure_locale'), \
                     patch.object(pack,'install_desktop',side_effect=desktop), \
                     patch.object(pack,'install_layer_packages',side_effect=board), \
                     patch.object(pack,'verify_startup',return_value={}), \
                     patch.object(pack,'compress_rootfs',side_effect=compress):
                    pack.rootfs('server' if base_only else 'kde',base_only=base_only,
                                from_base=not base_only,de_cache=cache)
                    check.assert_called_once_with('server')
                self.assertEqual(order,[] if base_only else ['de','board'])
                self.assertFalse((source/'etc/desktop-installed').exists())
                self.assertFalse((source/'usr/lib/reimuks/distribution.json').exists())
                label='base' if base_only else 'kde'
                self.assertTrue((output/f'desktop-{label}-arm64-rootfs.tar.gz').is_file())

    def test_shared_compatibility_has_no_desktop_specific_dependency(self):
        kde = {p['kind']:p for p in layers.plan('kde')}
        gnome = {p['kind']:p for p in layers.plan('gnome')}
        self.assertEqual(kde['board'], gnome['board'])
        self.assertEqual(kde['board-de'], gnome['board-de'])
        self.assertEqual(kde['de-common'], gnome['de-common'])
        self.assertEqual(kde['board-de']['depends'], ['reimuks-w202ds-board','reimuks-de-common'])
        self.assertIn('reimuks-de-kde', kde['board-kde']['depends'])
        server = {p['kind']:p for p in layers.plan('server')}
        self.assertEqual(kde['board-de'], server['board-de'])
        self.assertEqual(kde['de-common'], server['de-common'])
        self.assertIn('reimuks-w202ds-de-compat', server['board-server']['depends'])
        self.assertFalse(server['board-de'].get('conflicts'))
        self.assertEqual(set(server), {'board', 'board-de', 'de-common', 'board-server'})
        # Distribution-only server/base stays independent of the board runtime.
        self.assertEqual(layers.desktop_plan('server'), [])
        self.assertIn('network-manager', layers.board_dependencies('server'))
        self.assertIn('iio-sensor-proxy', layers.board_dependencies('server'))
        self.assertNotIn('network-manager', layers.requested_packages('server', include_board=False))
        self.assertNotIn('kde-standard', gnome['de-gnome']['depends'])
        self.assertIn('qtwayland5', kde['de-kde']['depends'])

    def test_deb_has_root_ownership_conffiles_dependencies_and_reproducible_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);digests=[]
            for index in range(2):
                root=base/str(index);(root/'etc/example').mkdir(parents=True)
                (root/'etc/example/policy').write_text('policy\n')
                result=layers.package_tree(root,base/'out','reimuks-test',['systemd'],'board')
                digests.append(result['sha256'])
            self.assertEqual(digests[0],digests[1])
            package=base/'out/reimuks-test.deb'
            self.assertEqual(subprocess.check_output(['dpkg-deb','-f',str(package),'Depends'],text=True).strip(),'systemd')
            control=base/'control';subprocess.run(['dpkg-deb','-e',str(package),str(control)],check=True)
            self.assertEqual((control/'conffiles').read_text(),'/etc/example/policy\n')
            stream=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(package)])
            with tarfile.open(fileobj=io.BytesIO(stream)) as archive:
                self.assertTrue(all(m.uid==m.gid==0 for m in archive))

    def test_private_accounts_and_kernel_modules_are_rejected(self):
        for name in ('etc/shadow','home/reimuks/private','usr/lib/modules/kernel/driver.ko'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'root';target=root/name;target.parent.mkdir(parents=True);target.touch()
                with self.assertRaisesRegex(ValueError,'Non-package'):
                    layers.package_tree(root,Path(tmp)/'out','reimuks-test',[],'board')

    def test_standard_desktop_packages_do_not_contain_board_code(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(build,'shared_distribution',return_value=Path(tmp)), \
             patch.object(layers,'plan',side_effect=AssertionError('Board dependency in a standard DE package')):
            packages=layers.pack_de('kde',Path(tmp)/'out')
            self.assertEqual({p['package'] for p in packages},{'reimuks-de-common','reimuks-de-kde'})
            for p in packages:
                data=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(Path(tmp)/'out'/p['file'])])
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    self.assertFalse(any('w202' in m.name for m in archive))
                self.assertFalse(any('w202' in name for name in p['depends']))

    def test_server_common_runtime_has_no_graphical_session(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, 'shared_distribution', return_value=Path(tmp)):
            packages = layers.pack_de('server', Path(tmp)/'out')
            self.assertEqual([p['package'] for p in packages], ['reimuks-de-common'])
            self.assertFalse(any(name.startswith(('plasma', 'gnome-shell', 'kde-standard', 'gdm3', 'sddm'))
                                 for name in packages[0]['depends']))
            data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(Path(tmp)/'out'/packages[0]['file'])])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                self.assertFalse(any('wayland-sessions' in m.name or 'default.target' in m.name for m in archive))

    def test_qt_vulkan_loader_configuration_has_one_owner_in_each_desktop(self):
        for profile in ('kde', 'gnome'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(build, 'shared_distribution', return_value=Path(tmp)):
                output = Path(tmp) / 'out'
                packages = layers.pack_de(profile, output)
                owners = []
                names = set()
                for package in packages:
                    data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile',
                                                    str(output / package['file'])])
                    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                        files = {m.name for m in archive if not m.isdir()}
                        self.assertFalse(names & files, 'Overlapping DE package ownership')
                        names.update(files)
                        path = './etc/environment.d/60-reimuks-qt-vulkan.conf'
                        if path in files:
                            owners.append(package['package'])
                            text = archive.extractfile(path).read().decode()
                            self.assertIn('QT_VULKAN_LIB=${QT_VULKAN_LIB:-libvulkan.so.1}', text)
                self.assertEqual(owners, ['reimuks-de-common'])

    def test_board_packages_have_disjoint_files_and_no_context_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);board=base/'board';(board/'rootfs').mkdir(parents=True)
            config=json.loads((ROOT/'config/boards/w202ds/packages.json').read_text())
            (board/'rootfs/packages.json').write_text(json.dumps(config))
            policy={'schema':1,'common':{},'desktop_common':{},'profiles':{'desktop/kde':{'desktop_common':True}}}
            (board/'rootfs/policy.json').write_text(json.dumps(policy))
            context=base/'context'
            for name in config['profiles']['kde']['preparer_inputs']:
                p=context/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('borrowed distro input')
            def install(root,profile,board,only):
                target=root/'usr/libexec'/only;target.parent.mkdir(parents=True);target.write_text('payload')
            def prepare(root,*args,**kw):
                p=root/'etc/skel/.config/integration';p.parent.mkdir(parents=True);p.write_text('generated board policy')
            with patch.object(build,'board_directory',return_value=board), \
                 patch.object(build,'distribution_build',return_value=base), \
                 patch.object(layers,'install_rootfs',side_effect=install), \
                 patch.object(layers,'prepare_rootfs',side_effect=prepare):
                manifest=layers.pack_board('kde',context,base/'out')
            owned=set()
            for p in manifest['packages']:
                data=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(base/'out'/p['file'])])
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    names={m.name for m in archive if not m.isdir()}
                self.assertFalse(owned & names)
                self.assertNotIn('./var/lib/dpkg/status',names)
                self.assertFalse(any('usr/share/plasma' in n for n in names))
                owned.update(names)
            self.assertIn('./etc/skel/.config/integration',owned)


if __name__=='__main__':
    unittest.main()

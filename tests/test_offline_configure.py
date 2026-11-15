"""Offline package setup must not enumerate host hardware or repeat completed unpacking."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import build


class OfflineConfigure(unittest.TestCase):
    def test_rootfs_runner_has_no_host_sysfs(self):
        with patch.object(build, 'run') as run:
            build.proot(Path('/example/rootfs'), ['/bin/true'])
            args = run.call_args.args[0]
            self.assertNotIn('/sys', args)
            self.assertEqual(run.call_args.kwargs['env']['SYSTEMD_OFFLINE'], '1')
            self.assertEqual(run.call_args.kwargs['env']['HOME'], '/root')
            self.assertFalse(any(k.startswith('XDG_') for k in run.call_args.kwargs['env']))

    def test_resume_retries_configuration_without_unpacking_complete_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);tree=base/'server';root=tree/'rootfs';work=tree/'work'
            (root/'var/lib/dpkg').mkdir(parents=True);work.mkdir()
            (work/'fakeroot.state').touch()
            states=['installed','unpacked','half-configured','half-installed']
            (root/'var/lib/dpkg/status').write_text('\n\n'.join('Package: pkg%d\nVersion: 1\nStatus: install ok %s'%(i,status) for i,status in enumerate(states)))
            candidates={('pkg%d'%i,'arm64'):('1',base/('pkg%d.deb'%i)) for i in range(len(states))}
            with patch.object(build,'load_accounts'), patch.object(build,'check_rootfs'), patch.object(build,'profile_directory',return_value=tree), patch.object(build,'distribution_build',return_value=base), patch.object(build,'cached_packages',return_value=candidates), patch.object(build,'proot'), patch.object(build,'apply_accounts'):
                build.configure('server')
            self.assertEqual((work/'unpack-list').read_text(),'pkg3.deb\n')

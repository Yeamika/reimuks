"""Offline USB tests; no real sysfs, USB role or gadget is changed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEVICES = ROOT/'devices/w202ds/kernel/Devices'
SOURCE = ROOT/'devices/w202ds/desktop/common/device-controls/source'


class UsbControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = os.environ.get('W202_NATIVE_CC') or shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('Native compiler required')
        cls.out = ROOT/'build/device-controls/tests'
        cls.out.mkdir(parents=True, exist_ok=True)
        for name, source in [('usb', DEVICES/'usb3/userspace/source/w202-usb-control.c'),
                             ('usb-settings', SOURCE/'usb-settings.c')]:
            subprocess.run([cc, '-std=gnu11', '-DW202_TESTING', '-Os',
                            '-I'+str(DEVICES/'userspace-common/source'), str(source),
                            '-o', str(cls.out/name)], check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sys = self.root/'sys'
        self.commands = self.root/'commands/usr/libexec'
        self.commands.mkdir(parents=True)
        self.env = dict(os.environ, W202_SYSFS_ROOT=str(self.sys),
                        W202_COMMAND_ROOT=str(self.root/'commands'), W202_TEST_ROOT='1',
                        W202_RUNTIME_ROOT=str(self.root), W202_CONFIG_ROOT=str(self.root/'config'))
        self.log = self.root/'calls'

    def run_tool(self, tool, *args):
        return subprocess.run([str(self.out/tool), *args], env=self.env,
                              capture_output=True, text=True)

    def stub(self, name, text):
        p = self.commands/name
        p.write_text('#!'+sys.executable+'\n'+text)
        p.chmod(0o755)

    def test_unknown_and_unprivileged_rejected_before_effects(self):
        self.assertNotEqual(self.run_tool('usb', 'apply', 'bad', '1', 'acm').returncode, 0)
        self.env['W202_TEST_ROOT'] = '0'
        self.assertNotEqual(self.run_tool('usb-settings', 'usb-auto-1-3').returncode, 0)
        self.assertFalse((self.root/'config').exists())

    def test_actual_roles_and_ambiguity_are_not_requested_roles(self):
        p = self.sys/'class/typec/port0'
        p.mkdir(parents=True)
        for key, value in {'port_type':'[dual] source sink', 'data_role':'[device] host', 'power_role':'[sink] source'}.items():
            (p/key).write_text(value)
        data = json.loads(self.run_tool('usb', 'status').stdout)
        self.assertEqual(data['port_type'], 'dual')
        self.assertEqual(data['data_role'], 'device')
        self.assertIsNone(data['bound'])
        p = self.sys/'class/typec/port1'
        p.mkdir()
        (p/'port_type').write_text('dual')
        self.assertFalse(json.loads(self.run_tool('usb', 'status').stdout)['available'])

    def test_save_intent_failure_readback_and_reapply(self):
        self.stub('w202-usb-control', f'''import json,sys,pathlib
with open({str(self.log)!r},'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1]=='status': print('{{"ok":true,"port_type":"sink","bound":false}}')
else: sys.exit(1)
''')
        result = self.run_tool('usb-settings', 'usb-host-1-2')
        self.assertNotEqual(result.returncode, 0)
        data = json.loads(self.run_tool('usb-settings', 'status').stdout)
        self.assertEqual(data['requested_mode'], 'host')
        self.assertFalse(data['acm'])
        self.assertTrue(data['ncm'])
        self.assertEqual(data['actual']['port_type'], 'sink')
        self.run_tool('usb-settings', 'reapply')
        self.assertIn(['rebind','host','1','ncm'], [json.loads(x) for x in self.log.read_text().splitlines()])

    def test_native_dispatch_host_inhibits_device_and_rebind_skips_role(self):
        for name in ['w202-usb-role','w202-usb-gadget']:
            self.stub(name, f'''import os,sys,json
with open({str(self.log)!r},'a') as f: f.write(json.dumps([sys.argv[0].split('/')[-1],sys.argv[1:],os.environ.get('USB_ENABLED'),os.environ.get('USB_FUNCTIONS')])+'\\n')
''')
        self.assertEqual(self.run_tool('usb','apply','host','1','ncm').returncode, 0)
        calls = [json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertEqual(calls[-1][2:], ['0','ncm'])
        self.log.unlink()
        self.assertEqual(self.run_tool('usb','rebind','auto','1','acm,ncm').returncode, 0)
        self.assertNotIn('w202-usb-role', self.log.read_text())

    def test_gadget_combinations_disable_preserve_and_foreign_function(self):
        # Run an isolated copy, replacing hardware paths and mount only.
        text = (DEVICES/'usb3/userspace/rootfs/usr/libexec/w202-usb-gadget').read_text()
        text = text.replace('/sys/', str(self.sys)+'/').replace('/sys\\n', str(self.sys)+'\\n')
        text = text.replace('/etc/default/w202-usb-gadget', str(self.root/'no-defaults'))
        start = text.index('mount_configfs() {')
        end = text.index('\nconfigure_gadget()', start)
        text = text[:start]+'mount_configfs() { return 0; }\n'+text[end:]
        script = self.root/'gadget'
        script.write_text(text)
        g = self.sys/'kernel/config/usb_gadget/w202ds'
        (g/'configs/c.1').mkdir(parents=True)
        (g/'functions/acm.GS0').mkdir(parents=True)
        (g/'functions/ncm.usb0').mkdir(parents=True)
        (self.sys/'class/udc/controller').mkdir(parents=True)
        (self.sys/'class/net/usb0').mkdir(parents=True)
        (g/'idVendor').write_text('0x1d6b')
        (g/'UDC').write_text('controller')
        for name in ['acm.GS0', 'ncm.usb0']:
            (g/'configs/c.1'/name).symlink_to(g/'functions'/name)
        def run(mask='acm,ncm', enabled='1'):
            return subprocess.run(['sh',str(script)], env=dict(self.env, USB_FUNCTIONS=mask, USB_ENABLED=enabled), capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        self.assertEqual(run('acm').returncode, 0)
        self.assertFalse((g/'configs/c.1/ncm.usb0').exists())
        self.assertEqual(run('ncm').returncode, 0)
        self.assertFalse((g/'configs/c.1/acm.GS0').exists())
        self.assertTrue((g/'configs/c.1/ncm.usb0').is_symlink())
        self.assertEqual(run(enabled='0').returncode, 0)
        self.assertEqual((g/'UDC').read_text().strip(), '')
        (g/'UDC').write_text('controller')
        (g/'configs/c.1/foreign').symlink_to(g/'functions/ncm.usb0')
        self.assertNotEqual(run().returncode, 0)
        self.assertEqual((g/'UDC').read_text(), 'controller')


if __name__ == '__main__':
    unittest.main()

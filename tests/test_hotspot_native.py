"""Test the C Wi-Fi helper against a fake NetworkManager command boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_usb_controls import ROOT, DEVICES, SOURCE


class NativeHotspot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = os.environ.get('W202_NATIVE_CC')
        if not cc:
            raise unittest.SkipTest('Set W202_NATIVE_CC')
        cls.binary = ROOT/'build/device-controls/tests/hotspot'
        cls.binary.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([cc, '-std=gnu11', '-DW202_TESTING', '-Os',
                        '-I'+str(DEVICES/'userspace-common/source'), '-I'+str(SOURCE),
                        str(SOURCE/'hotspot.c'), '-o', str(cls.binary)], check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root/'state'
        self.log = self.root/'log'
        cmd = self.root/'commands/usr/bin/busctl'
        cmd.parent.mkdir(parents=True)
        cmd.write_text('#!'+sys.executable+'\n'+r'''
import json,os,sys,pathlib
p=pathlib.Path(os.environ['FAKE_STATE']); s=json.loads(p.read_text()); a=sys.argv
with open(os.environ['FAKE_LOG'],'a') as f: f.write(json.dumps(a[1:])+'\n')
def typed(t,v): return {'type':t,'data':v}
def prop(t,v): return typed(t,v)
if 'get-property' in a:
 key=a[-1]; print(json.dumps(typed('b',s.get(key,True))))
elif 'Set' in a:
 key=a[-3]; value=a[-1]=='true'; s[key]=value; print('{}')
elif 'GetDeviceByIpIface' in a: print(json.dumps(typed('o',['/device'])))
elif 'GetAll' in a:
 if a[-1].endswith('.Wireless'): v={'Mode':prop('u',s['mode'])}
 elif a[-1].endswith('.Connection.Active'): v={'State':prop('u',2),'Uuid':prop('s','uuid')}
 else: v={'State':prop('u',100 if s['active'] else 30),'Managed':prop('b',True),'Autoconnect':prop('b',s['Autoconnect']),'ActiveConnection':prop('o','/active' if s['active'] else '/')}
 print(json.dumps(typed('a{sv}',[v])))
elif 'Disconnect' in a: s['active']=False; print('{}')
else: sys.exit(2)
p.write_text(json.dumps(s))
''')
        cmd.chmod(0o755)
        self.env = dict(os.environ, W202_COMMAND_ROOT=str(self.root/'commands'),
                        XDG_RUNTIME_DIR=str(self.root), FAKE_STATE=str(self.state), FAKE_LOG=str(self.log))
        self.state.write_text(json.dumps({'WirelessEnabled':True,'mode':3,'active':True,'Autoconnect':True}))

    def call(self, action):
        return subprocess.run([str(self.binary), action], env=self.env, capture_output=True, text=True)

    def test_ap_stop_and_radio_on_stay_idle(self):
        for action in ['restore','radio-on']:
            result=self.call(action)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertEqual(json.loads(result.stdout)['mode'],'idle')
        calls=[json.loads(x) for x in self.log.read_text().splitlines()]
        disconnect=next(i for i,x in enumerate(calls) if 'Disconnect' in x)
        inhibit=next(i for i,x in enumerate(calls) if 'Set' in x and x[-3:] == ['Autoconnect','b','false'])
        self.assertLess(inhibit,disconnect)
        self.assertNotIn('Update',self.log.read_text())

    def test_sta_and_radio_off(self):
        result=self.call('sta')
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertEqual(json.loads(result.stdout)['mode'],'sta')
        result=self.call('radio-off')
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertEqual(json.loads(result.stdout)['mode'],'off')
        self.assertFalse(json.loads(self.state.read_text())['Autoconnect'])

    def test_status_is_readonly_and_bad_action_has_no_io(self):
        before=self.state.read_text()
        self.assertEqual(json.loads(self.call('status').stdout)['mode'],'ap')
        self.assertEqual(before,self.state.read_text())
        self.log.unlink()
        self.assertNotEqual(self.call('arbitrary').returncode,0)
        self.assertFalse(self.log.exists())


if __name__=='__main__':
    unittest.main()

"""Compile and exercise the native controls with isolated command/hardware fakes."""
import importlib.util
import json
import os
from pathlib import Path
import random
import pty
import tty
import threading
import signal
import struct
import time
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from output_paths import board_root
DEVICES = ROOT/'devices/w202ds/kernel/Devices'
SOURCE = ROOT/'devices/w202ds/overlays/w202ds-hardwarepack2/src/device-controls/source'
KDE = ROOT/'devices/w202ds/overlays/w202ds-kde-hardwareuipack/src/kde/session'
GNOME = ROOT/'devices/w202ds/overlays/w202ds-gnome-hardwareuipack/src/gnome/session'


class NativeControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = os.environ.get('W202_NATIVE_CC') or shutil.which('cc')
        if not cls.cc:
            raise unittest.SkipTest('Set W202_NATIVE_CC to a native C compiler')
        cls.out = board_root('w202ds')/'device-controls/tests'
        cls.out.mkdir(parents=True, exist_ok=True)
        include = DEVICES/'userspace-common/source'
        flags = ['-std=gnu11', '-O1', '-g', '-DW202_TESTING', '-Wall', '-Wextra',
                 '-Werror', '-Wno-error=unused-result', '-Wno-unused-function', '-Wno-misleading-indentation',
                 '-I'+str(include), '-I'+str(SOURCE)]
        sources = {
            'controls': [SOURCE/'controls.c', SOURCE/'network.c'],
            'kde': [KDE/'hardware-controls.c'],
            'gnome': [GNOME/'controls.c'],
            'gnss-control': [SOURCE/'gnss-control.c'],
            'power': [DEVICES/'charging/userspace/source/w202-power-control.c'],
            'torch': [DEVICES/'camera/userspace/source/w202-torch-control.c'],
            'json': [ROOT/'tests/native/test-json.c'],
            'protocol': [ROOT/'tests/native/test-gnss.c'],
            'hall': [ROOT/'tests/native/test-hall.c'],
            'hotspot': [SOURCE/'hotspot.c'],
            'gnss-session': [DEVICES/'wcn/userspace/gnss/w202ds-gnss.c'],
            'storage': [ROOT/'tests/native/test-storage.c'],
            'bluetooth-radio': [ROOT/'tests/native/test-bluetooth-radio.c'],
        }
        flags += ['-I'+str(DEVICES/'wcn/userspace/gnss'),
                  '-I'+str(DEVICES/'hall/userspace/source'),
                  '-I'+str(DEVICES/'modem/userspace/runtime')]
        for name, files in sources.items():
            subprocess.run([cls.cc, *flags, *map(str, files), '-o', str(cls.out/name)], check=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.commands = self.path/'commands'
        self.log = self.path/'calls.jsonl'
        self.state = {'power': {'available': {'fast_charge': True, 'charging': True},
                      'fast_charge': False, 'separation': True, 'protocol': 'PD'},
                      'gnss': {'power_requested': False}, 'torch': {'brightness': 0, 'maximum': 8},
                      'rotation': {'enabled': True, 'tablet_mode': False}}
        self.state_path = self.path/'state.json'
        self.env = dict(os.environ, W202_COMMAND_ROOT=str(self.commands),
                        W202_FAKE_STATE=str(self.state_path), W202_FAKE_LOG=str(self.log),
                        W202_SYSFS_ROOT=str(self.path/'sys'), XDG_RUNTIME_DIR=str(self.path))
        stub = '''#!INTERPRETER
import json, os, pathlib, sys
s=json.loads(pathlib.Path(os.environ['W202_FAKE_STATE']).read_text())
with open(os.environ['W202_FAKE_LOG'],'a') as f: f.write(json.dumps(sys.argv)+'\\n')
name=pathlib.Path(sys.argv[0]).name
if name=='busctl':
    if s.get('no_bus'): sys.exit(1)
    if 'GetManagedObjects' in sys.argv:
        print(json.dumps({'type':'a{oa{sa{sv}}}', 'data':[{'/org/bluez/hci0':{'org.bluez.Adapter1':{'Powered':{'type':'b','data':False}}}}]}))
    elif 'get-property' in sys.argv: print(json.dumps({'type':'b','data':[True]}))
    else: print('{}')
elif name=='pkexec': sys.exit(1 if s.get('denied') else 0)
elif name=='w202-device-controls': print(json.dumps(s['shared'])); sys.exit(0 if s['shared'].get('ok') else 1)
elif name=='w202-rotation': print(json.dumps(s['rotation']))
elif name=='w202-tablet-mode': pass
elif name=='gsettings':
    if s.get('settings_missing'): sys.exit(1)
    operation,schema,key=sys.argv[1:4]
    values=s.setdefault('settings',{'orientation-lock':False,'screen-keyboard-enabled':False})
    if operation=='writable': print('false' if s.get('settings_readonly') else 'true')
    elif operation=='get': print('true' if values[key] else 'false')
    elif operation=='set':
        if s.get('settings_denied'): sys.exit(1)
        if not s.get('settings_ignored'): values[key]=sys.argv[4]=='true'
        pathlib.Path(os.environ['W202_FAKE_STATE']).write_text(json.dumps(s))
elif name=='systemctl':
    if 'show' in sys.argv: print(s.get('service','inactive'))
else:
    key={'w202-power-control':'power','w202-gnss-control':'gnss','w202-torch-control':'torch'}[name]
    if s.get('no_'+key):sys.exit(1)
    print(json.dumps(s[key]))
'''.replace('INTERPRETER', sys.executable)
        for name in ('usr/bin/busctl','usr/bin/pkexec','usr/bin/systemctl','usr/bin/w202-rotation','usr/bin/gsettings',
                     'usr/libexec/w202-power-control','usr/libexec/w202-gnss-control',
                     'usr/libexec/w202-torch-control','usr/libexec/w202-device-controls',
                     'usr/libexec/w202-tablet-mode'):
            p = self.commands/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(stub)
            p.chmod(0o755)

    def run_control(self, name, action):
        self.state_path.write_text(json.dumps(self.state))
        p = subprocess.run([str(self.out/name), action], env=self.env,
                           capture_output=True, text=True, timeout=15)
        return p, json.loads(p.stdout)

    def test_bluetooth_restore_unblocks_only_its_controller_and_respects_hardware(self):
        directory = self.path/'sys/class/rfkill'
        devices = [('hci0', 'bluetooth'), ('hci1', 'bluetooth'),
                   ('phy0', 'wlan'), ('w202ds-gnss', 'gps')]
        for i, (name, kind) in enumerate(devices):
            node = directory/f'rfkill{i}'
            node.mkdir(parents=True)
            for key, value in [('name', name), ('type', kind), ('soft', '1'), ('hard', '0')]:
                (node/key).write_text(value)
        binary = str(self.out/'bluetooth-radio')
        result = subprocess.run([binary, '/org/bluez/hci0'], env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((directory/'rfkill0/soft').read_text(), '0')
        for i in range(1, len(devices)):
            self.assertEqual((directory/f'rfkill{i}/soft').read_text(), '1')
        (directory/'rfkill0/soft').write_text('1')
        (directory/'rfkill0/hard').write_text('1')
        self.assertNotEqual(subprocess.run([binary, '/org/bluez/hci0'], env=self.env).returncode, 0)
        self.assertEqual((directory/'rfkill0/soft').read_text(), '1')
        self.assertNotEqual(subprocess.run([binary, '/org/bluez/hci0/../hci1'], env=self.env).returncode, 0)

    def test_missing_is_not_off_and_independent_controls_survive(self):
        self.state.update(no_power=True, no_bus=True)
        p, v = self.run_control('controls', 'status')
        self.assertEqual(p.returncode, 0)
        self.assertIsNone(v['states']['wifi'])
        self.assertIsNone(v['states']['fast'])
        self.assertFalse(v['states']['gnss'])
        self.assertTrue(v['capabilities']['gnss']['available'])
        self.assertFalse(v['capabilities']['fast']['available'])

    def test_unknown_and_session_actions_do_not_run_commands(self):
        for action in ('tablet-on', 'rotation-off', 'torch-9', 'wifi-maybe', 'bad-on'):
            p, v = self.run_control('controls', action)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(v['ok'])
        self.assertFalse(self.log.exists())

    def test_fixed_helper_dispatch_and_authorization_failure(self):
        for action, command in [('gnss-on','start'),('separation-on','charge-inhibit'),
                                ('torch-8','8'),('mode-pps','mode-pps')]:
            self.log.unlink(missing_ok=True)
            p, v = self.run_control('controls', action)
            self.assertEqual(p.returncode, 0)
            first=json.loads(self.log.read_text().splitlines()[0])
            self.assertEqual(first[1], '/usr/libexec/'+('w202-gnss-control' if action=='gnss-on' else
                             'w202-torch-control' if action=='torch-8' else 'w202-power-control'))
            self.assertEqual(first[2], command)
        self.state['denied']=True
        p, v=self.run_control('controls','gnss-on')
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(v['ok'])

    def test_kde_keeps_shared_fields_and_session_state(self):
        _, self.state['shared'] = self.run_control('controls','status')
        p,v=self.run_control('kde','wifi-off')
        self.assertEqual(p.returncode,0)
        self.assertTrue(v['states']['rotation'])
        self.assertFalse(v['states']['tablet'])
        self.assertEqual(v['power'],self.state['power'])
        p,v=self.run_control('kde','tablet-on')
        self.assertEqual(p.returncode,0)
        calls=[json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertTrue(any(x[1:]==['on'] and x[0].endswith('w202-tablet-mode') for x in calls))

    def test_de_adapters_keep_the_same_hardware_payload_and_future_fields(self):
        _, self.state['shared'] = self.run_control('controls', 'status')
        self.state['shared']['extension'] = {'version': 2, 'values': [None, 17]}
        for name in ('kde', 'gnome'):
            with self.subTest(adapter=name):
                p, value = self.run_control(name, 'wifi-off')
                self.assertEqual(p.returncode, 0, p.stderr)
                for field in ('power', 'torch', 'usb', 'protocol', 'extension'):
                    self.assertEqual(value[field], self.state['shared'][field])
                for key, state in self.state['shared']['states'].items():
                    self.assertEqual(value['states'][key], state)

    def test_gnome_rotation_uses_the_inverse_lock_and_keyboard_uses_gnome(self):
        _, self.state['shared'] = self.run_control('controls', 'status')
        self.log.unlink()
        for action, key, expected in (('rotation-off', 'orientation-lock', True),
                                      ('rotation-on', 'orientation-lock', False),
                                      ('keyboard-on', 'screen-keyboard-enabled', True),
                                      ('keyboard-off', 'screen-keyboard-enabled', False)):
            with self.subTest(action=action):
                p, value = self.run_control('gnome', action)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(self.state_path.read_text())['settings'][key], expected)
                self.assertIsNone(value['states']['tablet'])
                if key == 'orientation-lock':
                    self.assertEqual(value['states']['rotation'], not expected)
                else:
                    self.assertEqual(value['states']['keyboard'], expected)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertFalse(any(any('org.kde' in arg or 'w202-rotation' in arg for arg in call) for call in calls))
        self.assertFalse(any(call[0].endswith('pkexec') for call in calls))

    def test_gnome_missing_or_rejected_setting_is_not_reported_as_success(self):
        _, self.state['shared'] = self.run_control('controls', 'status')
        self.state['settings_missing'] = True
        p, value = self.run_control('gnome', 'status')
        self.assertEqual(p.returncode, 0)
        self.assertIsNone(value['states']['rotation'])
        self.assertIsNone(value['states']['keyboard'])
        self.assertFalse(value['capabilities']['rotation']['available'])
        self.state.pop('settings_missing')
        for failure in ('settings_readonly', 'settings_denied', 'settings_ignored'):
            with self.subTest(failure=failure):
                self.state[failure] = True
                p, value = self.run_control('gnome', 'keyboard-on')
                self.assertNotEqual(p.returncode, 0)
                self.assertFalse(value['ok'])
                self.state.pop(failure)

    def test_gnome_does_not_fake_a_manual_tablet_override(self):
        p, value = self.run_control('gnome', 'tablet-on')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(value['ok'])
        self.assertFalse(self.log.exists())

    def test_adapters_reject_malformed_shared_status(self):
        for shared in ({'ok': False}, {'ok': True, 'states': [], 'capabilities': {}}):
            self.state['shared'] = shared
            for name in ('kde', 'gnome'):
                with self.subTest(adapter=name, shared=shared):
                    p, value = self.run_control(name, 'status')
                    self.assertNotEqual(p.returncode, 0)
                    self.assertFalse(value['ok'])

    def test_gnss_does_not_steal_another_session(self):
        self.env['W202_TEST_ROOT']='1'
        radio=self.path/'sys/class/rfkill/rfkill0'
        radio.mkdir(parents=True)
        (radio/'name').write_text('w202ds-gnss\n')
        (radio/'soft').write_text('0\n')
        p,v=self.run_control('gnss-control','start')
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(v['ok'])
        calls=[json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertFalse(any('start' in x for x in calls))
        p,v=self.run_control('gnss-control','stop')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('release',v['error'])

    def test_torch_uses_driver_bounds_and_reads_actual_brightness(self):
        led=self.path/'sys/class/leds/white:torch'
        led.mkdir(parents=True)
        (led/'max_brightness').write_text('8\n')
        (led/'brightness').write_text('0\n')
        p,v=self.run_control('torch','8')
        self.assertEqual(p.returncode,0)
        self.assertEqual(v['brightness'],8)
        p,v=self.run_control('torch','9')
        self.assertNotEqual(p.returncode,0)
        self.assertEqual((led/'brightness').read_text(),'8\n')

    def test_protocol_debounce_json_and_timeout(self):
        env=dict(self.env)
        env.pop('W202_COMMAND_ROOT')
        for name in ('protocol','hall','json'):
            subprocess.run([str(self.out/name)],check=True,env=env,capture_output=True,timeout=10)

    def test_json_parser_against_standard_library(self):
        rng=random.Random(42)
        valid=[None,True,False,0,-17,1.25,'escaped\\"\n',{'a':[1,False,{'b':None}]}]
        for value in valid:
            text=json.dumps(value)
            self.assertEqual(subprocess.run([str(self.out/'json'),text]).returncode,0)
        for _ in range(100):
            text=''.join(rng.choice('{}[],:"012tnf x\\') for _ in range(rng.randrange(1,60)))
            try:json.loads(text); expected=0
            except ValueError:expected=1
            self.assertEqual(subprocess.run([str(self.out/'json'),text]).returncode,expected,repr(text))

    def test_power_status_matches_reference_for_realistic_fixture(self):
        path=DEVICES/'charging/userspace/tests/test-controls.py'
        spec=importlib.util.spec_from_file_location('power_fixture',path)
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        fixture=fixtures.PowerControlsTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for change in (None, 'disconnected', 'unknown_profile', 'missing_current'):
            if change=='disconnected': fixture.put(fixture.supplies/'w202-usb-c/online','0')
            if change=='unknown_profile': fixture.put(fixture.port/'select_usb_power_delivery','[pd99] pd8')
            if change=='missing_current': (fixture.supplies/'w202-battery/current_now').unlink()
            self.env['W202_SYSFS_ROOT']=str(fixture.sysfs)
            p,v=self.run_control('power','status')
            self.assertEqual(p.returncode,0)
            self.assertEqual(v,fixture.control.status(),change)

    def test_gnss_protocol_session_releases_power_after_signal(self):
        path=DEVICES/'wcn/userspace/gnss/tests/reference_gnss.py'
        spec=importlib.util.spec_from_file_location('gnss_reference',path)
        reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
        radio=self.path/'sys/class/rfkill/rfkill0'
        radio.mkdir(parents=True)
        (radio/'name').write_text('w202ds-gnss\n')
        (radio/'soft').write_text('1\n')
        runtime=self.path/'run'
        (runtime/'lock').mkdir(parents=True)
        master,slave=pty.openpty()
        self.addCleanup(os.close,master);self.addCleanup(os.close,slave)
        tty.setraw(slave)
        env=dict(self.env,W202_GNSS_DEVICE=os.ttyname(slave),W202_RUNTIME_ROOT=str(runtime))
        seen=[];ready=threading.Event();done=threading.Event()
        def firmware():
            parser=reference.FrameParser()
            import select
            while not done.is_set():
                if not select.select([master],[],[],0.1)[0]:continue
                try: data=os.read(master,4096)
                except OSError:return
                for kind,sub,payload in parser.feed(data):
                    seen.append((kind,sub,payload))
                    if (kind,sub)==(4,1):os.write(master,reference.encode(4,1,payload))
                    if (kind,sub)==(7,4):
                        os.write(master,reference.encode(8,5))
                        ready.set()
                    if (kind,sub)==(7,3):os.write(master,reference.encode(8,3))
        worker=threading.Thread(target=firmware,daemon=True);worker.start()
        proc=subprocess.Popen([str(self.out/'gnss-session'),'--duration','30'],env=env,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(ready.wait(5))
            proc.send_signal(signal.SIGTERM)
            out,err=proc.communicate(timeout=8)
            self.assertEqual(proc.returncode,143,err)
            self.assertEqual((radio/'soft').read_text(),'1\n')
            self.assertIn((7,3,b''),seen)
            self.assertIn((4,1,b'\x02\x00'),seen)
            self.assertEqual(out,'')
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()
            done.set();worker.join(1)

    def test_modem_nv_checksum_and_symlink_rejection(self):
        image=self.path/'nv.img'
        header=struct.pack('<4I',0x4e56,4096,0xffff,0x65)+bytes(496)
        image.write_bytes(header+bytes(4096)+bytes(3584))
        self.assertEqual(subprocess.run([str(self.out/'storage'),str(image),'4096','8192']).returncode,0)
        raw=bytearray(image.read_bytes());raw[512]=1;image.write_bytes(raw)
        self.assertNotEqual(subprocess.run([str(self.out/'storage'),str(image),'4096','8192']).returncode,0)
        link=self.path/'link';link.symlink_to(image)
        self.assertNotEqual(subprocess.run([str(self.out/'storage'),str(link),'4096','8192']).returncode,0)


if __name__=='__main__':
    unittest.main()

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

loader=importlib.machinery.SourceFileLoader("dispatcher",str(Path(__file__).parent / "tests/reference/90-w202-hotspot-scan"))
spec=importlib.util.spec_from_loader(loader.name,loader)
dispatcher=importlib.util.module_from_spec(spec)
loader.exec_module(dispatcher)


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.uuid="a08ef631-1d89-4a93-9fd2-560367395321"
    def result(self,text):
        return SimpleNamespace(returncode=0,stdout=text,stderr="")
    def test_other_devices_events_and_profiles_do_not_run_commands(self):
        with patch.object(dispatcher.subprocess,"run") as run:
            for interface,action,identifier in [("usb0","up",self.uuid),
                ("wlan0","down",self.uuid),("wlan0","up","some-other-uuid")]:
                self.assertFalse(dispatcher.drain(interface,action,identifier))
            run.assert_not_called()
    def test_delayed_event_does_not_scan_a_new_connection(self):
        with patch.object(dispatcher.subprocess,"run",side_effect=[self.result("another-uuid"),self.result("ap")]) as run:
            self.assertFalse(dispatcher.drain("wlan0","up",self.uuid))
            self.assertEqual(run.call_count,2)
    def test_station_mode_does_not_run_scan(self):
        with patch.object(dispatcher.subprocess,"run",side_effect=[self.result(self.uuid),self.result("infrastructure")]) as run:
            self.assertFalse(dispatcher.drain("wlan0","up",self.uuid))
            self.assertEqual(run.call_count,2)
    def test_managed_ap_finishes_with_one_manual_scan(self):
        with patch.object(dispatcher.subprocess,"run",side_effect=[self.result(self.uuid),self.result("ap"),self.result("OK\n")]) as run:
            self.assertTrue(dispatcher.drain("wlan0","up",self.uuid))
            self.assertEqual(run.call_count,3)
            self.assertEqual(run.call_args.args[0],["/usr/sbin/wpa_cli","-i","wlan0","scan","TYPE=ONLY"])


if __name__=="__main__":
    unittest.main(verbosity=2)

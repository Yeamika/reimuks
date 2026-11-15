"""Mode selection must prevent autoconnect and preserve unrelated transports."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader("switch", str(Path(__file__).parent / "tests/reference/w202-hotspot-switch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
switch = importlib.util.module_from_spec(spec)
loader.exec_module(switch)


class Network:
    def __init__(self, radio=True, mode=2, active=True, autoconnect=True):
        self.radio, self.mode, self.active = radio, mode, active
        self.autoconnect = autoconnect
        self.actions = []
    def manager(self):
        return {"WirelessEnabled": self.radio, "NetworkingEnabled": True}
    def device(self):
        return {"mode": self.mode, "State": 100 if self.active else 30,
                "Managed": True, "Autoconnect": self.autoconnect,
                "ActiveConnection": "/active/wifi" if self.active else "/",
                "active": {"Uuid": "6a4d8039-fd70-4a03-a9ca-f0a11c3dfba5", "State": 2} if self.active else {}}
    def set_radio(self, enabled):
        self.actions.append(("radio", enabled))
        self.radio = enabled
    def set_autoconnect(self, enabled):
        self.actions.append(("autoconnect", enabled))
        self.autoconnect = enabled
    def disconnect(self):
        self.actions.append(("disconnect", "wlan0"))
        self.active = False


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.state_patch = patch.object(switch, "STATE", Path(self.temp.name)/"state.json")
        self.state_patch.start()
    def tearDown(self):
        self.state_patch.stop()
        self.temp.cleanup()
    def saved_profile_network(self, mode="ap"):
        from unittest.mock import Mock
        network = Mock()
        network.device.return_value = {"active": {}}
        settings = {
            "connection": {"uuid": "a08ef631-1d89-4a93-9fd2-560367395321", "type": "802-11-wireless",
                           "interface-name": "wlan0", "autoconnect": False},
            "802-11-wireless": {"mode": mode, "band": "bg", "channel": 6},
            "802-11-wireless-security": {"key-mgmt": "sae"}}
        network.call.side_effect = lambda path, interface, method, *args: (
            (["/saved/ap"],) if method == "ListConnections" else (settings,))
        return network

    def test_saved_kde_profile_is_authoritative(self):
        network = self.saved_profile_network()
        with patch.object(switch.subprocess, "run") as run:
            path, identifier = switch.ensure_profile(network)
        self.assertEqual(path, "/saved/ap")
        self.assertEqual(identifier, "a08ef631-1d89-4a93-9fd2-560367395321")
        run.assert_not_called()
        self.assertEqual([c.args[2] for c in network.call.call_args_list],
                         ["ListConnections", "GetSettings"])

    def test_saved_unbound_ap_uses_explicit_activation_device(self):
        network = self.saved_profile_network()
        network.call.side_effect = [(["/saved/ap"],), ({
            "connection": {"uuid": "a08ef631-1d89-4a93-9fd2-560367395321", "type": "802-11-wireless",
                           "autoconnect": False},
            "802-11-wireless": {"mode": "ap"}},)]
        self.assertEqual(switch.ensure_profile(network)[0], "/saved/ap")

    def test_saved_station_profile_cannot_be_used_as_hotspot(self):
        with self.assertRaises(switch.SwitchError):
            switch.ensure_profile(self.saved_profile_network("infrastructure"))

    def test_no_profiles_does_not_create_defaults(self):
        from unittest.mock import Mock
        network = Mock()
        network.call.return_value = ([],)
        with self.assertRaisesRegex(switch.SwitchError, "Create an AP connection"):
            switch.ensure_profile(network)
        self.assertEqual([c.args[2] for c in network.call.call_args_list], ["ListConnections"])

    def test_several_profiles_require_explicit_selection(self):
        from unittest.mock import Mock
        network = Mock()
        network.device.return_value = {"active": {}}
        with patch.object(switch, "configured_access_points", return_value=[("/ap/a", "a"), ("/ap/b", "b")]):
            with self.assertRaisesRegex(switch.SwitchError, "Several AP connections"):
                switch.ensure_profile(network)
            network.device.return_value = {"active": {"Uuid": "b"}}
            self.assertEqual(switch.ensure_profile(network), ("/ap/b", "b"))

    def test_idle_blocks_reconnection_before_disconnecting_station(self):
        n = Network()
        self.assertEqual(switch.idle(n)["mode"], "idle")
        self.assertEqual(n.actions, [("autoconnect", False), ("disconnect", "wlan0")])
        self.assertTrue(n.radio)
    def test_stop_ap_does_not_restore_station(self):
        n = Network(mode=3)
        switch.save_state({"previous_uuid": "6a4d8039-fd70-4a03-a9ca-f0a11c3dfba5"})
        with patch.object(switch.subprocess, "run") as run:
            self.assertEqual(switch.restore(n)["mode"], "idle")
            run.assert_not_called()
        self.assertFalse(switch.STATE.exists())
    def test_master_off_disconnects_ap_and_disables_radio(self):
        n = Network(mode=3)
        self.assertEqual(switch.idle(n, radio=False)["mode"], "off")
        self.assertEqual(n.actions[-1], ("radio", False))
        self.assertFalse(n.autoconnect)
    def test_master_on_stays_idle(self):
        n = Network(radio=False, active=False)
        result = switch.idle(n, radio=True)
        self.assertEqual(result["mode"], "idle")
        self.assertTrue(result["radio"])
        self.assertFalse(n.autoconnect)
    def test_station_selection_stops_ap_before_allowing_autoactivation(self):
        n = Network(mode=3)
        self.assertEqual(switch.station(n)["mode"], "sta")
        self.assertEqual(n.actions, [("autoconnect", False), ("disconnect", "wlan0"),
                                     ("radio", True), ("autoconnect", True)])
    def test_idle_is_idempotent(self):
        n = Network(active=False, autoconnect=False)
        switch.idle(n)
        self.assertEqual(n.actions, [("autoconnect", False)])
    def test_manual_radio_off_is_respected_by_failure_cleanup(self):
        n = Network(radio=False, active=False)
        self.assertEqual(switch.restore(n, rollback=True)["mode"], "off")
        self.assertNotIn(("radio", True), n.actions)
    def test_prepare_blocks_autoactivation(self):
        n = Network(radio=False, active=False)
        self.assertTrue(switch.prepare(n)["ready"])
        self.assertEqual(n.actions, [("autoconnect", False), ("radio", True)])
    def test_prepare_rejects_existing_ap(self):
        with self.assertRaises(switch.SwitchError):
            switch.prepare(Network(mode=3))
    def test_status_uses_actual_ap_even_if_autoactivation_is_disabled(self):
        self.assertEqual(switch.status(Network(mode=3, autoconnect=False))["mode"], "ap")
    def test_explicit_station_connection_is_not_misreported_as_idle(self):
        self.assertEqual(switch.status(Network(mode=2, autoconnect=False))["mode"], "sta")
    def test_idle_propagates_permission_error_without_turning_radio_on(self):
        n = Network(radio=False)
        with patch.object(n, "set_autoconnect", side_effect=RuntimeError("denied")):
            with self.assertRaisesRegex(RuntimeError, "denied"):
                switch.idle(n, radio=True)
        self.assertEqual(n.actions, [])
    def test_disconnect_timeout_does_not_reenable_autoactivation(self):
        n = Network(mode=3)
        with patch.object(n, "disconnect"), patch.object(switch.time, "monotonic", side_effect=[0, 20]):
            with self.assertRaisesRegex(switch.SwitchError, "disconnect"):
                switch.idle(n, timeout=1)
        self.assertFalse(n.autoconnect)


if __name__ == "__main__":
    unittest.main(verbosity=2)

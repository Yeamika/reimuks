import QtQuick
import QtTest
import ".."

TestCase {
    name: "HotspotSwitcher"
    when: windowShown
    QtObject {
        id: config
        property string hotspotConnectionPath: ""
    }
    QtObject {
        id: backend
        property int createCount: 0
        property int stopCount: 0
        signal hotspotCreated()
        signal hotspotDisabled()
        function createHotspot() { createCount++; }
        function stopHotspot() {
            stopCount++;
            config.hotspotConnectionPath = "";
            hotspotDisabled();
        }
    }
    HotspotSwitcher {
        id: flow
        nmHandler: backend
        configuration: config
        pollingEnabled: false
    }
    SignalSpy {
        id: operations
        target: flow
        signalName: "operationRequested"
    }
    function init() {
        flow.stage = "idle";
        flow.mode = "sta";
        flow.radioEnabled = true;
        flow.pending = "";
        flow.lastError = "";
        flow.accessPointActive = false;
        flow.nativeHotspotActive = false;
        config.hotspotConnectionPath = "";
        backend.createCount = 0;
        backend.stopCount = 0;
        operations.clear();
    }
    function test_ap_can_start_with_radio_off() {
        flow.mode = "off";
        flow.radioEnabled = false;
        flow.start();
        compare(flow.stage, "preparing");
        compare(operations.signalArguments[0][0], "prepare");
    }
    function test_waits_for_ready_and_ignores_repeated_click() {
        flow.start();
        flow.start();
        compare(flow.stage, "preparing");
        compare(operations.count, 1);
        compare(backend.createCount, 0);
        verify(flow.suppressScanning);
        flow.completeOperation("prepare", {ok:true});
        compare(backend.createCount, 0);
        compare(flow.stage, "creating");
        compare(operations.signalArguments[1][0], "create");
        flow.completeOperation("create", {ok:true,active_path:"/active/hotspot"});
        compare(flow.stage, "verifying");
        compare(operations.signalArguments[2][0], "verify");
        flow.completeOperation("verify", {ok:true});
        verify(!flow.busy);
        verify(flow.suppressScanning);
    }
    function test_failed_prepare_does_not_create_ap_and_rolls_back() {
        flow.start();
        flow.completeOperation("prepare", {ok:false,error:"not ready"});
        compare(backend.createCount, 0);
        compare(flow.stage, "restoring");
        compare(operations.signalArguments[1][0], "radio-off");
        flow.completeOperation("radio-off", {ok:true, mode:"off", radio:false});
        verify(!flow.busy);
        verify(flow.suppressScanning);
    }
    function test_deactivation_during_verification_does_not_race_helper() {
        flow.start();
        flow.completeOperation("prepare", {ok:true});
        flow.completeOperation("create", {ok:true,active_path:"/active/hotspot"});
        const count = operations.count;
        backend.hotspotDisabled();
        compare(operations.count, count);
        flow.completeOperation("verify", {ok:false,error:"failed"});
        compare(operations.signalArguments[count][0], "radio-off");
        flow.completeOperation("radio-off", {ok:true, mode:"off", radio:false});
    }
    function test_stop_enters_idle_without_resuming_scans() {
        config.hotspotConnectionPath = "/active/hotspot";
        flow.stop();
        compare(flow.stage, "restoring");
        compare(backend.stopCount, 1);
        compare(operations.signalArguments[0][0], "radio-off");
        config.hotspotConnectionPath = "";
        backend.hotspotDisabled();
        compare(operations.count, 1);
        flow.completeOperation("radio-off", {ok:true, mode:"off", radio:false});
        verify(flow.suppressScanning);
    }
    function test_station_request_blocks_second_mode_request() {
        flow.selectMode("sta");
        flow.start();
        compare(operations.count, 1);
        compare(operations.signalArguments[0][0], "sta");
        flow.completeOperation("sta", {ok:true, mode:"sta", radio:true});
        compare(flow.mode, "sta");
        verify(!flow.suppressScanning);
    }
    function test_master_on_selects_neither_mode() {
        flow.setRadio(true);
        flow.completeOperation("radio-on", {ok:true, mode:"off", radio:false});
        compare(flow.mode, "idle");
        verify(flow.radioEnabled);
        verify(flow.suppressScanning);
    }
    function test_master_off_clears_ap_state() {
        config.hotspotConnectionPath = "/active/hotspot";
        flow.nativeHotspotActive = true;
        flow.setRadio(false);
        flow.completeOperation("radio-off", {ok:true, mode:"off", radio:false});
        compare(flow.mode, "off");
        compare(config.hotspotConnectionPath, "");
        verify(!flow.radioEnabled);
        verify(!flow.nativeHotspotActive);
    }
    function test_delayed_status_does_not_overwrite_inflight_request() {
        flow.selectMode("idle");
        flow.completeOperation("status", {ok:true, mode:"ap", radio:true});
        compare(flow.stage, "switching");
        compare(flow.mode, "sta");
    }
    function test_external_ap_suppresses_scans() {
        flow.accessPointActive = true;
        verify(flow.suppressScanning);
    }
}

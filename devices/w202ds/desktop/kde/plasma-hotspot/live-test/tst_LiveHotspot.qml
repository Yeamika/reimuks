import QtQuick
import QtTest
import org.kde.plasma.networkmanagement as PlasmaNM
import org.kde.plasma.plasma5support as Plasma5Support
import ".."

TestCase {
    name: "LiveHotspot"
    when: windowShown
    PlasmaNM.Handler { id: backend }
    PlasmaNM.WirelessStatus { id: wirelessStatus }
    HotspotSwitcher {
        id: flow
        nmHandler: backend
        configuration: PlasmaNM.Configuration
        accessPointActive: wirelessStatus.hotspotSSID.length > 0
        onOperationRequested: name => executor.connectSource("/usr/libexec/w202-hotspot-switch " + name)
        onFailed: message => console.warn("Hotspot flow:", message)
    }
    Plasma5Support.DataSource {
        id: executor
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            if (data["exit code"] === undefined) {
                return;
            }
            disconnectSource(sourceName);
            let result;
            try {
                result = JSON.parse(data["stdout"]);
            } catch (error) {
                result = {ok:false,error:"Invalid helper response"};
            }
            console.log("Operation", sourceName.split(" ").pop(), "ok", result.ok);
            flow.completeOperation(sourceName.split(" ").pop(), result);
        }
    }
    function test_native_hotspot_start_and_stop() {
        flow.setRadio(true);
        tryCompare(flow, "busy", false, 40000);
        compare(flow.lastError, "");
        compare(flow.mode, "idle");
        flow.start();
        tryCompare(flow, "busy", false, 65000);
        compare(flow.lastError, "");
        verify(!!PlasmaNM.Configuration.hotspotConnectionPath);
        verify(flow.suppressScanning);
        console.log("HOTSPOT_ACTIVE");
        wait(8000);
        verify(!!PlasmaNM.Configuration.hotspotConnectionPath);
        flow.stop();
        tryCompare(flow, "busy", false, 40000);
        compare(flow.lastError, "");
        verify(!PlasmaNM.Configuration.hotspotConnectionPath);
        compare(flow.mode, "idle");
        console.log("HOTSPOT_STOPPED_IDLE");
    }
}

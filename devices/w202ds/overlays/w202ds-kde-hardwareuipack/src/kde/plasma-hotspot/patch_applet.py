#!/usr/bin/python3
"""Apply the W202DS hotspot flow to the supported Plasma NM structure in a private applet copy."""
from pathlib import Path


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Unsupported Plasma NM source; refusing an ambiguous patch")
    return text.replace(before, after, 1)


def patch(root):
    ui = Path(root) / "contents/ui"
    path = ui / "main.qml"
    text = path.read_text()
    text = replace_once(text, "import QtQuick 2.2\n",
        "import QtQuick 2.2\nimport org.kde.plasma.plasma5support as Plasma5Support\n"
        "import org.kde.notification as KNotification\n")
    text = replace_once(text, "    property alias planeModeSwitchAction: planeAction\n",
        """    property alias planeModeSwitchAction: planeAction
    property alias hotspotSwitcher: hotspotFlow
    readonly property var scanHandler: scanHandlerLoader.item

    function requestWifiScan() {
        if (!hotspotSwitcher.suppressScanning && scanHandler) {
            scanHandler.requestScan();
        }
    }
""")
    text = replace_once(text, "    Timer {\n        id: scanTimer\n",
        """    PlasmaNM.WirelessStatus {
        id: hotspotWirelessStatus
    }

    HotspotSwitcher {
        id: hotspotFlow
        nmHandler: handler
        configuration: PlasmaNM.Configuration
        accessPointActive: hotspotWirelessStatus.hotspotSSID.length > 0
        pollingEnabled: mainWindow.expanded
        onOperationRequested: name => hotspotExecutor.connectSource("/usr/libexec/w202-hotspot-switch " + name)
        onFailed: message => {
            hotspotFailure.text = message;
            hotspotFailure.sendEvent();
        }
    }

    Plasma5Support.DataSource {
        id: hotspotExecutor
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
                result = {ok: false, error: i18n("The Wi-Fi switch helper did not respond.")};
            }
            hotspotSwitcher.completeOperation(sourceName.split(" ").pop(), result);
        }
    }

    KNotification.Notification {
        id: hotspotFailure
        componentName: "networkmanagement"
        eventId: "FailedToCreateHotspot"
        title: i18n("Wi-Fi mode switch failed")
        iconName: "dialog-warning"
    }

    // Destroying the scan handler also cancels its queued retry timers.
    Loader {
        id: scanHandlerLoader
        active: !hotspotSwitcher.suppressScanning
        sourceComponent: PlasmaNM.Handler {}
    }

    Timer {
        id: scanTimer
""")
    text = replace_once(text,
        "running: mainWindow.expanded && !PlasmaNM.Configuration.airplaneModeEnabled && !mainWindow.delayModelUpdates",
        "running: mainWindow.expanded && !PlasmaNM.Configuration.airplaneModeEnabled"
        " && !mainWindow.delayModelUpdates && !hotspotSwitcher.suppressScanning")
    text = replace_once(text, "onTriggered: handler.requestScan()", "onTriggered: mainWindow.requestWifiScan()")
    text = replace_once(text, "onTriggered: checked => {handler.enableWireless(checked)}",
        "onTriggered: checked => {hotspotSwitcher.setRadio(checked)}")
    path.write_text(text)

    path = ui / "PopupDialog.qml"
    text = replace_once(path.read_text(), "                handler.requestScan();", "                deferredScan.restart();")
    # Keep NM's live model across openings. Rebuilding it synchronously for every
    # tap delays the popup and discards the already available connection list.
    text = replace_once(text,
        """                if (full.connectionModel) {
                    full.connectionModel.destroy();
                    full.connectionModel = null;
                }""",
        """                deferredScan.stop();""")
    text = replace_once(text, "    Connections {\n        target: mainWindow\n",
        """    Timer {
        id: deferredScan
        interval: 300
        onTriggered: {
            if (mainWindow.expanded) mainWindow.requestWifiScan();
        }
    }

    Connections {
        target: mainWindow
""")
    path.write_text(text)

    path = ui / "Toolbar.qml"
    text = path.read_text()
    text = replace_once(text, "import QtQuick 2.2\n", "import QtQuick 2.2\nimport QtQuick.Controls as QQC2\n")
    text = replace_once(text, "running: handler.scanning || timer.running",
        "running: !!mainWindow.scanHandler?.scanning || timer.running")
    text = replace_once(text,
        "                    target: handler\n                    function onScanningChanged() {\n                        if (handler.scanning) {",
        "                    target: mainWindow.scanHandler\n                    function onScanningChanged() {\n"
        "                        if (mainWindow.scanHandler?.scanning) {")
    text = replace_once(text, "        visible: handler.hotspotSupported\n        checkable: true\n",
        "        visible: handler.hotspotSupported\n        checkable: true\n"
        "        enabled: !mainWindow.hotspotSwitcher.busy && !PlasmaNM.Configuration.airplaneModeEnabled\n")
    text = replace_once(text,
        """                checked = false
                handler.stopHotspot()
            } else {
                checked = true
                handler.createHotspot()""",
        """                mainWindow.hotspotSwitcher.stop()
            } else {
                mainWindow.hotspotSwitcher.start()""")
    text = replace_once(text, "            onToggled: handler.enableWireless(checked);",
        """            onToggled: {
                mainWindow.hotspotSwitcher.setRadio(checked);
                checked = Qt.binding(() => administrativelyEnabled && enabledConnections.wirelessEnabled);
            }""")
    text = replace_once(text, "            checked: administrativelyEnabled && enabledConnections.wirelessEnabled\n            enabled: administrativelyEnabled",
        "            checked: administrativelyEnabled && enabledConnections.wirelessEnabled\n"
        "            enabled: administrativelyEnabled && !mainWindow.hotspotSwitcher.busy")
    text = replace_once(text, "    PlasmaComponents3.ToolButton {\n        id: hotspotButton",
        """    PlasmaComponents3.ToolButton {
        id: stationButton
        visible: availableDevices.wirelessDeviceAvailable
        text: i18n("STA")
        display: QQC2.AbstractButton.IconOnly
        icon.name: "network-wireless"
        checkable: true
        checked: mainWindow.hotspotSwitcher.mode === "sta"
        enabled: !mainWindow.hotspotSwitcher.busy
            && mainWindow.hotspotSwitcher.mode !== "unknown"
        onClicked: {
            mainWindow.hotspotSwitcher.selectMode(
                mainWindow.hotspotSwitcher.mode === "sta" ? "radio-off" : "sta");
            checked = Qt.binding(() => mainWindow.hotspotSwitcher.mode === "sta");
        }
        KeyNavigation.left: planeModeSwitchButton
        KeyNavigation.right: hotspotButton
        PlasmaComponents3.ToolTip { text: i18n("Connect to a Wi-Fi network") }
    }

    PlasmaComponents3.ToolButton {
        id: hotspotButton""")
    text = replace_once(text, "            id: tooltip\n",
        '            id: tooltip\n            text: mainWindow.hotspotSwitcher.mode === "ap" ? i18n("Disable Hotspot") : i18n("Create Hotspot")\n')
    text = text.replace('        text: i18n("Hotspot")', '        text: i18n("AP")')
    text = text.replace("        enabled: !mainWindow.hotspotSwitcher.busy && !PlasmaNM.Configuration.airplaneModeEnabled",
        "        enabled: !mainWindow.hotspotSwitcher.busy"
        " && mainWindow.hotspotSwitcher.mode !== \"unknown\" && !PlasmaNM.Configuration.airplaneModeEnabled")
    # Replace native optimistic check-state handlers with observed NM mode.
    start = text.index("        Connections {\n            target: handler\n            function onHotspotCreated()")
    end = text.index("\n    }\n", start)
    text = text[:start] + '        checked: mainWindow.hotspotSwitcher.mode === "ap"\n' + text[end:]
    text = replace_once(text, "                mainWindow.hotspotSwitcher.start()\n            }",
        '                mainWindow.hotspotSwitcher.start()\n            }\n            checked = Qt.binding(() => mainWindow.hotspotSwitcher.mode === "ap");')
    text = text.replace("if (PlasmaNM.Configuration.hotspotConnectionPath) {",
                        'if (mainWindow.hotspotSwitcher.mode === "ap") {')
    text = text.replace("        KeyNavigation.left: planeModeSwitchButton.visible ? planeModeSwitchButton : planeModeSwitchButton.KeyNavigation.left",
                        "        KeyNavigation.left: stationButton")
    text = replace_once(text, '        text: i18n("AP")\n',
        '        text: i18n("AP")\n        display: QQC2.AbstractButton.IconOnly\n')
    for identifier in ("wifiSwitchButton", "wwanSwitchButton"):
        text = replace_once(text,
            "        PlasmaComponents3.Switch {\n            id: " + identifier + "\n",
            "        PlasmaComponents3.ToolButton {\n            id: " + identifier + "\n"
            "            checkable: true\n"
            "            display: QQC2.AbstractButton.IconOnly\n")
    text = replace_once(text,
        "leftMargin: wifiSwitchButton.indicator.width + wifiSwitchButton.spacing",
        "leftMargin: 0")
    text = replace_once(text,
        "            visible: availableDevices.wirelessDeviceAvailable\n",
        "            visible: false // STA/AP jointly control the Wi-Fi radio.\n")
    # The custom helper uses NM's real wlan0 capability, rather than Plasma's
    # native temporary-hotspot policy (which may hide a supported device).
    text = replace_once(text, "        visible: handler.hotspotSupported\n",
        "        visible: availableDevices.wirelessDeviceAvailable\n")
    # Keep the header to radio / station / access point; native airplane action
    # remains available through Plasma's existing global action.
    text = replace_once(text,
        "            visible: availableDevices.modemDeviceAvailable || availableDevices.wirelessDeviceAvailable\n",
        "            visible: false // Board toolbar exposes Wi-Fi, STA and AP.\n")
    path.write_text(text)


if __name__ == "__main__":
    import sys
    patch(Path(sys.argv[1]))

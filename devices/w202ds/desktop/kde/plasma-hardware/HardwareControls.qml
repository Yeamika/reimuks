import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PC
import org.kde.plasma.extras as PE
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Support

ColumnLayout {
    id: root
    property var states: ({})
    property bool busy: false
    property bool requestInFlight: false
    property int requestSerial: 0
    property string deferredAction: ""
    property bool powerControls: false
    property string message: ""
    property string protocol: ""
    property int torchBrightness: 0
    property int torchMaximum: 8
    property int lastTorchBrightness: 1
    property bool torchInFlight: false
    property int queuedTorch: -1
    property int torchGeneration: 0
    property int statusTorchGeneration: 0
    property bool tabletMode: false
    function requestTorch(level) {
        level = Math.max(0, Math.min(torchMaximum, Math.round(level)));
        ++torchGeneration;
        queuedTorch = level;
        if (!torchInFlight) sendTorch();
    }
    function sendTorch() {
        const level = queuedTorch;
        queuedTorch = -1;
        torchInFlight = true;
        torchExecutor.connectSource("/usr/bin/pkexec /usr/libexec/w202-torch-control " + level + " # " + (++requestSerial));
    }
    function request(action) {
        if (action.startsWith("torch-")) {
            const value = action.substring(6);
            requestTorch(value === "off" ? 0 : value === "on" ? lastTorchBrightness : Number(value));
            return;
        }
        if (requestInFlight) {
            if (action !== "status") deferredAction = action;
            return;
        }
        requestInFlight = true;
        statusTorchGeneration = torchGeneration;
        busy = action !== "status";
        executor.connectSource("/usr/libexec/w202-hardware-controls " + action + " # " + (++requestSerial));
    }
    Support.DataSource {
        id: executor
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (data["exit code"] === undefined) return;
            disconnectSource(source);
            try {
                const result = JSON.parse(data["stdout"]);
                if (result.ok) {
                    const updateTorch = root.statusTorchGeneration === root.torchGeneration
                        && !root.torchInFlight && root.queuedTorch < 0 && !brightness.pressed;
                    const states = result.states;
                    if (!updateTorch) states.torch = root.states.torch;
                    root.states = states;
                    root.protocol = result.protocol || "";
                    root.torchMaximum = result.torch?.maximum || 8;
                    if (updateTorch) {
                        root.torchBrightness = result.torch?.brightness || 0;
                        if (root.torchBrightness > 0) root.lastTorchBrightness = root.torchBrightness;
                        brightness.value = root.torchBrightness;
                    }
                    root.tabletMode = result.rotation?.tablet_mode === true;
                    root.message = "";
                } else root.message = result.error || i18n("操作失败");
            } catch (error) { root.message = i18n("无法读取设备状态"); }
            root.busy = false;
            root.requestInFlight = false;
            if (root.deferredAction) {
                const next = root.deferredAction;
                root.deferredAction = "";
                Qt.callLater(() => root.request(next));
            }
        }
    }
    Support.DataSource {
        id: torchExecutor
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (data["exit code"] === undefined) return;
            disconnectSource(source);
            try {
                const result = JSON.parse(data["stdout"]);
                if (data["exit code"] !== 0 || result.error || typeof result.brightness !== "number")
                    throw new Error(result.error || i18n("手电筒操作失败"));
                root.torchBrightness = result.brightness;
                root.torchMaximum = result.maximum;
                if (result.brightness > 0) root.lastTorchBrightness = result.brightness;
                root.states = Object.assign({}, root.states, {torch: result.brightness > 0});
                if (!brightness.pressed && root.queuedTorch < 0) brightness.value = result.brightness;
                root.message = "";
            } catch (error) { root.message = String(error); }
            root.torchInFlight = false;
            if (root.queuedTorch >= 0) root.sendTorch();
        }
    }
    Timer {
        interval: 4000
        repeat: true
        running: root.visible
        onTriggered: root.request("status")
    }
    onVisibleChanged: if (visible) request("status")
    Component.onCompleted: request("status")
        GridLayout {
            columns: root.powerControls ? 2 : 7
            Layout.fillWidth: true
            rowSpacing: Kirigami.Units.smallSpacing
            Repeater {
                model: root.powerControls ? [
                    {key: "fast", name: "快充", icon: "battery-charging"},
                    {key: "separation", name: "充电分离", icon: "battery-profile-powersave"}
                ] : [
                    {key: "cellular", name: "5G", icon: "network-mobile-100"},
                    {key: "wifi", name: "Wi-Fi", icon: "network-wireless"},
                    {key: "bluetooth", name: "蓝牙", icon: "preferences-system-bluetooth"},
                    {key: "gnss", name: "GNSS", icon: "gps"},
                    {key: "tablet", name: "平板模式", icon: "input-tablet"},
                    {key: "rotation", name: "自动旋转", icon: "rotation-allowed"},
                    {key: "keyboard", name: "屏幕键盘", icon: "input-keyboard"}
                ]
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    spacing: Kirigami.Units.smallSpacing
                    PC.ToolButton {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 2.5
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2.5
                        icon.name: modelData.icon
                        icon.width: Kirigami.Units.iconSizes.smallMedium
                        icon.height: Kirigami.Units.iconSizes.smallMedium
                        checkable: true
                        checked: root.states[modelData.key] === true
                        enabled: typeof root.states[modelData.key] === "boolean"
                        onClicked: {
                            root.request(modelData.key + (root.states[modelData.key] ? "-off" : "-on"));
                            checked = Qt.binding(() => root.states[modelData.key] === true);
                        }
                        PC.ToolTip { text: modelData.key === "keyboard" ? i18n("点击输入框自动弹出；键盘套拆装时自动切换") : modelData.name }
                    }
                    PC.Label { text: modelData.name; Layout.alignment: Qt.AlignHCenter }
                }
            }
        }
        Kirigami.Separator { Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            visible: !root.powerControls && typeof root.states.torch === "boolean"
            spacing: Kirigami.Units.largeSpacing
            PC.ToolButton {
                icon.name: "flashlight-on-symbolic"
                icon.width: Kirigami.Units.iconSizes.smallMedium
                icon.height: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.5
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2.5
                checkable: true
                checked: root.states.torch === true
                onClicked: {
                    root.request(root.states.torch ? "torch-off" : "torch-on");
                    checked = Qt.binding(() => root.states.torch === true);
                }
                PC.ToolTip { text: i18n("手电筒") }
            }
            PC.Slider {
                id: brightness
                Layout.fillWidth: true
                from: 0
                to: root.torchMaximum
                stepSize: 1
                onMoved: root.requestTorch(value)
            }
            PC.Label { text: Math.round(brightness.value) + "/" + root.torchMaximum }
        }
        PC.Label { text: root.protocol; visible: root.powerControls && text.length > 0 }
        PC.Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.message; visible: text.length > 0 }
}

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Support

PC.ItemDelegate {
    id: root
    property var usb: ({})
    background.visible: highlighted
    highlighted: activeFocus
    hoverEnabled: false
    property bool deferredApply: false
    property bool dirty: false
    property bool inFlight: false
    property bool applying: false
    property int serial: 0
    property string message: ""
    property int selectedFunctions: 3
    readonly property var functionChoices: [
        {key: "acm", label: "ACM", description: "串口", mask: 1},
        {key: "ncm", label: "NCM", description: "网络", mask: 2}
    ]
    readonly property string functionSummary: {
        const names = functionChoices.filter(f => (selectedFunctions & f.mask) !== 0).map(f => f.label);
        return names.length > 1 ? "[" + names.join(", ") + "]" : names.length === 1 ? names[0] : "—";
    }
    readonly property var modes: ["auto", "device", "host"]
    function request(action) {
        if (inFlight) return;
        inFlight = true;
        applying = action !== "status";
        executor.connectSource("/usr/libexec/w202-hardware-controls " + action + " # usb-" + (++serial));
    }
    function applySettings() {
        dirty = true;
        if (inFlight) { deferredApply = true; return; }
        const mask = selectedFunctions;
        if (!mask || preset.currentIndex < 0) {
            message = i18n("请至少选择一项 Device 功能");
            options.open();
            return;
        }
        request("usb-" + modes[preset.currentIndex] + "-" + (deviceEnabled.checked ? 1 : 0) + "-" + mask);
    }
    function sync() {
        preset.currentIndex = modes.indexOf(usb.requested_mode || "auto");
        deviceEnabled.checked = usb.enabled === true;
        selectedFunctions = (usb.acm === true ? 1 : 0) + (usb.ncm === true ? 2 : 0);
    }
    Support.DataSource {
        id: executor
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (data["exit code"] === undefined) return;
            disconnectSource(source);
            const wasApplying = root.applying;
            root.inFlight = root.applying = false;
            try {
                const result = JSON.parse(data["stdout"]);
                if (data["exit code"] !== 0 || !result.ok) throw new Error(result.error || i18n("USB 操作失败"));
                root.usb = result.usb || {};
                if (wasApplying) root.dirty = false;
                if (!root.dirty) root.sync();
                if (wasApplying) root.message = "";
            } catch (error) {
                if (wasApplying) { root.dirty = false; root.sync(); }
                root.message = String(error); options.open();
            }
            if (root.deferredApply) {
                root.deferredApply = false;
                Qt.callLater(() => root.applySettings());
            }
        }
    }
    Timer { interval: 4000; repeat: true; running: root.visible; onTriggered: root.request("status") }
    Component.onCompleted: request("status")
    onVisibleChanged: if (visible) request("status")
    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing
        Kirigami.Icon {
            source: "drive-removable-media-usb"
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
        }
        PC.Label { text: i18n("USB") }
        PC.ComboBox {
            id: preset
            model: ["OTG", "Device", "Host"]
            enabled: !root.applying
            onActivated: root.applySettings()
            PC.ToolTip { text: i18n("预期模式") }
        }
        PC.Label { text: "/" }
        PC.Label {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: root.usb.actual?.connected === false ? i18n("未连接") : root.usb.actual?.available === true ?
                (root.usb.actual.data_role === "host" ? "Host" : root.usb.actual.data_role === "device" ? "Device" : i18n("未确定")) : i18n("不可用")
            PC.ToolTip { text: i18n("当前模式") }
        }
        PC.ToolButton {
            id: menuButton
            icon.name: "application-menu"
            text: i18n("自定义 Device 功能")
            display: PC.ToolButton.IconOnly
            onClicked: options.visible ? options.close() : options.open()
            PC.ToolTip { text: parent.text }
        }
    }
    QQC2.Popup {
        id: options
        x: Math.max(0, root.width - width)
        y: root.height
        width: Kirigami.Units.gridUnit * 18
        padding: Kirigami.Units.largeSpacing
        closePolicy: QQC2.Popup.CloseOnEscape | QQC2.Popup.CloseOnPressOutside
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            RowLayout {
                Layout.fillWidth: true
                PC.CheckBox {
                    id: deviceEnabled
                    text: i18n("自定义 Device")
                    enabled: !root.applying
                    onClicked: root.applySettings()
                }
                PC.Label { text: root.functionSummary; Layout.fillWidth: true }
                PC.ToolButton {
                    id: functionMenuButton
                    icon.name: "application-menu"
                    text: i18n("Device 功能列表")
                    display: PC.ToolButton.IconOnly
                    onClicked: functionOptions.visible ? functionOptions.close() : functionOptions.open()
                    PC.ToolTip { text: parent.text }
                    QQC2.Popup {
                        id: functionOptions
                        x: parent.width - width
                        y: parent.height
                        width: Kirigami.Units.gridUnit * 14
                        padding: Kirigami.Units.smallSpacing
                        closePolicy: QQC2.Popup.CloseOnEscape | QQC2.Popup.CloseOnPressOutside
                        contentItem: ColumnLayout {
                            RowLayout {
                                Layout.fillWidth: true
                                PC.Label { text: i18n("功能组合"); Layout.fillWidth: true }
                                PC.Button {
                                    text: root.applying ? i18n("保存中…") : i18n("保存")
                                    enabled: root.dirty && !root.inFlight && root.selectedFunctions > 0
                                    onClicked: root.applySettings()
                                }
                            }
                            Repeater {
                                model: root.functionChoices
                                delegate: PC.CheckBox {
                                    required property var modelData
                                    text: modelData.label + "（" + modelData.description + "）"
                                    checked: (root.selectedFunctions & modelData.mask) !== 0
                                    enabled: !root.applying && root.selectedFunctions !== modelData.mask
                                    onClicked: {
                                        root.selectedFunctions ^= modelData.mask;
                                        checked = Qt.binding(() => (root.selectedFunctions & modelData.mask) !== 0);
                                        root.dirty = true;
                                    }
                                }
                            }

                        }
                    }
                }
            }
            PC.CheckBox {
                text: i18n("DP 视频输出（未接入）")
                enabled: false
                checked: false
                PC.ToolTip { text: i18n("Type-C DP Alt Mode 尚未接入驱动和控制接口，与 USB 数据角色分别管理") }
            }
            PC.Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.message; visible: text.length > 0 }
        }
    }
}

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as Support
import org.kde.ksvg as KSvg

PC.ItemDelegate {
    id: root
    property var power: ({})
    property bool requestInFlight: false
    property bool changing: false
    property int requestSerial: 0
    property string deferredAction: ""
    property string currentAction: ""
    property string message: ""
    readonly property var modes: ["auto", "pps", "pd9v", "pd5v", "bc1.2"]
    background.visible: highlighted
    highlighted: activeFocus
    hoverEnabled: false
    function measure(value, unit) {
        return typeof value === "number" ? (value / 1000000).toFixed(2) + " " + unit : i18n("不可用");
    }
    function request(action) {
        if (requestInFlight) {
            if (action !== "status") deferredAction = action;
            return;
        }
        requestInFlight = true;
        changing = action !== "status";
        currentAction = action;
        // The executable engine retains completed source data. A unique source
        // prevents a reconnect from consuming the previous process's result.
        executor.connectSource("/usr/libexec/w202-hardware-controls " + action + " # " + (++requestSerial));
    }
    Support.DataSource {
        id: executor
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (data["exit code"] === undefined) return;
            disconnectSource(source);
            root.requestInFlight = root.changing = false;
            try {
                const result = JSON.parse(data["stdout"]);
                if (result.ok) {
                    root.power = result.power || {};
                    if (root.currentAction !== "status") root.message = "";
                }
                else root.message = result.error || i18n("操作失败");
            } catch (error) { root.message = i18n("无法读取充电状态"); }
            if (root.deferredAction) {
                const next = root.deferredAction;
                root.deferredAction = "";
                Qt.callLater(() => root.request(next));
            }
        }
    }
    Timer { interval: 4000; repeat: true; running: root.visible; onTriggered: root.request("status") }
    onVisibleChanged: if (visible) request("status")
    Component.onCompleted: request("status")
    contentItem: RowLayout {
        spacing: Kirigami.Units.gridUnit
        KSvg.SvgItem {
            svg: KSvg.Svg { imagePath: "icons/battery" }
            elementId: "AcAdapter"
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
        }
        ColumnLayout {
            Layout.fillWidth: true
            RowLayout {
                PC.Label { text: i18n("充电"); Layout.fillWidth: true }
                PC.Label { text: root.power.battery_status || ""; enabled: false }
            }
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                columnSpacing: Kirigami.Units.largeSpacing
                component DetailLabel: PC.Label {
                    font: Kirigami.Theme.smallFont
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                DetailLabel { text: i18n("预期模式") }
                PC.ComboBox {
                    Layout.fillWidth: true
                    model: ["Auto（默认，最高功率）", "PPS", "PD 9V", "PD 5V", "BC1.2（暂不支持强制选择）"]
                    currentIndex: root.modes.indexOf(root.power.requested_mode || "auto")
                    enabled: !root.changing && (root.power.charging_modes || []).length > 0
                    delegate: PC.ItemDelegate {
                        required property int index
                        required property var modelData
                        width: parent ? parent.width : implicitWidth
                        text: modelData
                        enabled: index === 0 || (root.power.charging_modes || []).indexOf(root.modes[index]) >= 0
                    }
                    onActivated: index => {
                        if (index < 4) root.request("mode-" + root.modes[index]);
                        currentIndex = Qt.binding(() => root.modes.indexOf(root.power.requested_mode || "auto"));
                    }
                }
                DetailLabel { text: i18n("当前模式") }
                DetailLabel {
                    text: root.power.usb_output_active === true ? i18n("USB 对外供电") :
                        root.power.typec_connected === false ? i18n("未连接") :
                        !root.power.input_online ? i18n("已连接，未供电") :
                        root.power.protocol === "PD PPS" ? "PPS" :
                        root.power.protocol === "PD fixed" ? (root.power.active_mode === "pd9v" ? "PD 9V" : root.power.active_mode === "pd5v" ? "PD 5V" : "PD") :
                        ["DCP", "CDP", "SDP"].indexOf(root.power.protocol) >= 0 ? "BC1.2 / " + root.power.protocol :
                        root.power.protocol === "C" ? i18n("Type-C（未确认 PD）") :
                        root.power.protocol === "PD" ? "PD" :
                        root.power.protocol === "PD_PPS" ? "PPS" : i18n("未知")
                }
                DetailLabel { text: i18n("输入电压 / 电流") }
                DetailLabel {
                    text: root.power.power_role === "sink" && root.power.input_online === true ?
                        root.measure(root.power.input_voltage_uv, "V") + " / " + root.measure(root.power.input_current_ua, "A") : "— / —"
                }
                DetailLabel { text: i18n("USB 输出电压 / 电流") }
                DetailLabel {
                    text: root.power.usb_output_active === true ? root.measure(root.power.input_voltage_uv, "V") + " / " + i18n("不可用") : "— / —"
                }
                DetailLabel { text: i18n("电池电压 / 电流") }
                DetailLabel {
                    text: root.measure(root.power.battery_voltage_uv, "V") + " / " + root.measure(root.power.battery_current_ua, "A")
                        + (root.power.battery_current_ua > 0 ? i18n("（充入）") : root.power.battery_current_ua < 0 ? i18n("（放出）") : "")
                }
                DetailLabel { text: i18n("协商电压 / 电流上限") }
                DetailLabel { text: root.power.power_role === "sink" && root.power.input_online === true ? root.measure(root.power.contract_voltage_uv, "V") + " / " + root.measure(root.power.contract_current_ua, "A") : "— / —" }
                DetailLabel { text: i18n("充电分离") }
                PC.CheckBox {
                    text: i18n("外部供电，停止给电池充电")
                    checked: root.power.separation === true
                    enabled: !root.changing && typeof root.power.separation === "boolean"
                    onClicked: {
                        root.request(root.power.separation ? "separation-off" : "separation-on");
                        checked = Qt.binding(() => root.power.separation === true);
                    }
                }
            }
            PC.Label {
                Layout.fillWidth: true
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
                text: i18n("Auto / PPS 允许驱动协商 PPS，不可用时回退固定 PD。电流上限不是实测电流；实际功率受充电器、温度和电池状态限制。")
                enabled: false
            }
            PC.Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: root.message; visible: text.length > 0 }
        }
    }
}

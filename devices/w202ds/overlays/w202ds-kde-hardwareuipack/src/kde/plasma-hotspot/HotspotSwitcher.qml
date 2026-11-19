/*
    SPDX-FileCopyrightText: 2026 W202DS contributors
    SPDX-License-Identifier: LGPL-2.1-only OR LGPL-3.0-only OR LicenseRef-KDE-Accepted-LGPL
*/
import QtQuick

Item {
    id: root
    visible: false

    required property var nmHandler
    required property var configuration
    property string stage: "idle"
    property string lastError: ""
    property bool accessPointActive: false
    property bool nativeHotspotActive: false
    property string mode: "unknown"
    property bool radioEnabled: false
    property bool pollingEnabled: true
    property string pending: ""
    readonly property bool busy: stage !== "idle"
    readonly property bool suppressScanning: busy || mode !== "sta" || nativeHotspotActive || accessPointActive
    signal operationRequested(string name)
    signal failed(string message)

    function operation(name) {
        pending = name;
        operationRequested(name);
    }

    function refresh() {
        if (!busy) operationRequested("status");
    }

    function selectMode(value) {
        if (busy) return;
        lastError = "";
        stage = "switching";
        operation(value);
    }

    function setRadio(enabled) {
        selectMode(enabled ? "radio-on" : "radio-off");
    }

    function fail(message) {
        lastError = message;
        failed(message);
        stage = "restoring";
        nmHandler.stopHotspot();
        configuration.hotspotConnectionPath = "";
        nativeHotspotActive = false;
        operation("radio-off");
    }

    function start() {
        if (busy || mode === "ap" || configuration.hotspotConnectionPath) {
            return;
        }
        lastError = "";
        stage = "preparing";
        operation("prepare");
    }

    function stop() {
        if (busy) {
            return;
        }
        stage = "restoring";
        nmHandler.stopHotspot();
        configuration.hotspotConnectionPath = "";
        nativeHotspotActive = false;
        operation("radio-off");
    }

    function completeOperation(name, result) {
        if (name === "status") {
            if (!busy && result.ok) {
                mode = result.mode;
                radioEnabled = result.radio;
            }
            return;
        }
        if (name !== pending) return;
        pending = "";
        if (["idle", "sta", "radio-on", "radio-off", "restore", "rollback"].indexOf(name) >= 0) {
            if (result.ok) {
                nativeHotspotActive = false;
                configuration.hotspotConnectionPath = "";
                mode = result.mode;
                radioEnabled = result.radio;
            } else {
                mode = "unknown";
                lastError = result.error;
                failed(result.error);
            }
            stage = "idle";
            refresh();
            return;
        }
        if (!result.ok) {
            fail(result.error);
            return;
        }
        if (name === "prepare" && stage === "preparing") {
            stage = "creating";
            operation("create");
        } else if (name === "create" && stage === "creating") {
            configuration.hotspotConnectionPath = result.active_path;
            nativeHotspotActive = true;
            stage = "verifying";
            nmHandler.hotspotCreated();
            operation("verify");
        } else if (name === "verify" && stage === "verifying") {
            mode = "ap";
            stage = "idle";
            refresh();
        }
    }

    Connections {
        target: root.nmHandler
        function onHotspotCreated() {
            root.nativeHotspotActive = true;
        }
        function onHotspotDisabled() {
            root.nativeHotspotActive = false;
            // Verification detects activation failures; do not race its helper lock.
            if (root.stage === "idle") {
                root.stage = "restoring";
                root.operation("radio-off");
            }
        }
    }
    onAccessPointActiveChanged: {
        if (!accessPointActive && nativeHotspotActive && stage === "idle") {
            stage = "restoring";
            nativeHotspotActive = false;
            configuration.hotspotConnectionPath = "";
            nmHandler.hotspotDisabled();
            operation("radio-off");
        }
    }
    Timer {
        interval: 2000
        repeat: true
        running: root.pollingEnabled && !root.busy
        onTriggered: root.refresh()
    }
    onPollingEnabledChanged: { if (pollingEnabled) refresh(); }
    Component.onCompleted: {
        nativeHotspotActive = !!configuration.hotspotConnectionPath;
        refresh();
    }
}

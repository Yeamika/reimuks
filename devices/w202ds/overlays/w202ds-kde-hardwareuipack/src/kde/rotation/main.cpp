// SPDX-License-Identifier: MIT
#include <QApplication>
#include <QAbstractButton>
#include <QMessageBox>
#include <QPushButton>
#include <QTimer>
#include <QDebug>
#include <QDBusInterface>
#include <QDBusReply>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <libudev.h>
#include <cstring>
#include <KScreen/Config>
#include <KScreen/GetConfigOperation>
#include <KScreen/Output>
#include <KScreen/SetConfigOperation>
#include <stdexcept>

using Policy = KScreen::Output::AutoRotatePolicy;

// Only external keyboard input devices, not gpio power/volume keys or virtual keyboards.
static bool keyboardAttached()
{
    QDBusInterface manager("org.kde.KWin", "/org/kde/KWin",
        "org.freedesktop.DBus.Properties", QDBusConnection::sessionBus());
    QDBusReply<QVariantMap> reply = manager.call("GetAll", "org.kde.KWin.TabletModeManager");
    if (reply.isValid() && reply.value().value("tabletModeAvailable").toBool())
        return !reply.value().value("tabletMode").toBool();
    auto *context = udev_new();
    if (!context) throw std::runtime_error("无法查询键盘状态");
    auto *scan = udev_enumerate_new(context);
    if (!scan) { udev_unref(context); throw std::runtime_error("无法查询键盘状态"); }
    udev_enumerate_add_match_subsystem(scan, "input");
    if (udev_enumerate_scan_devices(scan) < 0) {
        udev_enumerate_unref(scan);
        udev_unref(context);
        throw std::runtime_error("无法查询键盘状态");
    }
    bool found = false;
    udev_list_entry *entry;
    udev_list_entry_foreach(entry, udev_enumerate_get_list_entry(scan)) {
        auto *device = udev_device_new_from_syspath(context, udev_list_entry_get_name(entry));
        if (!device) continue;
        const char *key = udev_device_get_property_value(device, "ID_INPUT_KEYBOARD");
        if (key && std::strcmp(key, "1") == 0) {
            for (auto *ancestor = device; ancestor; ancestor = udev_device_get_parent(ancestor)) {
                const char *bus = udev_device_get_property_value(ancestor, "ID_BUS");
                const char *subsystem = udev_device_get_subsystem(ancestor);
                if ((bus && (!std::strcmp(bus, "usb") || !std::strcmp(bus, "bluetooth")))
                    || (subsystem && (!std::strcmp(subsystem, "usb") || !std::strcmp(subsystem, "bluetooth")))) {
                    found = true;
                    break;
                }
            }
        }
        udev_device_unref(device);
    }
    udev_enumerate_unref(scan);
    udev_unref(context);
    return found;
}

static KScreen::ConfigPtr readConfig()
{
    auto *op = new KScreen::GetConfigOperation;
    if (!op->exec() || !op->config()) {
        throw std::runtime_error("无法读取 KDE 显示配置");
    }
    return op->config();
}

static KScreen::OutputPtr panel(const KScreen::ConfigPtr &config)
{
    KScreen::OutputPtr selected;
    for (const auto &output : config->outputs()) {
        if (!output->isConnected() || !output->isEnabled()
            || output->type() != KScreen::Output::Panel
            || !output->capabilities().testFlag(KScreen::Output::Capability::AutoRotation)) {
            continue;
        }
        if (selected) {
            throw std::runtime_error("存在多个支持自动旋转的内置屏幕，无法唯一选择");
        }
        selected = output;
    }
    if (!selected) {
        throw std::runtime_error("未找到支持自动旋转的内置屏幕。请检查 Wayland、加速度计及 iio-sensor-proxy。");
    }
    return selected;
}

static void lockForKeyboard()
{
    if (!keyboardAttached()) return;
    const auto config = readConfig();
    const auto output = panel(config);
    if (output->autoRotatePolicy() == Policy::InTabletMode) return;
    if (output->autoRotatePolicy() == Policy::Never) return;
    output->setAutoRotatePolicy(Policy::Never);
    auto *op = new KScreen::SetConfigOperation(config);
    if (!op->exec()) throw std::runtime_error("键盘接入后锁定方向失败");
    if (panel(readConfig())->autoRotatePolicy() != Policy::Never)
        throw std::runtime_error("键盘方向锁定未通过读回检查");
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("w202-rotation"));
    const QString command = app.arguments().value(1);
    if (command == "status" || command == "on" || command == "off") {
        try {
            auto config = readConfig();
            auto output = panel(config);
            if (command != "status") {
                output->setAutoRotatePolicy(command == "on" ? Policy::InTabletMode : Policy::Never);
                auto *operation = new KScreen::SetConfigOperation(config);
                if (!operation->exec()) throw std::runtime_error("无法设置自动旋转策略");
                output = panel(readConfig());
                if (output->autoRotatePolicy() != (command == "on" ? Policy::InTabletMode : Policy::Never))
                    throw std::runtime_error("自动旋转策略读回不一致");
            }
            QDBusInterface manager("org.kde.KWin", "/org/kde/KWin",
                "org.freedesktop.DBus.Properties", QDBusConnection::sessionBus());
            QDBusReply<QVariantMap> reply = manager.call("GetAll", "org.kde.KWin.TabletModeManager");
            if (!reply.isValid()) throw std::runtime_error("无法读取 KDE 平板模式");
            QJsonObject result;
            result["enabled"] = output->autoRotatePolicy() != Policy::Never;
            result["tablet_mode"] = reply.value().value("tabletMode").toBool();
            result["tablet_available"] = reply.value().value("tabletModeAvailable").toBool();
            result["policy"] = output->autoRotatePolicy() == Policy::Never ? "locked" :
                output->autoRotatePolicy() == Policy::InTabletMode ? "tablet" : "always";
            QTextStream(stdout) << QJsonDocument(result).toJson(QJsonDocument::Compact) << '\n';
            return 0;
        } catch (const std::exception &error) {
            QTextStream(stderr) << error.what() << '\n';
            return 1;
        }
    }
    if (qEnvironmentVariable("XDG_SESSION_TYPE") != QStringLiteral("wayland")) {
        if (app.arguments().contains(QStringLiteral("--watch"))) return 1;
        QMessageBox::warning(nullptr, QStringLiteral("自动旋转"), QStringLiteral("请在 KDE Wayland 会话中使用。"));
        return 1;
    }
    if (app.arguments().contains(QStringLiteral("--watch"))) {
        app.setQuitOnLastWindowClosed(false);
        QTimer timer;
        bool busy = false;
        QString previousError;
        auto enforce = [&] {
            if (busy) return;
            busy = true;
            try { lockForKeyboard(); previousError.clear(); }
            catch (const std::exception &error) {
                const auto message = QString::fromUtf8(error.what());
                if (message != previousError) qWarning().noquote() << message;
                previousError = message;
            }
            busy = false;
        };
        QObject::connect(&timer, &QTimer::timeout, &app, enforce);
        timer.start(2000);
        enforce();
        return app.exec();
    }
    try {
        lockForKeyboard();
        const auto initial = panel(readConfig());
        const QString name = initial->name();
        QString state;
        switch (initial->autoRotatePolicy()) {
        case Policy::Never: state = QStringLiteral("已锁定方向"); break;
        case Policy::Always: state = QStringLiteral("自动旋转已开启"); break;
        case Policy::InTabletMode: state = QStringLiteral("仅平板模式自动旋转"); break;
        default: throw std::runtime_error("未知自动旋转策略");
        }
        QMessageBox box(QMessageBox::Question, QStringLiteral("自动旋转"),
                         name + QStringLiteral("：") + state, QMessageBox::Cancel);
        auto *enable = box.addButton(QStringLiteral("开启自动旋转"), QMessageBox::AcceptRole);
        auto *lock = box.addButton(QStringLiteral("锁定当前方向"), QMessageBox::DestructiveRole);
        QTimer keyboardTimer;
        auto updateKeyboard = [&] {
            try {
                const bool attached = keyboardAttached();
                enable->setEnabled(!attached);
                lock->setEnabled(!attached);
                box.setInformativeText(attached ? QStringLiteral("已连接键盘：自动旋转开关不可用，保持固定方向。")
                                               : QStringLiteral("未连接外接键盘，可以切换自动旋转。"));
            } catch (const std::exception &) {
                enable->setEnabled(false);
                lock->setEnabled(false);
                box.setInformativeText(QStringLiteral("无法确认键盘状态，开关不可用。"));
            }
        };
        QObject::connect(&keyboardTimer, &QTimer::timeout, &box, updateKeyboard);
        keyboardTimer.start(1000);
        updateKeyboard();
        box.exec();
        keyboardTimer.stop();
        if (box.clickedButton() != enable && box.clickedButton() != lock) {
            return 0;
        }
        const Policy wanted = box.clickedButton() == enable ? Policy::Always : Policy::Never;
        if (keyboardAttached()) {
            lockForKeyboard();
            throw std::runtime_error("已连接键盘，自动旋转开关不可用");
        }
        // Re-read after the dialog: preserve unrelated display changes and current rotation.
        const auto config = readConfig();
        const auto output = panel(config);
        if (output->name() != name) {
            throw std::runtime_error("屏幕配置已变化，请重新打开开关");
        }
        output->setAutoRotatePolicy(wanted);
        auto *op = new KScreen::SetConfigOperation(config);
        if (!op->exec()) {
            throw std::runtime_error("KDE 未能应用自动旋转策略");
        }
        const auto actual = panel(readConfig());
        if (actual->name() != name || actual->autoRotatePolicy() != wanted) {
            throw std::runtime_error("读回策略与请求不一致，请在显示设置中检查");
        }
        QMessageBox::information(nullptr, QStringLiteral("自动旋转"),
            wanted == Policy::Always ? QStringLiteral("自动旋转策略已开启，旋转仍需有效传感器数据。")
                                     : QStringLiteral("自动旋转已关闭，保持当前方向。"));
    } catch (const std::exception &error) {
        QMessageBox::warning(nullptr, QStringLiteral("自动旋转"), QString::fromUtf8(error.what()));
        return 1;
    }
    return 0;
}

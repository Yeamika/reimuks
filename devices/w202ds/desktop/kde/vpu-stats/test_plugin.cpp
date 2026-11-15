// SPDX-License-Identifier: MIT
#include <QCoreApplication>
#include <QPluginLoader>
#include <QFile>
#include <KPluginFactory>
#include <systemstats/SensorPlugin.h>
#include <systemstats/SensorContainer.h>
#include <systemstats/SensorObject.h>
#include <systemstats/SensorProperty.h>
#include <iostream>
#include <memory>
#include <cmath>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (argc != 2) return 1;
    QPluginLoader loader(QString::fromLocal8Bit(argv[1]));
    auto *factory = qobject_cast<KPluginFactory *>(loader.instance());
    if (!factory) { std::cerr << loader.errorString().toStdString(); return 2; }
    std::unique_ptr<KSysGuard::SensorPlugin> plugin(factory->create<KSysGuard::SensorPlugin>());
    if (!plugin) return 3;
    // KSystemStats queues object/property registration onto the event loop.
    QCoreApplication::processEvents();
    plugin->update();
    KSysGuard::SensorContainer *container = nullptr;
    for (auto *candidate : plugin->containers()) {
        if (candidate->id() == QStringLiteral("vpu")) container = candidate;
    }
    if (!container) return 4;
    KSysGuard::SensorContainer *gpu = nullptr;
    for (auto *candidate : plugin->containers()) {
        if (candidate->id() == QStringLiteral("w202gpu")) gpu = candidate;
    }
    if (!gpu || !gpu->object(QStringLiteral("panfrost"))) return 8;
    auto *decoder = container->object(QStringLiteral("decoder"));
    if (!decoder) return 5;
    for (const auto &id : {QStringLiteral("usage"), QStringLiteral("frequency"), QStringLiteral("status")}) {
        auto *sensor = decoder->sensor(id);
        if (!sensor || sensor->path() != QStringLiteral("vpu/decoder/") + id || !sensor->value().isValid()) return 6;
    }
    if (!QFile::exists(QStringLiteral("/sys/class/misc/sprd_vsp/device/utilization"))) {
        if (!std::isnan(decoder->sensor(QStringLiteral("usage"))->value().toDouble())
            || !std::isnan(decoder->sensor(QStringLiteral("frequency"))->value().toDouble())
            || !decoder->sensor(QStringLiteral("status"))->value().toString().startsWith(QStringLiteral("Unavailable:"))) return 7;
    }
    std::cout << "PASS: Qt loads plugin and KSystemStats registers all three VPU sensors\n";
}

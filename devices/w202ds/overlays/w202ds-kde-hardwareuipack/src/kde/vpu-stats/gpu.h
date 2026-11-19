// SPDX-License-Identifier: MIT
#pragma once
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <chrono>
#include <cmath>
#include <limits>
#include <unistd.h>
#include "gpu_sample.h"
#include <systemstats/SensorContainer.h>
#include <systemstats/SensorObject.h>
#include <systemstats/SensorProperty.h>

// DRM fdinfo is per-client. These sensors intentionally describe the current
// desktop user's clients, not inaccessible clients belonging to other users.
class DesktopGpuStats {
    using Engines = GpuEngines;
    using Clients = GpuClients;
    Clients previous;
    std::chrono::steady_clock::time_point previousTime;
    KSysGuard::SensorProperty *usage, *frequency, *status;
    static double missing() { return std::numeric_limits<double>::quiet_NaN(); }
public:
    explicit DesktopGpuStats(KSysGuard::SensorPlugin *plugin)
    {
        // The stock GPU plugin already owns "gpu", even when it supports no
        // devices here. Use a distinct root to avoid a container-ID collision.
        auto *container = new KSysGuard::SensorContainer(QStringLiteral("w202gpu"), QStringLiteral("GPU"), plugin);
        auto *object = new KSysGuard::SensorObject(QStringLiteral("panfrost"), QStringLiteral("Mali-G57 desktop"), container);
        usage = new KSysGuard::SensorProperty(QStringLiteral("usage"), QStringLiteral("Desktop GPU engine utilization"), object);
        usage->setVariantType(QVariant::Double);
        usage->setUnit(KSysGuard::UnitPercent); usage->setMin(0); usage->setMax(100);
        usage->setDescription(QStringLiteral("Current user's Panfrost clients; busiest engine, deduplicated DRM client IDs. Excludes other users."));
        frequency = new KSysGuard::SensorProperty(QStringLiteral("frequency"), QStringLiteral("GPU frequency"), object);
        frequency->setVariantType(QVariant::Double); frequency->setUnit(KSysGuard::UnitMegaHertz);
        status = new KSysGuard::SensorProperty(QStringLiteral("status"), QStringLiteral("GPU statistics status"), object);
        status->setVariantType(QVariant::String);
        usage->setValue(missing()); frequency->setValue(missing());
        status->setValue(QStringLiteral("Waiting for a subscriber"));
    }
    void update()
    {
        if (!usage->isSubscribed() && !frequency->isSubscribed() && !status->isSubscribed()) {
            previous.clear(); return;
        }
        QFile freq(QStringLiteral("/sys/class/devfreq/23140000.gpu/cur_freq"));
        bool ok = false;
        const double hz = freq.open(QIODevice::ReadOnly) ? freq.readAll().trimmed().toDouble(&ok) : missing();
        frequency->setValue(ok ? hz / 1000000.0 : missing());
        if (!usage->isSubscribed() && !status->isSubscribed()) return;
        Clients clients;
        const auto now = std::chrono::steady_clock::now();
        const auto procs = QDir(QStringLiteral("/proc")).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot);
        for (const auto &proc : procs) {
            proc.fileName().toUInt(&ok);
            if (!ok || proc.ownerId() != getuid()) continue;
            QDir dir(proc.filePath() + QStringLiteral("/fdinfo"));
            for (const auto &fd : dir.entryList(QDir::Files)) {
                QFile info(dir.filePath(fd));
                if (!info.open(QIODevice::ReadOnly)) continue;
                const auto text = info.readAll();
                if (!text.contains("drm-driver:\tpanfrost")) continue;
                QString id; Engines engines;
                for (const auto &line : text.split('\n')) {
                    const int colon = line.indexOf(':');
                    if (colon < 0) continue;
                    const auto key = line.left(colon);
                    const auto value = line.mid(colon + 1).trimmed();
                    if (key == "drm-client-id") id = QString::fromLatin1(value);
                    if (key.startsWith("drm-engine-")) {
                        const auto parts = value.split(' ');
                        const auto ns = parts.value(0).toULongLong(&ok);
                        if (ok && parts.value(1) == "ns") engines.insert(QString::fromLatin1(key), ns);
                    }
                }
                if (!id.isEmpty() && !engines.isEmpty()) clients.insert(id, engines);
            }
        }
        const double elapsed = std::chrono::duration<double, std::nano>(now - previousTime).count();
        const auto sample = gpuSample(previous, clients, elapsed);
        usage->setValue(sample.percent);
        status->setValue(std::isfinite(sample.percent)
            ? (sample.partial ? QStringLiteral("Partial desktop sample: client set changed; stable clients only")
                              : QStringLiteral("Current desktop user; busiest Panfrost engine"))
            : QStringLiteral("Unavailable: profiling off, missing baseline or counter reset"));
        previous = clients; previousTime = now;
    }
};

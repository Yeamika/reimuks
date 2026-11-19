// SPDX-License-Identifier: MIT
#include <QFile>
#include <KPluginFactory>
#include <systemstats/SensorContainer.h>
#include <systemstats/SensorObject.h>
#include <systemstats/SensorPlugin.h>
#include <systemstats/SensorProperty.h>
#include <limits>
#include "sample.h"
#include "gpu.h"

class VpuPlugin : public KSysGuard::SensorPlugin {
    Q_OBJECT
    VpuStats::Sampler sampler;
    KSysGuard::SensorProperty *usage, *frequency, *status;
    DesktopGpuStats gpu;
    static double missing() { return std::numeric_limits<double>::quiet_NaN(); }
public:
    VpuPlugin(QObject *parent, const QVariantList &args) : SensorPlugin(parent, args), gpu(this)
    {
        auto *container = new KSysGuard::SensorContainer(QStringLiteral("vpu"), QStringLiteral("VPU"), this);
        auto *object = new KSysGuard::SensorObject(QStringLiteral("decoder"), QStringLiteral("Video decoder"), container);
        usage = new KSysGuard::SensorProperty(QStringLiteral("usage"), QStringLiteral("VPU task utilization"), object);
        usage->setVariantType(QVariant::Double);
        usage->setUnit(KSysGuard::UnitPercent);
        usage->setMin(0);
        usage->setMax(100);
        usage->setDescription(QStringLiteral("Native decoder START-to-IRQ occupancy; unavailable during legacy MMIO ownership."));
        frequency = new KSysGuard::SensorProperty(QStringLiteral("frequency"), QStringLiteral("VPU clock frequency"), object);
        frequency->setVariantType(QVariant::Double);
        frequency->setUnit(KSysGuard::UnitMegaHertz);
        status = new KSysGuard::SensorProperty(QStringLiteral("status"), QStringLiteral("VPU statistics status"), object);
        status->setVariantType(QVariant::String);
        update();
    }
    void update() override
    {
        gpu.update();
        QFile file(QStringLiteral("/sys/class/misc/sprd_vsp/device/utilization"));
        if (!file.open(QIODevice::ReadOnly)) {
            sampler.clear();
            usage->setValue(missing());
            frequency->setValue(missing());
            status->setValue(QStringLiteral("Unavailable: driver statistics missing or unreadable"));
            return;
        }
        const auto data = VpuStats::parse(file.readAll().toStdString());
        if (!data) {
            sampler.clear();
            usage->setValue(missing());
            frequency->setValue(missing());
            status->setValue(QStringLiteral("Unavailable: unsupported or malformed statistics"));
            return;
        }
        const auto load = sampler.sample(*data);
        usage->setValue(load.value_or(missing()));
        frequency->setValue(static_cast<double>(data->frequency) / 1000000.0);
        status->setValue(!data->healthy ? QStringLiteral("Unavailable: decoder fault")
                        : load ? QStringLiteral("Native task occupancy")
                               : QStringLiteral("Unavailable: baseline, legacy MMIO interval or counters restarted"));
    }
};

K_PLUGIN_CLASS_WITH_JSON(VpuPlugin, "metadata.json")
#include "plugin.moc"

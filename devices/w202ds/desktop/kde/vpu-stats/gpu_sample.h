// SPDX-License-Identifier: MIT
#pragma once
#include <QHash>
#include <QString>
#include <algorithm>
#include <cmath>
#include <limits>
using GpuEngines = QHash<QString, quint64>;
using GpuClients = QHash<QString, GpuEngines>;
struct GpuSample { double percent; bool partial; };
inline GpuSample gpuSample(const GpuClients &before, const GpuClients &now, double elapsed)
{
    const double missing = std::numeric_limits<double>::quiet_NaN();
    if (before.isEmpty() || now.isEmpty() || !std::isfinite(elapsed) || elapsed <= 0)
        return {missing, false};
    QHash<QString, double> busy;
    bool partial = before.size() != now.size();
    unsigned matched = 0;
    for (auto client = now.cbegin(); client != now.cend(); ++client) {
        const auto old = before.constFind(client.key());
        if (old == before.cend()) { partial = true; continue; }
        if (old->size() != client->size()) partial = true;
        for (auto engine = client->cbegin(); engine != client->cend(); ++engine) {
            if (!old->contains(engine.key())) { partial = true; continue; }
            if (engine.value() < old->value(engine.key())) return {missing, false};
            busy[engine.key()] += double(engine.value() - old->value(engine.key()));
            ++matched;
        }
    }
    if (!matched) return {missing, true};
    double load = 0;
    for (double ns : busy) load = std::max(load, ns * 100.0 / elapsed);
    // Concurrent job accounting and snapshot skew may exceed one interval.
    // Saturation is full occupancy, not a missing sample.
    return {std::clamp(load, 0.0, 100.0), partial};
}

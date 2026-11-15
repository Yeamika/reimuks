// SPDX-License-Identifier: MIT
#include "sample.h"
#include <cstdlib>
#include <iostream>

static void check(bool result) { if (!result) std::abort(); }
int main()
{
    using namespace VpuStats;
    const std::string valid = "version=1 generation=99 total_ns=1000 busy_ns=200 untracked_ns=0 healthy=1 frequency_hz=256000000\n";
    auto record = parse(valid);
    check(record.has_value());
    Sampler sample;
    check(!sample.sample(*record));
    auto now = *record;
    now.total += 1000; now.busy += 250;
    check(sample.sample(now) == 25.0);
    now.total += 1000;
    check(sample.sample(now) == 0.0);
    now.total += 1000; now.busy += 1000;
    check(sample.sample(now) == 100.0);
    now.total += 1000; now.untracked += 1;
    check(!sample.sample(now));
    now.total += 1000;
    check(sample.sample(now) == 0.0);
    now.healthy = false; now.total += 1000;
    check(!sample.sample(now));
    now.healthy = true; now.total += 1000;
    check(!sample.sample(now));
    now.total += 1000; now.generation++;
    check(!sample.sample(now));
    now.total = 1; now.busy = 0; now.untracked = 0;
    check(!sample.sample(now));
    sample.clear();
    check(!sample.sample(now));
    now.total += 10; now.busy += 11;
    check(!sample.sample(now));
    check(!parse("version=1"));
    check(!parse("version=1 version=1"));
    check(!parse("version=-1"));
    check(!parse("version=18446744073709551616"));
    check(!parse("version=1x"));
    check(!parse(valid + "version=1"));
    for (const auto &change : {std::pair{"version=1", "version=2"},
                               std::pair{"healthy=1", "healthy=2"},
                               std::pair{"busy_ns=200", "busy_ns=1001"},
                               std::pair{"untracked_ns=0", "untracked_ns=1001"}}) {
        auto bad = valid;
        bad.replace(bad.find(change.first), std::string(change.first).size(), change.second);
        check(!parse(bad));
    }
    std::cout << "PASS: utilization, idle, busy, legacy, faults, reload, rollback and parser rejection\n";
}

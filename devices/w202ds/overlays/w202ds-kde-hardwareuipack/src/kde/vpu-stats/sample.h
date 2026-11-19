// SPDX-License-Identifier: MIT
#pragma once
#include <charconv>
#include <cstdint>
#include <map>
#include <optional>
#include <sstream>
#include <string>

namespace VpuStats {
struct Snapshot {
    uint64_t generation, total, busy, untracked, frequency;
    bool healthy;
};

inline std::optional<Snapshot> parse(const std::string &text)
{
    std::map<std::string, uint64_t> fields;
    std::istringstream input(text);
    std::string token;
    while (input >> token) {
        const auto split = token.find('=');
        if (split == std::string::npos || split == 0) return {};
        const auto value = token.substr(split + 1);
        uint64_t number;
        const auto result = std::from_chars(value.data(), value.data() + value.size(), number);
        if (result.ec != std::errc() || result.ptr != value.data() + value.size()
            || !fields.emplace(token.substr(0, split), number).second) return {};
    }
    for (auto key : {"version", "generation", "total_ns", "busy_ns", "untracked_ns", "healthy", "frequency_hz"}) {
        if (!fields.count(key)) return {};
    }
    if (fields["version"] != 1 || fields["healthy"] > 1
        || fields["busy_ns"] > fields["total_ns"]
        || fields["untracked_ns"] > fields["total_ns"]) return {};
    return Snapshot{fields["generation"], fields["total_ns"], fields["busy_ns"],
                    fields["untracked_ns"], fields["frequency_hz"], fields["healthy"] == 1};
}

class Sampler {
    std::optional<Snapshot> previous;
public:
    void clear() { previous.reset(); }
    std::optional<double> sample(const Snapshot &now)
    {
        const auto before = previous;
        previous = now;
        if (!before || !before->healthy || !now.healthy
            || now.generation != before->generation || now.total <= before->total
            || now.busy < before->busy || now.untracked != before->untracked) return {};
        const auto duration = now.total - before->total;
        const auto busy = now.busy - before->busy;
        if (busy > duration) return {};
        return 100.0 * static_cast<double>(busy) / static_cast<double>(duration);
    }
};
}

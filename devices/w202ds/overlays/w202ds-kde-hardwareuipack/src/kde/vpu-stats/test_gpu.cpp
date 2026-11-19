// SPDX-License-Identifier: MIT
#include "gpu_sample.h"
#include <cassert>
#include <iostream>
int main() {
    GpuClients a{{"1", {{"fragment", 100}, {"vertex", 200}}}};
    GpuClients b{{"1", {{"fragment", 150}, {"vertex", 225}}}};
    auto r = gpuSample(a,b,100); assert(r.percent == 50 && !r.partial);
    b["2"] = {{"fragment",99999}};
    r = gpuSample(a,b,100); assert(r.percent == 50 && r.partial);
    r = gpuSample(b,a,100); assert(std::isnan(r.percent)); // rollback is not zero
    auto c=b; c["1"]["fragment"]=200; c.remove("2");
    r=gpuSample(b,c,100); assert(r.percent==50 && r.partial);
    c["1"]["fragment"]=1000;
    r=gpuSample(a,c,100);assert(r.percent==100 && !r.partial);
    assert(std::isnan(gpuSample({},a,100).percent));
    assert(std::isnan(gpuSample(a,b,0).percent));
    assert(std::isnan(gpuSample(a,{{"2",{{"fragment",200}}}},100).percent));
    r=gpuSample(a,a,100);assert(r.percent==0 && !r.partial);
    std::cout << "PASS: GPU occupancy, churn coverage, saturation, idle, reset and baseline\n";
}

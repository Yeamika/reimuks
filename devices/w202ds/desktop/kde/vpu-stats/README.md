# KDE GPU / VPU 监控适配

可选 KSystemStats 插件，通过更新后的 VPU 驱动只读 `utilization` 接口提供传感器：

| 传感器 ID | 内容 |
| --- | --- |
| vpu/decoder/usage | 原生解码任务占用率，0–100% |
| vpu/decoder/frequency | 时钟框架报告的频率，MHz |
| vpu/decoder/status | 统计可用性及故障说明 |
| w202gpu/panfrost/usage | 当前用户可读 DRM 客户端的引擎占用率 |
| w202gpu/panfrost/frequency | GPU devfreq 频率，MHz |
| w202gpu/panfrost/status | GPU 统计可用性说明 |

驱动接口路径为 `/sys/class/misc/sprd_vsp/device/utilization`，无需 root 或硬件控制权限。
读取统计不唤醒 VPU。使用率是 START 到 IRQ／成功复位的任务占用比例，
不是内部计算单元饱和度。旧用户态直接写寄存器的 MMIO 路径无法精确统计，
相应采样窗口使用 NaN 表示无有效数值，并通过 status 解释，不显示为 0%。
初始采样、接口缺失、格式错误、模块重载、故障与计数回退同样不伪造百分比。

## 构建与安装

先构建并部署 kernel 项目中的匹配 VPU 模块（接口说明为 `Devices/vpu/source/utilization.md`）。
插件需要与目标 KDE 安装匹配的 Qt 6、KDE Frameworks 6 和 libksysguard。
Debian trixie 构建依赖为 `build-essential cmake extra-cmake-modules qt6-base-dev
libkf6coreaddons-dev libksysguard-dev libsensors-dev`，运行时需要 `ksystemstats`、`plasma-systemmonitor`。

在本目录执行：

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build
ctest --test-dir build --output-on-failure
sudo cmake --install build
```

不要把其他 CPU 架构编译的插件安装到目标系统。插件安装到 Qt 6 的
`ksystemstats` 插件目录；安装后注销重新登录，使 KSystemStats 重新发现插件。
卸载使用 `build/install_manifest.txt` 列出的文件，并重新登录。

GPU 统计读取 Panfrost DRM fdinfo，按 drm-client-id 去重，使用 fragment/vertex
引擎占用率的较大值，避免把并行引擎相加成超过 100%。只统计当前用户可读客户端，
不等同于全系统 GPU 使用率。需要 Panfrost profiling 开启；配套 udev 规则负责开启。
客户端增减时保留具有连续基线的客户端采样，并通过 status 标明覆盖不完整；
新客户端在下一次采样建立基线后参与统计。并行任务计时或快照偏差导致超过
一个采样窗口时饱和到 100%。无有效基线、计数回退或计数不可用时返回 NaN，不伪造 0%。

REIMUKS 的 KDE 用户默认概览保留内存、磁盘、CPU，并增加 GPU、VPU 一行；
通过 skeleton 为新用户提供默认值，不覆盖已有用户布局。
也可在 KDE 系统监视器编辑自定义页面，或添加“系统监视器传感器”面板部件，
搜索 VPU，选择使用率、频率及状态。插件注册传感器，不自动改写个人页面布局。
插件已在目标设备完成加载与传感器注册测试；NaN 图表显示、浏览器硬解负载和空闲后电源挂起仍需分别验证。

VPU 采样逻辑测试不依赖 Qt，可单独编译 `test_sample.cpp`；
GPU 客户端采样测试 `test_gpu.cpp` 依赖 Qt Core。构建产物通过不代表已经
在目标设备加载成功；完整链路需要新驱动和匹配架构的插件同时部署。

插件接口参照 [KDE KSystemStats 插件](https://github.com/KDE/ksystemstats/tree/Plasma/6.3/plugins)
和 [libksysguard SensorPlugin](https://github.com/KDE/libksysguard/blob/Plasma/6.3/systemstats/SensorPlugin.h)。

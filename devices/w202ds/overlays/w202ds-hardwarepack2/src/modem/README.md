# 桌面共享蜂窝网络集成

板级运行服务和 ModemManager 插件来自 kernel 项目的 `Devices/modem/userspace/`。本目录只定义 REIMUKS 的系统服务和网络管理策略，不修改内核或原厂 NV 分区。

需要匹配的 ARM64 ModemManager 适配包、固件和本设备私有 NV；私有输入按板级组件的 `RUNTIME.md` 配置，不随源码发布。先完成板级运行服务验收，再接入桌面网络管理。

- `rootfs/desktop-common/etc/systemd/system/ModemManager.service.d/w202ds.conf` 安装到目标 `/etc/systemd/system/ModemManager.service.d/`，使用 `/opt/w202ds/modemmanager` 中的匹配 daemon 和私有库；保留发行版自己的 D-Bus 策略及系统 libmm-glib。
- `rootfs/desktop-common/etc/NetworkManager/conf.d/31-w202-sipa-internal.conf` 安装到目标 `/etc/NetworkManager/conf.d/`，将 `sipa_dummy*` 排除出连接管理；保持内部 NAPI 网口的驱动状态，真实数据接口仍由 MM/NM 管理。
- MM 工程的 `src/plugins/w202ds/77-mm-w202ds.rules` 随相应插件包安装。

桌面采用 MM → NM → KDE 标准链路；独立 `w202-cellular` 后端不能同时管理相同的数据连接。APN、自动连接、路由优先级及 SIM 授权由 REIMUKS 配置和目标用户决定。共享桌面策略启用蜂窝栈；打包前必须完成适配器构建，部署前必须提供设备私有输入。

`rootfs/common/etc/default/w202-modem-runtime` 定义板级运行目录、固件入口及独立启动准备策略，
由板级包管理，不放进 user overlay。固件、设备 NV 仍须单独提供；
用户 APN、自动连接和凭据继续由 NetworkManager/KDE 保存。

本目录定义 ModemManager/NetworkManager 的共享接入，不依赖 Plasma。
ModemManager 的 D-Bus 服务不硬依赖基带运行服务：硬件关闭或初始化失败时，
桌面仍能查询管理接口，避免等满 D-Bus 激活超时。硬件开关仍由板级运行服务管理。
KDE 和 GNOME 可使用各自原生网络界面；私有固件、MM 适配包及实机验证仍须另行准备。
本目录保存集成说明，实际离线策略由板级 rootfs 模板维护。

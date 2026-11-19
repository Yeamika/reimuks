# W202DS

- [debian-server](targets/debian-server.json)：控制台、电源键和霍尔策略。合盖两秒息屏，开盖恢复，系统继续运行。
- [debian-kde](targets/debian-kde.json) 组合 Pack2 和 KDE 适配；[debian-kde-remote](targets/debian-kde-remote.json) 还加入远程应用、TUI 工具及 `passkey`、`kde-theme`，输出 rootfs。
- [debian-niri](targets/debian-niri.json) 组合 Pack2、Niri 和 passkey，输出 rootfs。

板级声明在 [board.json](board.json) 和 [overlays/](overlays/)。[Pack2](overlays/w202ds-hardwarepack2/src/README.md) 提供共享控制接口，[KDE 适配](overlays/w202ds-kde-hardwareuipack/src/kde/README.md) 负责界面和会话。内核和启动源码由 [子模块](../../.gitmodules) 提供。

Pack2 的本地工具链配置以 [build.example.json](overlays/w202ds-hardwarepack2/build.example.json) 为模板。需要私有基带 NV 的预设在配方中指定 `rootfs.device_state`。

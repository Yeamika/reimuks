# 板级通用 DE 兼容包

W202DS 包名为 `reimuks-w202ds-de-compat`，依赖板级基础包及 `reimuks-de-common`，不依赖 Plasma、KWin 或 GNOME Shell。

负责硬件与标准桌面服务的接入：合盖输入、GNSS、蓝牙状态、统一硬件控制、NetworkManager/ModemManager 接入、权限与视频接口。KDE、GNOME 共用同一个包。

源码与策略继续位于 `devices/w202ds/desktop/common/` 和 `devices/w202ds/rootfs/desktop-common/`；本目录是构建入口说明，不复制源码。

```sh
python3 scripts/layers.py pack --profile kde --context build/kde/rootfs
```

包输出 `build/artifacts/layers/reimuks-w202ds-de-compat.deb`。该命令同时生成当前组合的其余包；`--profile gnome` 复用相同的兼容包。

# 板级基础包

板级基础服务、固件接口和硬件运行库。W202DS 包名为 `reimuks-w202ds-board`，不依赖 KDE/GNOME。

配置入口为 `devices/w202ds/rootfs/packages.json` 的 `board`，内容来自 `rootfs/policy.json` 的 `common`。硬件源码仍由设备 Linux 工程维护。

```sh
python3 scripts/layers.py pack --profile server
```

产物在 `build/artifacts/layers/`。Server 的登录、网络和合盖行为另由 `reimuks-w202ds-server` 提供，不混入板级基础包。

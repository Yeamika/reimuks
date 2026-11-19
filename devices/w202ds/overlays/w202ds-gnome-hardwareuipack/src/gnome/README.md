# W202DS GNOME 会话适配

硬件、固件、初始化和统一控制复用
[公共硬件层](../../../w202ds-hardwarepack2/src/README.md)。本目录只处理
GNOME 自己的会话接口，随 `reimuks-w202ds-gnome` 安装；标准 GNOME 来自发行版包。

`/usr/libexec/w202-gnome-controls` 是 C 入口，应由登录用户在 GNOME 会话中调用。
硬件请求原样转发给 `w202-device-controls`；状态合并沿用 KDE 的公共实现。

| 动作 | GNOME 接口 |
| --- | --- |
| `status` | 公共硬件状态，加上旋转锁定和屏幕键盘偏好 |
| `rotation-on` / `rotation-off` | `org.gnome.settings-daemon.peripherals.touchscreen orientation-lock` 的反向值 |
| `keyboard-on` / `keyboard-off` | `org.gnome.desktop.a11y.applications screen-keyboard-enabled` |
| Wi-Fi、蜂窝、蓝牙、GNSS、充电、USB、手电筒 | 共享板级控制入口及既有授权 |

GSettings 写入前检查可写性，写入后读回；缺失状态为 `null`，失败返回非零退出码。
旋转和键盘字段表示用户设置，实际旋转依赖 SensorProxy、Mutter 和设备能力。
GNOME 使用自身平板模式判断，此入口不提供手动覆盖，`tablet` 返回 `null`。
不强制写入用户默认值，设置仍可通过 GNOME 原生界面调整。

```sh
make -C devices/w202ds/overlays/w202ds-gnome-hardwareuipack/src/gnome stage CC=aarch64-linux-gnu-gcc
```

默认暂存到 `build/boards/w202ds/desktop-gnome/rootfs/`。完整板型构建按 GNOME profile
自动调用本入口，只要求 C 编译器与板级公共头文件；不构建 KDE 或依赖 Qt SDK。
登录、合盖、传感器旋转和屏幕键盘仍由 GNOME 自身服务处理。

离线测试覆盖请求转发、设置反向含义、读回失败和缺失状态。GNOME Shell 专属
快捷按钮和新会话入口的实机验收仍待完成。

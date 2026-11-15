# Rootfs profiles

GNOME 的构建入口及实验限制见 [desktop/gnome.md](desktop/gnome.md)。

图形桌面统一使用 Wayland：KDE 的 SDDM 登录界面运行 KWin Wayland，仅列出 Wayland
会话；GNOME 的 GDM 启用 Wayland、禁用 Xorg 回退。保留 XWayland 作为旧应用兼容层，
不表示桌面运行 X11。配置随新 rootfs 打包生效，尚需实机验证登录与图形驱动。

| Profile | W202DS 状态 | 内核与功能 |
| --- | --- | --- |
| desktop/server | 可构建 | desktop 内核，命令行屏幕，systemd multi-user.target |
| desktop/kde | 可构建 | 同一 desktop 内核，Plasma/SDDM，graphical.target |
| desktop/gnome | 实验配置 | 同一 desktop 内核，GNOME/GDM，graphical.target；尚未实机验证 |
| desktop/niri | 占位 | 尚未实现软件包清单及桌面配置 |
| server | 占位 | 真正的 Server 方案；W202DS 未提供对应内核 |

`desktop/server` 也是各桌面 profile 的基础用户态，不等于顶层 server。
发行版通过 `--distribution` 独立选择；当前只提供 Debian trixie ARM64。
具体软件包映射、软件源与发行版版本归入 [`distributions/`](../distributions/README.md)，
本目录只描述用途、启动目标、继承和占位状态。Niri 占位文件不参与构建。
底层脚本和现有缓存暂保留内部名称 server、kde、gnome，公开入口使用完整 profile 名。

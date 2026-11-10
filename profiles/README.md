# Rootfs profiles

| Profile | W202DS 状态 | 内核与功能 |
| --- | --- | --- |
| desktop/server | 可构建 | desktop 内核，命令行屏幕，systemd multi-user.target |
| desktop/kde | 可构建 | 同一 desktop 内核，Plasma/SDDM，graphical.target |
| desktop/gnome | 占位 | 尚未实现软件包清单及桌面配置 |
| desktop/niri | 占位 | 尚未实现软件包清单及桌面配置 |
| server | 占位 | 真正的 Server 方案；W202DS 未提供对应内核 |

`desktop/server` 也是各桌面 profile 的基础用户态，不等于顶层 server。
当前发行版均为 Debian trixie ARM64。GNOME/Niri 占位文件不参与构建。
底层脚本和现有缓存暂保留内部名称 server、kde，公开入口使用完整 profile 名。

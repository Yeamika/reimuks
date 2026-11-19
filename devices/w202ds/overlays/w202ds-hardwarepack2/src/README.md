# W202DS Pack2 接口

`/usr/libexec/w202-device-controls status` 输出 JSON（schema 1）。`false` 表示关闭，`null` 表示状态未知。操作后读回实际状态；KDE 和 GNOME 的会话入口只追加自己的状态。

Pack2 负责无线开关、STA/AP 切换及恢复。连接、密码、频段和信道由用户通过 NetworkManager 配置。只有一个匹配的热点时可直接开启；有多个匹配热点时，从 NetworkManager 的连接列表启用所需热点。

`w202-usb-settings` 保存 OTG/Device/Host 预选及 ACM/NCM 组合至 `/var/lib/reimuks/usb.conf`。`usb.actual` 是实际角色与绑定，可与预选不同。切到 Host 可能断开 USB 网络和串口。

ModemManager 和 NetworkManager 的板级策略随 Pack2 安装。基带适配器、固件和设备私有 NV 是独立输入。

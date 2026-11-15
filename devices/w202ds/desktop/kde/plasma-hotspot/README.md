# Plasma Wi-Fi 模式控制

提供 STA、AP 两个图标按钮；两者互斥，均关闭时关闭 Wi-Fi 无线。
从 AP 切到 STA 时先断开 AP，再恢复设备自动连接许可。切换不改写保存连接的自动连接、密码、地址或安全性配置。

连接由用户在 KDE“系统设置 → 网络 → 连接”中创建和编辑。
工具不创建 AP 配置，不提供默认 SSID、密码、频段、信道宽度或地址，也不提供默认网口共享配置。
只有一个适用于 wlan0 的 AP 配置时，AP 按钮激活该配置；存在多个配置时，需用户在 KDE 中明确激活所需连接，不替用户选择。
托盘只提供开关和状态，不添加 AP 专用配置菜单。

安装器从系统 Plasma NM applet 建立用户覆盖，原系统文件由包管理器维护。
不按包版本白名单拒绝安装；使用前检查所需 QML 结构，无法明确应用补丁时报错。
辅助程序使用 NetworkManager D-Bus 与现有桌面授权，不添加网络管理提权规则。
W202DS AP 扫描保护针对本板驱动；dispatcher 仅处理 wlan0 当前确实处于 AP 模式的 up 事件，不改连接设置。

在目标系统以 Plasma 用户运行：

```sh
python3 -B install.py
systemctl --user restart plasma-plasmashell.service
```

运行时依赖原生 C 辅助程序、systemd/busctl、NetworkManager、Plasma NM 和 Plasma5Support executable 引擎。
安装器与测试使用 Python 3，运行时不使用 Python/GIO。
测试：`python3 -B test_helper.py`、`python3 -B test_dispatcher.py`；
QML 流程测试使用 `qmltestrunner -input tests`。真实 STA/AP 切换会断开 Wi-Fi 管理连接，需独立控制通道。

安装记录和本工具先前版本保存在用户的 `~/.local/state/w202ds/plasma-hotspot/`。
安装器拒绝覆盖其他工具的 applet、helper 或 dispatcher。用户覆盖移除后，重启 plasmashell 可回到发行版网络控件。

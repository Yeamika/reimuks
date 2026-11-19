# KDE GNSS 开关

可选的应用菜单入口，可右键固定到 Plasma 面板。点击读取 GNSS rfkill 的实际电源请求
及接收服务状态，再选择开启或关闭；不是 Plasma 网络面板插件，不持续轮询。
电源请求不等于已定位，也不代表共享芯片的实际供电状态。

## 依赖与安装

需要 systemd、原生 C 控制程序、KDE kdialog、polkit/pkexec 及会话认证代理。
先安装板级 GNSS 电源驱动、固件和 kernel 项目提供的 `w202ds-gnss`
（对应 `Devices/wcn/userspace` 的 `install-gnss` 目标）。确认存在
`/dev/data0_gnss` 和名为 `w202ds-gnss` 的 rfkill 接口。

在本目录运行 `sudo sh install.sh`。安装仅刷新 systemd 单元，不开启接收，不设置开机启动。
应用菜单搜索“GNSS 定位开关”，右键添加到面板。每次修改需要管理员认证；取消认证不操作硬件。

## 行为与边界

- 开启运行独占、最长一小时的接收会话，结束后自动释放；需继续使用时再次开启。
- 关闭只停止本服务，通过现有工具发送停止、休眠并释放 GNSS 电源请求。
  读回仍开启或接口消失时报告失败，不直接写 rfkill 强关其他会话。
- 不重启 WCN，不修改 Wi-Fi、蓝牙或其他 rfkill，不接受自定义命令、单元或设备参数。
- 启动成功表示进程启动，不保证协议握手或定位成功；再次打开按钮可查看服务退出状态。
- NMEA 输出丢弃，不把精确坐标写入 journal；协议诊断仍可通过
  `journalctl -u w202-gnss.service` 查看。
- 本入口尚未向 gpsd、GeoClue 或地图应用提供定位数据，不能代表 KDE 应用已经获得位置。

本地策略测试：`python3 test_control.py`。实机验收需确认开启后接收、关闭后 rfkill
恢复阻断、连续切换以及 Wi-Fi/蓝牙保持正常；代码检查不能代替这些硬件验证。

卸载前先停止 `w202-gnss.service`，确认电源请求已释放，再删除安装脚本列出的五个文件，
执行 `systemctl daemon-reload` 并移除面板入口。

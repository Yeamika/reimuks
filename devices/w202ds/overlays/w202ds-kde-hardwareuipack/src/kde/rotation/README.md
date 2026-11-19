# KDE 自动旋转开关

可选应用菜单入口，可右键添加到 Plasma 面板。打开时读取 KDE 实际策略，提供
“开启自动旋转”和“锁定当前方向”。保留并单独显示原有“仅平板模式”策略；
点击开启后选择 Always，不依赖设备是否报告平板模式。关闭选择 Never，保留当前方向。
应用后重新读取策略，不用本地标记文件模拟状态。

USB 或蓝牙实体键盘接入后，会话监听器在约两秒内锁定当前方向；键盘保持连接时
按钮的两个操作均禁用。拔掉键盘后按钮恢复可用，不自动重新开启旋转。
使用 udev 的键盘标记及 USB/蓝牙父设备识别，不把电源键、音量键或虚拟键盘当作外接键盘。
其他总线的专用键盘底座需要根据实际设备标记补充识别。

## 依赖与构建

需要 KDE Plasma Wayland、Qt 6 Widgets、libkscreen 6.3 或更新版本、CMake 和 C++17 编译器。
Debian 构建依赖为 `build-essential cmake pkg-config qt6-base-dev libkscreen-dev libudev-dev`。
加速度计驱动和传感器方向映射须正确，`iio-sensor-proxy` 须向桌面提供有效方向数据。

在本目录构建安装：

```sh
cmake -S . -B build -DCMAKE_INSTALL_PREFIX="$HOME/.local"
cmake --build build
cmake --install build
mkdir -p "$HOME/.config/autostart"
cp "$HOME/.local/share/w202-rotation/w202-rotation-watch.desktop" "$HOME/.config/autostart/"
```

确保用户的 `.local/bin` 在桌面会话 PATH 中，再从应用菜单将“自动旋转开关”添加到面板。
不需要 root 或 polkit。下次登录启动键盘监听；当前会话可运行 `w202-rotation --watch`。
卸载前退出监听进程，删除上述自启动文件及安装前缀下的
`bin/w202-rotation`、`share/applications/w202-rotation.desktop` 和 `share/w202-rotation/`。

只处理 KDE 报告支持 AutoRotation 的唯一已启用内置屏幕，能力缺失或屏幕选择有歧义时
提示错误，不选外接屏替代。设置策略成功不证明传感器产生了正确数据；仍需实机验证
四个方向、锁定后不旋转、触摸坐标跟随及注销后策略持久性。

使用 [libkscreen 6.3.4 的公开 Output API](https://github.com/KDE/libkscreen/blob/v6.3.4/src/output.h)
设置策略，兼容该版本尚无自动旋转命令的 kscreen-doctor。

# W202DS KDE 行为集成

硬件服务和统一控制协议见
[`w202ds-hardwarepack2`](../../../w202ds-hardwarepack2/src/README.md)，由 KDE、GNOME 共用。
本目录保留 Plasma、KWin、KSystemStats 的界面与会话适配。
`session/Makefile` 单独构建 KDE 的 C 会话程序，输出到
`build/boards/w202ds/desktop-kde/rootfs/`；公共构建不再编译这些程序。
KDE 硬件按钮继续使用原来的入口与 JSON 字段。

KWin 会话默认使用 EGL/OpenGL ES，配置位于用户服务
`plasma-kwin_wayland.service.d/60-w202-gles.conf`，不改变应用选择的图形 API。
桌面 OpenGL 与 GLES 共用 Panfrost；独立 Vulkan 应用使用板级 PanVK 启动器。
Plasma 6.3 的 KWin 没有原生 Vulkan 合成后端，不能将 Vulkan 应用测试视为
KWin Vulkan 后端验证。用户可通过标准用户服务 override 调整合成模式。

当前显示驱动使用物理连续缓冲，尚不能导入任意 GPU DMA-BUF。KWin 和 SDDM
因此关闭客户端直接扫描尝试，继续使用 GPU 合成至显示侧分配的缓冲；不关闭
GPU 加速，也不屏蔽错误日志。接通并验证 VAU/IOMMU 导入后才能解除此限制。

## 弹窗缓存

`popup-cache/` 提供 QML 扩展，通过公开的 `KSvg::ImageSet::setCacheLimit`
将主题共享缓存预算设为 128 MiB；KSvg 6.13 对应 16 MiB 的本地解码图缓存，
避免大尺寸弹窗遮罩反复在 GUI 线程解码。默认线程渲染和 GPU 加速保持启用。
该优化不代表图形 API 完整一致性认证，也不消除所有界面停顿。
构建 SDK 需提供 `libkf6svg-dev` 及其依赖；目标系统使用发行版 KSvg 库。
扩展随 KDE 适配包安装，系统托盘用户副本导入，不替换发行版库或使用 LD_PRELOAD。

## 软件包来源

Plasma、KWin 和 Plasma NM 的版本由所选发行版的软件源决定，代码和默认包列表不固定桌面版本号。
构建清单记录本次实际安装版本；换用其他软件源时仍需验证界面适配和监控插件。

### 小部件覆盖与升级

`prepare.py` 从发行版原件复制系统托盘、电池和网络三个完整小部件，检查结构后
仅修改副本，安装到 `/etc/skel/.local/share/plasma/plasmoids/`。打包流程为默认用户
复制 skeleton，新建用户也会得到这些默认值；不会改写 `/usr/share/plasma/plasmoids/`
中由 APT 管理的文件。已有用户的同名文件不会被 skeleton 强制覆盖。

`apt update` 只刷新软件包索引。`apt upgrade` 不会覆盖家目录中的小部件，但这些副本
也不会自动获得上游的修复；升级 Plasma 后需检查兼容性，并基于新版原件重新生成。
删除家目录中对应的三个覆盖目录、重新登录，即可恢复发行版小部件。

- [`plasma-hardware/`](plasma-hardware/README.md) 维护状态和通知快捷控制及电池弹窗集成，使用用户级 applet 覆盖，不覆盖系统包。

- [`vpu-stats/`](vpu-stats/README.md) 提供可选 KSystemStats 插件，接入新 VPU 驱动的任务占用率、频率和可用状态，可由系统监视器及面板选择显示。

- [`rotation/`](rotation/README.md) 提供可固定到面板的自动旋转开关，读取并设置 KDE 内置屏幕策略，支持锁定当前方向；需要 Wayland 和有效方向传感器。

- [`gnss/`](gnss/README.md) 提供可固定到面板的 GNSS 开关入口，读取真实电源请求状态，采用独占、限时接收服务；可选安装，不默认开启。

- 虚拟键盘联动资源放在 `../../files/kde/usr/share/kwin/scripts/w202ds-tablet-keyboard/`，随 KDE profile 打包；会话中的启用及 Maliit 配置见包内 README。
- [`plasma-hotspot/`](plasma-hotspot/README.md) 维护可选的 Plasma NM Wi-Fi 总开关、STA/AP 互斥和双关控制，安装时检查 QML 结构，不默认修改桌面。
- [`w202ds-hardwarepack2 modem`](../../../w202ds-hardwarepack2/src/modem/README.md) 定义 ModemManager/NetworkManager 接入、服务依赖及内部网口排除规则；依赖匹配的 MM 适配包和设备私有固件/NV，不默认启用。

底层驱动、协议和初始化实现留在 kernel 项目 `Devices/<设备>/userspace/`。此处负责应用这些机制的桌面行为，不复制另一设备的网络、SIM 或私有状态。

## USB 数据角色

USB 控件调用共享 `w202-device-controls` / `w202-usb-settings`，仅维护界面编辑状态。
OTG/Device/Host 预期、实际角色以及 ACM/NCM 功能组合的实现和读回见
[公共接口](../../../w202ds-hardwarepack2/src/README.md#usb-策略)。Host 切换可能断开该口的 NCM/ACM，
Type-C DP Alt Mode 能力需独立验证；按钮存在不代表外接显示已经接通。

## 霍尔与合盖

板级驱动只报告磁感应状态，KDE 的 `w202-hall.conf` 选择 `switch_code=-1`。
`w202-hall-input.service` 使用板级标准输入桥，将有效状态稳定 2000 ms 后发布为
`EV_SW/SW_LID`，开盖立即发布并取消待处理的合盖。去抖参数由 REIMUKS 决定，
不固定在驱动里。服务在创建 input 设备后报告就绪，先于 UPower 启动。

桌面电源管理使用标准盖子状态，不直接读取 GPIO。KDE 会话的 `w202-lid-wake`
监听 UPower 的真实关到开转换，仅当 PowerDevil 当前合盖策略为“关闭屏幕”时，
明确请求 Wayland DPMS On，并在一秒后复核式重发一次以覆盖晚完成的关闭动作；
新的合盖会取消重发。它不在启动时强制亮屏，也不覆盖用户选择的其他合盖策略。

`desktop/kde` 不安装 Server 的忽略合盖策略。用户在 KDE「系统设置 → 电源管理」
选择「合上笔记本盖时」的动作；具体选项取决于设备被识别到的能力。检查时可只读查询
logind 的 `LidClosed`、UPower 的 lid 属性和 input 事件；不可仅因配置文件存在就声称
PowerDevil 已在当前会话接管。测试合盖前应核对当前动作，避免无意触发休眠或关机。

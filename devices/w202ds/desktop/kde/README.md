# W202DS KDE 行为集成

硬件服务和统一控制协议见 [`../common/`](../common/README.md)，由 KDE、GNOME 共用。
本目录保留 Plasma、KWin、KSystemStats 的界面与会话适配。

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

- 虚拟键盘联动资源放在 `../../rootfs/profiles/desktop/kde/usr/share/kwin/scripts/w202ds-tablet-keyboard/`，随 desktop/kde 打包；会话中的启用及 Maliit 配置见包内 README。
- [`plasma-hotspot/`](plasma-hotspot/README.md) 维护可选的 Plasma NM Wi-Fi 总开关、STA/AP 互斥和双关控制，安装时检查 QML 结构，不默认修改桌面。
- [`../common/modem/`](../common/modem/README.md) 定义 ModemManager/NetworkManager 接入、服务依赖及内部网口排除规则；依赖匹配的 MM 适配包和设备私有固件/NV，不默认启用。

底层驱动、协议和初始化实现留在 kernel 项目 `Devices/<设备>/userspace/`。此处负责应用这些机制的桌面行为，不复制另一设备的网络、SIM 或私有状态。

## USB 数据角色

现有板级 USB gadget 服务提供 ACM 串口和 NCM 网络。KDE 的网络面板可管理 NCM
网络连接，但这不等于切换 USB 的 host/device 数据角色。桌面角色按钮需要先确认运行内核
实际提供可写的 Type-C `data_role` 或 USB role-switch 接口，并完成主机供电、gadget
解绑与恢复的板级验证；设备树声明 `usb-role-switch` 本身不代表这些条件已满足。
当前不添加声称可以切换的按钮，也不使用卸载驱动或写 debugfs 模拟通用角色接口。
切换到 host 会断开该口的 NCM/ACM，桌面操作应明确提示此影响。

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

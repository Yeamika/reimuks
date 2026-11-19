# W202DS 桌面整合接口

控制链按职责分层，当前以 KDE 验收为主：

```text
w202ds-linux / Devices
  驱动、标准 Linux 接口、C 硬件工具
                  ↓
REIMUKS / overlays/w202ds-hardwarepack2
  C 整合入口、服务所有权、授权、策略、开关与状态数据
                  ↓
REIMUKS / overlays/w202ds-kde-hardwareuipack
  Plasma 界面、KWin 会话策略、KSystemStats 监控适配
                  ↓
KDE 用户界面
```

GNOME 的少量会话适配位于 `w202ds-gnome-hardwareuipack/src/gnome/`，硬件控制与 KDE 使用同一入口。
REIMUKS 不重复实现充电寄存器、GNSS 协议或手电筒硬件访问。
`desktop/server` 也复用相同的公共硬件和整合入口，安装标准服务/API 运行库；
只额外选择全屏控制台登录、错误日志和合盖保持运行，不安装具体 DE 会话。

| 所属 | 实现 |
| --- | --- |
| Linux `Devices/charging/userspace/source/` | C 充电控制、PD profile 选择与读回、失败时保持 PPS 关闭 |
| Linux `Devices/wcn/userspace/gnss/` | C GNSS 协议、独占接收、校验、停止和电源释放 |
| Linux `Devices/hall/userspace/source/` | C 标准 input 桥、可配置编码与去抖 |
| Linux `Devices/camera/userspace/source/` | C LED class 亮度控制与边界检查 |
| Linux `Devices/modem/userspace/runtime/` | C 私有 NV 校验及 loop 映射工具 |
| REIMUKS `overlays/w202ds-hardwarepack2/src/device-controls/source/` | C JSON 入口、NM/BlueZ 接入、GNSS 服务所有权、蓝牙状态记忆、STA/AP 互斥 |
| REIMUKS `overlays/w202ds-kde-hardwareuipack/src/kde/session/` | KDE 会话入口、平板模式、通知、合盖唤醒、可选 GNSS 对话框 |
| REIMUKS `overlays/w202ds-gnome-hardwareuipack/src/gnome/session/` | GNOME 会话入口、旋转锁定与屏幕键盘偏好 |

这条控制链不安装或调用 Python helper，也不使用 Rust。已有旋转与监控插件继续
使用原生 C++/Qt/KDE 接口；QML/KWin 脚本属于桌面本身。
Python 仅用于构建、安装、测试及保留在 tests 中的旧实现对照，不是运行时依赖。
系统服务和初始化中仍有 shell 脚本；本次不把 shell 初始化改造成新守护程序。

## 接口

`/usr/libexec/w202-device-controls` 是短时运行的 C 整合程序，不是常驻大服务。
NetworkManager、BlueZ、GNSS 接收等仍各自负责其生命周期。
网络请求使用系统原生 `busctl`；常驻监听程序使用 libsystemd 的 sd-bus 订阅信号，
不通过高权限总线监听器窃听，也不使用 Python/GIO。
特权写入仍使用固定 helper 与原有 Polkit 授权。

公共层显式启动 SensorProxy，Server 同样提供传感器服务接口。蓝牙恢复已保存的
开启状态时，只解除对应 HCI 控制器的软件 rfkill，保留硬件屏蔽以及其他无线设备状态；
重试使用退避，已达到目标状态时不重复写入。

```sh
/usr/libexec/w202-device-controls status
/usr/libexec/w202-device-controls gnss-on
/usr/libexec/w202-device-controls gnss-off
```

支持 `wifi/cellular/bluetooth/gnss/fast/separation/torch` 的 `-on/-off`，
`torch-0` 至 `torch-8`，以及 `mode-auto/mode-pps/mode-pd9v/mode-pd5v`。
请求不代表硬件已成功完成；必须读回状态。
STA/AP 互斥由 `w202-hotspot-switch` 实现，使用用户已有的 NM 连接，不创建 SSID、
密码、安全性或地址配置。它负责断开和设备自动连接许可，不修改保存连接。

Wi-Fi／蜂窝总开关只操作 NetworkManager 的硬件无线许可；APN、连接、自动连接和路由
由桌面的原生网络设置管理。`w202-wifi-recover.timer` 每 20 秒检查一次板级 supplicant
绑定，仅在无线已打开、设备由 NM 管理且驱动状态明确缺少 nl80211 的 phyname 时，
移除错误回退的 WEXT 接口，让 NM 重新绑定。健康、关闭或非托管接口不处理，
不重启共享 WCN，也不创建或修改用户连接。

JSON schema 1 包含 `ok`、`states`、`capabilities`、`protocol`、`power`、`torch`、`usb`。
状态 `false` 表示明确关闭；`null` 表示无法确定，不可显示为关闭。
capability 的 `available` 仅表示当前能读到有效状态，不保证授权或后续写入成功；
`reason` 说明不可用。详情对象沿用硬件工具的数据。
命令失败返回 `ok: false`、`error` 和非零退出码。
界面应异步调用并串行处理切换；子进程、输出大小和请求时间均有界限。

KDE 的 `w202-hardware-controls` 和 GNOME 的 `w202-gnome-controls` 调用同一整合入口，
只追加各自会话状态。`source/session.h` 复用转发和 JSON 合并，保留所有硬件字段与
扩展字段。KDE 原 QML 调用路径不变；共享后端不执行具体 DE 的会话命令。

IMU、加速度计和方向通过 IIO 与 `net.hadess.SensorProxy` 提供；霍尔和键盘提供
标准 input/logind 状态。音频走 ALSA/PipeWire，视频走 DRM、V4L2 和 VA-API。
这些接口不要求桌面重新实现硬件初始化，也不由 `status` 伪造尚未读取的状态。

## 构建与打包

需要 C 编译器、GNU make、目标 libc 和 libsystemd；交叉编译时使用匹配的 ARM64
sysroot。正常开发环境可安装 libsystemd 开发包；精简工具链可使用源码中仅含不透明
句柄的稳定公共 API 声明，不依赖 systemd 私有结构。

```sh
sh devices/w202ds/overlays/w202ds-hardwarepack2/src/device-controls/build.sh CC=aarch64-linux-gnu-gcc
```

本入口只构建共享程序，暂存到 `build/boards/w202ds/device-controls/rootfs/`。
硬件由 `scripts/board-build.py` 单独构建；具体 DE 的构建由板型构建入口按 profile 选择。
KDE 会话程序暂存在 `build/boards/w202ds/desktop-kde/rootfs/`，GNOME 程序暂存在
`build/boards/w202ds/desktop-gnome/rootfs/`。共享构建不需要 KDE/GNOME 的源码或 SDK。
硬件工具在各组件自己的固定输出目录生成。
打包验证整合程序为 ARM64 ELF；硬件组件通过各自 artifacts.json 校验产物存在。
缺少产物时失败，不回退到 Python。不会自动下载工具链或安装到运行设备。

运行时需要 systemd/busctl、libsystemd、pkexec、NetworkManager、BlueZ 和对应板级
工具及固件。独立 GNSS 入口另需 kdialog。GNSS 不默认开启；摄像头手电筒仅在选中
匹配模块时打包。Polkit、服务启用、霍尔编码和去抖仍由 REIMUKS rootfs 策略定义。

离线测试：

```sh
W202_NATIVE_CC=cc python3 -B -m unittest discover -s tests -p test_desktop_controls.py
python3 -B -m unittest discover -s tests -p test_userspace.py
```

测试包含假接口、充电状态对照、GNSS PTY 握手与信号退出释放、电源所有权、
协议校验、霍尔去抖、亮度边界、NV 校验、JSON 与超时。
它们不能代替充电、无线切换、实际输入事件及 KDE 合盖/唤醒的硬件验收。

## USB 策略

共享 C 程序 `w202-usb-settings` 保存 OTG/Device/Host 预选、Device 开关和 ACM/NCM
组合。`w202-device-controls usb-auto-1-3` 通过 Polkit 调用它；末两项分别为启用标志
和功能位掩码（1=ACM、2=NCM、3=两者）。只接受固定模式和值。
设置写入 `/var/lib/reimuks/usb.conf`，先保存意图，再调用硬件接口；应用失败时仍保留
意图，界面显示失败，实际角色与绑定读回放在 `usb.actual`，不冒充已成功切换。
Host 保留 Device 预选，但暂不绑定。UDC 返回后的 gadget 服务由 drop-in 调用
`reapply` 恢复保存的功能，不覆盖回默认 ACM+NCM。未保存设置时沿用初始化默认。
这套覆盖由 Server、KDE 和 GNOME 共享；initramfs 保留独立的恢复配置。

USB 界面在 KDE 托盘展开页，独立于充电项目。勾选仅编辑，点击保存才写入；
轮询不覆盖未提交编辑。至少预选一种功能；Device 关闭时仍保存预选。
应用可能断开 USB 网络或串口，界面有明确提示。

离线 USB 测试：`W202_NATIVE_CC=cc python3 -B -m unittest discover -s tests -p test_usb_controls.py`。
当前仅完成离线接口、组合、所有权和失败状态测试，未做真实角色/供电/枚举验收。

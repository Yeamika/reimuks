# W202DS rootfs 策略

职责边界见 [分层契约](../../../ARCHITECTURE.md)。rootfs 不指定内核，模块与身份检查由部署阶段负责。

板级硬件适配来自 `kernel/Devices/<设备>/userspace/`：初始化程序、基础 systemd 单元、设备方向等物理描述和标准接口留在 Linux 工程。REIMUKS 在本目录选择组件、定义输入含义和系统动作，并覆盖组件默认文件。

[`policy.json`](policy.json) 定义组件及服务启用规则。打包顺序固定为：安装所选板级组件 → 叠加 `common/` → 图形桌面选择 `desktop-common/` → 叠加对应 profile → 创建/移除服务启用链接。REIMUKS 的同路径文件优先，构建只操作离线目标树。

| 路径 | 职责 |
| --- | --- |
| `common/` | 主路自动充电、霍尔到 `SW_LID` 的映射、USB 地址、ACM getty 依赖、远程服务就绪辅助。 |
| `profiles/desktop/server/` | 全屏控制台登录、普通日志限制、保持合盖运行、networkd。 |
| `desktop-common/` | KDE/GNOME 共用的 GNSS、手电筒、蓝牙、合盖桥和权限；C 控制程序在打包时安装。 |
| `profiles/desktop/gnome/` | GDM Wayland 配置；不安装 KWin 会话脚本。 |
| `profiles/desktop/kde/` | KWin 虚拟键盘联动资源；合盖动作由 KDE/PowerDevil 配置决定，网络由桌面管理。 |
| `optional/wcn/` | 可选的 WCN 故障恢复与休眠钩子，依赖已安装并验证的 WCN 运行服务，不默认打包。 |

`desktop/server` 和 `desktop/kde` 共用 desktop 内核。顶层 `server` 尚未实现，不使用这些配置。内部构建参数暂用 `server`、`kde`，对应上面两个完整 profile，不表示顶层 server。

霍尔模块默认只给出磁感应状态；`common/etc/modprobe.d/w202-hall.conf` 显式选 `switch_code=0`，才将有效磁感应解释为 `SW_LID=1`。模块仍由 udev 按设备匹配加载，不另加强制加载服务。部署时须检查所选霍尔模块是否支持 `switch_code`；独立 rootfs 打包不检查内核二进制。desktop/server 通过 logind 配置忽略合盖电源动作；desktop/kde 不继承此覆盖，由桌面选动作。读取 `LidClosed` 不会更改策略。

两种 profile 均安装选定组件的用户态服务；硬件可用性仍取决于部署时安装的匹配模块。KDE 不安装 Server 的全屏控制台/合盖覆盖，并移除本工程的 networkd 启用链接。可选 KDE 网络集成见 [`../desktop/kde/`](../desktop/kde/README.md)，可选控制台策略工具见 [`../userspace/display/`](../userspace/display/README.md)。

SSH 使用发行版自身的启动条件，不依赖显示、键盘、USB gadget 或板级就绪服务。打包会清理历史根树中将 SSH 绑定到 `w202-ready.service` 的旧 drop-in，保留主机密钥生成配置；USB 调试失败不会连带阻止 SSH 启动。

两种 desktop profile 均安装并启用选定组件的板级 `w202-charging.service`，通过 `common/etc/default/w202-charging` 选择主路 `auto`。从路保持停充，PPS 协商、普通充电回退及温度/故障保护仍由驱动管理。已有根树上的旧 `w202-power.service` 先完成初始化，再应用此策略；无需更换内核或 UEFI。该设置表示请求自动充电，不代表当前连接已经协商成功或达到固定功率。

`usr/`、`etc/` 都是目标系统路径。打包不启动服务，不访问构建机的 USB、声卡或显示设备。每个 profile 使用独立 rootfs；覆盖不是把已打包的 Server 根树就地转换成 KDE 的迁移器。

启动充电服务时，通过 `30-auto-power.conf` 选择 PPS 优先的自动快充模式；不支持 PPS 时保留固定档回退。功率受板级电流、电压、温度和电源能力限制，不强制拉满充电器额定功率。启动后手动模式及充电分离不被周期性覆盖。当前驱动在充电分离时退出 PPS，保留固定 PD 外电供电。

以太网、STA 和 AP 的连接档案由用户在网络管理界面配置；板级集成不反复写入默认连接。

可选 `w202-screen` 控制台策略默认空闲 300 秒息屏；其配置为 `W202_SCREEN_IDLE_SECONDS=300`。运行该策略时不要再叠加 VT 自动 blank 定时器。图形调试可临时使用 `w202-screen --timeout 0`，结束后恢复 `--timeout 300`。KDE 通过 PowerDevil 设置 300 秒息屏，与此控制台策略分开。

图形桌面通过 `policy.json` 的 `desktop_common` 显式复用共享层。
先按 [`../desktop/common/`](../desktop/common/README.md) 构建 ARM64 C 控制程序，
缺失或错误架构时打包提前失败。KDE 的合盖唤醒补偿仍只在 KDE 会话运行；
GNOME 使用自己的电源管理。此处不提供已有根树之间的 DE 就地切换。

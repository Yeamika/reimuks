# 分层职责与产物契约

## 四层职责

KDE 已有实现是抽象基准。硬件层和板级接口层各维护一份产物，所有 DE 复用；
选择 GNOME、KDE 或后续桌面时，只增加对应 DE 和少量会话、界面适配。

| 层 | 维护位置 | 职责与产物 |
| --- | --- | --- |
| 1. 内核与硬件 | 板级 Linux 工程的 `Devices/<设备>/`、`userspace/` | 驱动、设备树、固件、物理方向、硬件初始化与恢复、标准 Linux 接口和基础服务；进入该板的硬件包 |
| 2. 板级接口 | `devices/<板型>/overlays/<板级硬件层>/` | 统一 C 控制入口、权限、状态读回、服务所有权和标准桌面服务桥接；供 Server 与各 DE 复用 |
| 3. 标准 DE | `distributions/` 的桌面包映射 | 发行版的标准 GNOME、KDE 等桌面与登录会话；产物 `reimuks-de-<桌面>` |
| 4. DE 专属适配 | `devices/<板型>/overlays/<板型>-<桌面>-hardwareuipack/` | 调用共享接口的控件、会话开关、旋转和键盘策略、监控插件；只包含该桌面的适配 |

板级 profile 在 `config/boards/<板型>/` 选择 kernel 和 overlay 清单；每个 overlay
以 `layer.json` 声明文件、服务、校验规则和构建产物。普通 rootfs 不再在板目录
维护另一套并行的 `common/`、`desktop-common/`、`profiles/` 树。

第一层将设备拉起并提供标准接口，第二层为上层统一包装。AT 就绪排序跟随基带
初始化实现；Wi-Fi、蜂窝、蓝牙、GNSS、USB、充电和手电筒控制复用同一后端。
IMU、加速度计、输入、音频和视频继续使用 IIO/SensorProxy、input/logind、
ALSA/PipeWire、DRM/V4L2/VA-API 等接口。GNSS 默认关闭，私有 NV 单独提供。

公共构建不编译任何具体 DE 程序。KDE 的 Plasma/KWin/Qt 代码和 GNOME 的
GSettings 适配分别构建，安装任一个不要求另一个的 SDK 或编译输出。
切换桌面只改变后两层，前两层的包和固件应逐字节相同。

发行版基础系统、用户选择和启动产物另有各自职责：

| 部分 | 维护位置与职责 |
| --- | --- |
| 发行版基础 | `distributions/<发行版>/`：软件源、架构、核心软件包和版本约束 |
| 使用场景 | `profiles/`：desktop/server、desktop/kde 等目标和继承关系 |
| 用户配置 | `overlays/user/`：Passkey 提供登录和网络，KDE 主题提供壁纸和任务栏位置 |
| 启动工程 | boot、edk2-ums9620、pj4edk2：LK/UEFI、启动菜单及 EFI 交接 |
| 安装部署 | 组合产物、检查内核与模块 ABI、安装模块、更新 ESP 和根分区 |

## 四类产物

- **UEFI 固件**：由 boot 工程生成，包含板级固件封装；不依赖 rootfs 的发行版。
- **EFI / ESP 文件**：EFI 程序及明确指定的启动材料；启动项引用与安装由部署阶段管理。
- **initramfs**：需要指定内核及匹配模块，负责早期硬件和根分区切换。
- **rootfs**：发行版软件包、桌面、板级用户态适配和系统策略；不读取内核清单，不包含 `Image`、`.ko` 或内核身份标记。

内核 Image、匹配模块及其身份清单为独立配套产物。部署阶段安装模块、运行 depmod，
并按启动协议补齐 initramfs 所需的根分区身份标记。独立 rootfs 不能直接当成已配置好的
可启动整机镜像；部署检查仍须验证实际内核与模块 ABI。

## 默认值和覆盖

GPU 支持哪些频率、电压与热保护，由 GPU 驱动负责。
W202DS 选择 845 MHz 配置的 modprobe 文件归入 GPU 的 `userspace/rootfs/`；
REIMUKS 安装该组件，不在 KDE 配置中重复定义频率。

物理安装方向属于板级。桌面只在逻辑坐标中选择用户旋转角度；触控保持同一坐标契约。
霍尔提供磁感应状态，REIMUKS 将其解释为合盖，桌面决定合盖动作。

板级服务提供 USB、充电、GNSS 等硬件接口；桌面控件只调用接口。
用户保存的网络连接、手动开关和桌面偏好优先，开机服务不得循环重写用户选择。
壁纸属于桌面资源与用户选择，不随内核更新。账户和真实密码只从本地账户配置注入。

## 当前边界与后续工作

rootfs 构建入口、打包与校验已解除强制内核输入；板级组件的用户态文件可以离线安装。
模块 ABI、驱动参数支持检查属于内核配套包/部署检查，不属于独立 rootfs 的发行版校验。
完整安装流程还需对独立配套产物执行上述部署检查，不能仅凭 rootfs 打包成功就刷盘。

## 可独立组合的软件包层

APT 分包由发行版和设备目录维护：

1. 通用基础 rootfs：标准命令行用户空间，不携带板级或 DE 集成包。
2. `reimuks-w202ds-board`：板级基础服务、硬件运行库与接口，Server 也可使用。
3. `reimuks-de-common`：发行版通用图形、音频、输入、传感器及系统服务依赖。
4. `reimuks-w202ds-de-compat`：W202DS 对上述通用桌面接口的接入，不依赖具体 DE。
5. `reimuks-de-kde` / `reimuks-de-gnome`：发行版标准 DE 及 Wayland 登录。
6. `reimuks-w202ds-kde` / `reimuks-w202ds-gnome`：具体桌面控件、会话及板级行为适配。
7. 可选 apps 包、独立私有 user overlay。

`reimuks-w202ds-server` 独立提供控制台登录、networkd 和合盖策略，不作为图形桌面的父包。
通用 DE 兼容包依赖板级基础与发行版桌面接口；具体桌面适配同时依赖兼容包和对应标准 DE。
所有软件层使用 dpkg/APT 记录依赖与文件归属。源码模板先生成独立 `.deb`，rootfs 打包通过目标 dpkg 安装，不再直接覆盖发行版文件。
上游 ModemManager 的通用 udev、D-Bus、PolicyKit 文件由发行版包拥有；板级包只提供私有扩展。

`pack.py rootfs --profile server --base-only` 生成基础归档。
`pack.py rootfs --profile kde --from-base` 从已配置的标准基础包树暂存，离线安装桌面依赖和板级包，完成启动前检查后生成完整 rootfs。普通 KDE/GNOME 完整构建也使用相同的集成包。
软件包拆分不改变内核、initramfs、EFI/ESP 的职责；本流程不刷机。

## 构建存储分层

发行版配置和构建独立于板型：`scripts/distribution.py` 不加载板型工程，
产出共享基础系统。默认共享根目录为 `build/`；
`distributions/<id>/<arch>/` 下维护通用包树、缓存、DE、App、SDK 和基础归档。
板型额外软件源和包依赖只在板级组合时使用，其选择清单位于共享缓存的 `boards/<board>/`。

`--build-root` 或 `REIMUKS_BUILD_ROOT` 选择板级工作树和交付目录，
默认 `build/boards/<board>/`。组合时复制共享发行版包树，在板级工作树中离线安装
板级包和必要依赖，生成完整 rootfs；不把板级覆盖写回发行版层。
共享发行版包树使用构建锁串行访问。

## 板级完整性与叠加关系

板级机制和固件先独立构建、暂存并通过完整性检查，再开始整机 rootfs 组合。
发行版提供标准用户空间根树；板级公共包、通用桌面接口、具体 DE、App 和私有
用户配置分别管理，按依赖叠加。更换发行版或 DE 不改变板级硬件输入清单。
共享发行版树保持板型无关，组合过程也不将板级内容写回该树。

触控、WCN（Wi-Fi、蓝牙及 GNSS 参数）、音频和基带公共固件属于板级包，
不能由 GNOME、KDE 或 App 包补齐。输入缺失或哈希错误必须在读取发行版树前
失败；所有层安装完成后，再在目标用户态核对板级固件收据，防止覆盖或遗漏。
设备私有 NV、账户及网络连接使用独立私有 overlay，不能进入公共板级包。

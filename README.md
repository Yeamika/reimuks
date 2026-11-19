# REIMUKS

REIMUKS 是面向多个设备的 Linux 发行版组装项目，提供发行版 rootfs 打包、板型系统集成与独立启动产物的构建调度。

内核、模块与硬件用户态由设备的 Linux 工程实现，统一入口调用其构建与导出接口。发行版软件源、软件包选择、系统策略和桌面集成由本仓库维护。私有固件与设备状态由部署者提供；硬件适配的 Vulkan ICD、ModemManager 插件作为独立组件构建，不从旧系统复制可执行文件。

## 统一选择构建目标

```sh
python3 reimuks.py --list-boards
python3 reimuks.py --list-distributions
# 工具链只安装在 build/ 下；需要宿主已有 rustup、APT、dpkg-deb。
python3 scripts/prepare_boot_tools.py
. build/boot-tools/env.sh
python3 reimuks.py --board w202ds --target uefi efi
python3 reimuks.py --board w202ds --target kernel userspace kernel-runtime \
  --profile desktop/kde
python3 reimuks.py --board w202ds --target initramfs
python3 reimuks.py --board w202ds --distribution debian/trixie \
  --target rootfs --profile desktop/server desktop/kde
```

`--distribution` 选择 rootfs 的发行版，默认 `debian/trixie`；`--profile`
选择 rootfs 或 userspace 的使用场景，默认 `desktop/server`。内核配置使用
独立的 `--kernel-profile`；UEFI、EFI 和 initramfs 保持板级公共产物。
`--plan` 显示所选目标和输入，不执行构建。配置位于
[`distributions/`](distributions/README.md)，包含软件源、suite、架构、包映射和
验收要求；profile 保留用途与继承关系。当前仅提供 Debian trixie ARM64 配置，
其他发行版/包管理后端尚未实现。底层 build/pack/verify 脚本也接受同名参数。

`--target` 可组合 `kernel userspace kernel-runtime uefi efi initramfs rootfs esp`。
`kernel` 调用 Linux 构建并导出配套运行文件；`userspace` 构建硬件用户态及板型集成；
`kernel-runtime` 将 Image、配置、匹配模块和身份清单封装成独立安装包。
SDK 和 producer 配置见 [板型构建说明](devices/w202ds/README.md)。
`uefi`、`efi` 委托板型 boot 工程构建固件和 ESP 应用；LK/U-Boot 的生成、
分区封装及内部布局校验均由 boot 工程负责。REIMUKS 按其清单收集产物，
只检查文件长度与 SHA-256，不解释分区内容。
ESP 的 DebianServer/DebianKde 分别用于 desktop/server 与 desktop/kde。
旧 ESP 路径名称保留兼容性，不代表存在 Server 专用内核。
boot 文件固定输出到 `build/boards/w202ds/artifacts/boot/`，也可用 `--output` 指定唯一交付目录。
重复构建更新同一位置；独立构建 UEFI 或 EFI 时保留另一阶段的文件与来源清单。
编译工作目录固定为 `<build-root>/boot/work/`，成功后删除；失败时保留现场供排查，下一次构建重新使用该位置。
构建不刷机，也不自动提供 Linux DTB 或根分区。分区镜像经过离线结构与模拟测试，
仍需真机验证。

boot 工程管理自己的构建输入。`--boot-inputs /path/to/inputs.json` 作为不透明配置
直接转交 boot 工程；其格式、镜像兼容性、产物布局及板级验证方法见
[`devices/w202ds/boot/README.md`](devices/w202ds/boot/README.md)。

rootfs 结构为 `desktop/{server,kde,gnome,niri}` 和顶层 `server`。
`desktop/server`、`desktop/kde` 已有构建配置，`desktop/gnome` 为新增实验配置（尚未实机验证）；Niri 占位；
顶层 `server` 因 W202DS 没有 Server 内核而占位，选择后在构建前报错。
详情见 [profile 定义](profiles/README.md)。底层脚本及缓存中的 `server`、`kde`
是兼容现有构建目录的内部简称，分别对应上述两个 desktop 配置。

分层职责与产物契约见 [ARCHITECTURE.md](ARCHITECTURE.md)。
initramfs 消费已导入的内核与模块；rootfs 不指定内核，也不包含 Image 或 `.ko`。
两者均不编译内核或板级用户态程序。
发行版基础包树只读取发行版/DE 配置，板级非通用依赖在组合阶段从认证缓存离线安装。
rootfs 还从 `devices/w202ds/kernel/Devices/<设备>/userspace/` 读取音频、显示和 USB 基础服务模板，
再应用 [`devices/w202ds/rootfs/`](devices/w202ds/rootfs/README.md) 中的输入含义、网络、登录和桌面策略。
组件先安装，REIMUKS 的 common 和对应 desktop profile 依次覆盖；组件选择及服务启用在板型 `rootfs/policy.json` 定义。
需初始化板型 kernel 子模块；组件实现只在 kernel 项目维护一份。
initramfs 从独立的最小工具包树获取 BusyBox 和 blkid，不构建或读取 Server rootfs。已配置 rootfs 会直接重新打包；需要更新软件包时先显式执行下方
底层 fetch/configure 流程，避免无意改动已设置的账号。

新增板子时放入 `devices/<board>/board.json`、`kernel`、`boot`；
`boot_builder` 指向板级 boot 项目自己的构建适配器，REIMUKS 负责选择、调度、
验证与收集输出。工具链按板级适配器要求提供，不把 W202DS 硬件代码搬入发行版。
当前 W202DS 提供构建实现；[Polaris](devices/polaris/README.md) 已登记目录骨架，
Linux 采用上游 SDM845 7.1-rc1，boot 与 Linux 分别取 Polaris-linux 的两个分支。
Polaris 尚未完成配置、用户态与启动移植，所有目标会在下载或写入构建目录前明确拒绝，
不会使用 W202DS 的默认输入代替。`supported_targets` 字段用于逐项启用新板型目标；
未设置此字段的现有板型保持原行为。

## 从独立层包组装目标

`--target compose` 读取目标 JSON，按选定顺序把现有内核、发行版、DE 及可选层封装成目标归档，并逐文件校验 SHA-256。各层自己的脚本独立出包。W202DS 的目标配置在 `devices/w202ds/targets/`。

## 构建目录

REIMUKS 默认将板级工作树和产物放入 `build/boards/<board>/`。
`reimuks.py --build-root <输出目录>` 可为本次调用选择其他位置，低层脚本通过
`REIMUKS_BUILD_ROOT` 使用同一目录；该选择不会移动共享软件包和缓存。
发行版层位于 `build/distributions/<发行版>/<版本>/<架构>/`：
`rootfs/<profile>/` 保存通用软件包树，`artifacts/` 保存基础发行版归档，
`cache/` 保存通用 APT 缓存，`apps/`、`de/` 和 `sdk/` 保存可复用附加包与 SDK。
板级 APT 依赖独立保存在 `cache/boards/<board>/`，不进入共享的软件包树。
板级组合工作树位于 `<build-root>/rootfs/<profile>/work/`；最终完整 rootfs 位于
`<build-root>/artifacts/`。硬件服务、板型 DE 兼容包和用户配置在组合阶段加入。
通用 App 包位于同一发行版目录的 `apps/<profile>/`，通用 DE 包位于 `de/<profile>/`；
工具链在 `build/boot-tools/`、`build/compiler/` 和 `build/tools/`，目标 SDK 在发行版目录的 `sdk/`。
共享数据根目录可用 `REIMUKS_SHARED_BUILD_ROOT` 单独选择，默认仍为仓库 `build/`。
这些目录都不安装到宿主系统。

```sh
# 不要求板型或板型源码，构建共享基础发行版
python3 scripts/distribution.py --distribution debian/trixie --plan
python3 scripts/distribution.py --distribution debian/trixie
# 选择板型，组合完整系统
python3 reimuks.py --board w202ds --target rootfs --profile desktop/kde \
  --build-root <项目构建目录> --plan
```

`--plan` 显示解析后的共享目录、板级目录和启动产物路径，不创建输出。
如需独立指定 boot 工作树，可设置 `REIMUKS_BOOT_ROOT`；其中使用固定的
`work/`、`artifacts/` 和 `source-cache/`。未设置时优先使用板型 boot 工程的
`output` 链接，否则使用板级构建目录；`--output` 仍只覆盖 boot 交付目录。
Linux 工程的内核、模块及硬件用户态输出由其自身管理，统一位于该工程的 `output/`。
每个目标只保留一份固定输出，不自动生成带日期或版本后缀的副本。
需要留存构建对照时，构建完成后复制到独立工作区再改名。

- `distributions/debian/trixie.json`：Debian 软件源、包清单、版本身份和验收要求。
- `profiles/desktop/server.json`：使用 desktop 内核的命令行系统，`multi-user.target`。
- `profiles/desktop/kde.json`：继承 desktop/server，增加 Plasma、SDDM、Konsole、Dolphin、NetworkManager 和 PipeWire，`graphical.target`。
- `initramfs/init`：等待根分区、验证内核身份、挂载 ext4、切换到 systemd。
- `devices/w202ds/rootfs/`：板型网络与 profile 登录策略，组件基础服务来自 kernel 项目的 `Devices/<设备>/userspace/`。
- `devices/w202ds/initramfs/`：板型早期启动钩子，USB 实现复用 kernel 项目的 `Devices/usb3/userspace/`。
- `devices/w202ds/desktop/kde/`：可选桌面网络集成；通用硬件适配仍留在 kernel 项目。
- `scripts/build.py`：隔离 APT 状态，下载、解包及配置 ARM64 软件包。
- `scripts/pack.py`：导入内核、打包 initramfs 和 rootfs。
- `scripts/verify.py`：检查压缩格式、架构、包状态、所有权、启动目标和模块数量。

依赖宿主 Python 3.11+、APT、dpkg-deb、curl、liblz4；x86_64 宿主使用项目内下载的 QEMU 和 PRoot。PRoot 需要容器允许 ptrace；不需要 root、mount 或 user namespace。包配置在 PRoot + QEMU 内执行，fakeroot 保存包所有权后交给目标 tar 导出。

下载使用发行版配置的软件源。APT 状态、缓存、源配置及钩子与宿主隔离；依赖版本和下载哈希记录在产物 manifest 中。在线镜像会更新，本实现记录输入，尚不保证跨日期字节一致的重建。

## 操作顺序

在项目根目录运行，以下 `python3` 可替换为本机 Python 绝对路径：

```sh
python3 scripts/build.py tools
python3 scripts/build.py fetch --profile server
python3 scripts/build.py assemble --profile server
python3 scripts/build.py configure --profile server
python3 scripts/build.py fetch --profile kde
python3 scripts/build.py assemble --profile kde
python3 scripts/build.py configure --profile kde
```

内核交接需要四项：未压缩 ARM64 `Image`、以 kernel release 命名的完整模块目录、实际构建 `.config`、身份 JSON。JSON 至少包含 `release`、`image_sha256`、`config_sha256`、`standard_modules` 和 `board_modules`。导入检查 Image/config 哈希、模块数量和 vermagic，拒绝混用不同 release 或 vermagic；同 release 的 ABI 身份仍需内核供应方保证，文件哈希用于追溯。

```sh
python3 scripts/pack.py import-kernel \
  --image /path/to/Image \
  --modules /path/to/lib/modules/KERNEL_RELEASE \
  --config /path/to/config \
  --identity /path/to/identity.json
python3 scripts/pack.py initramfs
python3 scripts/pack.py rootfs --profile server
python3 scripts/pack.py rootfs --profile kde
python3 scripts/verify.py
```

`assemble` 和内核导入拒绝覆盖已有目录，防止把失败的旧状态误当作干净构建。配置日志必须成功，`dpkg --audit` 必须为空，才能打包 rootfs。构建失败时保留日志与现场，不将仅解包的目录标为完成。

共享层位于 `overlays/`，用户层的打包脚本位于 `overlays/user/`。

## 启动交接

initramfs 使用 LinuxBoot 所需的 **legacy LZ4（魔数 `0x184c2102`）+ newc CPIO**，不是 gzip 或现代 LZ4 frame。REIMUKS 使用标准 `/init` 入口，不包含 `/w202diag` 诊断别名；内核导入会拒绝启用 `W202DS_DIAG_RECOVERY` 或强制 `rdinit=/w202diag` 的旧诊断配置。W202DS 应使用当前 Linux 工程的 `desktop` profile，不能复用旧 `debug` Image。

根分区选择优先读取 DT `/chosen/w202,root-partuuid`，否则读取内核命令行 `root=PARTUUID=…`、`root=UUID=…`、`root=LABEL=…` 或 `root=/dev/…`，等待最多 60 秒。当前没有内置真实分区 ID，避免误选设备分区。DT 消费逻辑是本项目新增；本地 LinuxBoot 已实现相应属性写入，详见 [DTB 约定](boot/doces/efi_dtbchosen.md)。`CONFIG_CMDLINE_FORCE=y` 的内核可能忽略启动器传入的 `root=`，应使用 DT 属性或重编译内核配置。

rootfs 默认用 ext4。部署阶段安装独立内核模块包及身份标记；initramfs 核对已安装的 kernel release 和 Image 身份后切换到 systemd。内核需内建存储和 ext4 驱动。板级 `initramfs_early_modules` 生成 `etc/early-modules`；W202DS 提前加载匹配内核的 `w202_r6p0` DRM 模块，保留延迟 modeset 行为，早期日志由内建启动显示组件负责。其他模块由 rootfs 的 udev 按 modalias 加载。单独打包可用 `scripts/pack.py initramfs --early-module w202_r6p0 --output <输出目录>`；缺少匹配模块时构建失败。重复打包重建固定的 `root/` 工作树并更新归档，不保留旧工作树副本。

desktop/server 在 `multi-user.target` 与原生显示就绪后切换全屏登录，
不再等待 Wi-Fi 或远程执行器。切换后仅错误及更严重的内核消息显示到控制台；
普通信息和警告仍保留在 dmesg/journal。匹配模块集包含音频驱动时，rootfs
启用 `w202-audio.service`，等待音频时钟和 ALSA 设备就绪；需提前将经过校验的
`w202ds/agdsp.bin`、`w202ds/vbc-speaker.bin`、`aw88166_acf.bin` 放入 rootfs 的
`usr/lib/firmware/`。固件准备方法见内核工程的 `Devices/audio/firmware/prepare.py`。

USB 调试传输由 initramfs 和 rootfs 复用同一份板级脚本配置为 ACM+NCM gadget，
initramfs 中不再保存第二份硬件实现。早期启动动作在 `devices/w202ds/initramfs/` 定义。
ACM 设备为
`ttyGS0`，rootfs 会启用 `serial-getty@ttyGS0.service`；NCM 网卡为 `usb0`，
设备端地址 `192.168.77.2/24`，由 `/etc/default/w202-usb-gadget` 和
`/etc/systemd/network/80-w202-usb.network` 保持一致配置。
rootfs 会在切换完成后再次确保 gadget 和地址存在。当前只提供 USB 串口提示和网络接口，
发行版包提供 SSH，服务不依赖硬件就绪检查；不附带 rexed。root 与 `reimuks`
账号默认锁定，可由本地账号配置设置初始密码。

## 产物与部署前事项

默认 Debian trixie 的板级输出在 `<build-root>/artifacts/`；其他发行版使用
`<build-root>/distributions/<发行版>/<版本>/artifacts/`。下文示例使用默认 W202DS 目录：

- `initramfs-arm64.cpio.lz4`
- `desktop-server-arm64-rootfs.tar.gz`
- `desktop-kde-arm64-rootfs.tar.gz`
- `SHA256SUMS`、`verification.json`、各自 manifest 和软件包版本清单。

rootfs 不带 Image、配置或模块。部署时将 rootfs 与匹配的 `kernel-runtime-arm64.tar.gz`
组合安装；`scripts/install-rootfs.sh` 校验两份归档、运行文件哈希及模块依赖。
归档解包须保留数字 UID/GID、权限、ACL 和扩展属性；分区创建、格式化、
私有固件安装和 ESP 更新由独立部署流程负责。

desktop/server 与 desktop/kde 共用 `config/accounts.json` 的账号策略，账号为 `root` 和 `reimuks`，仓库默认锁定密码。可将 `config/accounts.example.json` 复制为 Git 忽略的 `config/accounts.local.json`，分别设置 `password`（明文初始密码）、`password_hash`（crypt 哈希）、`password_env`（环境变量名）或 `locked: true`，每个账号只能选择一种。本地配置建议权限为 `0600`；真实密码不要放进被跟踪的配置文件。

基础 rootfs 默认使用仓库的锁定账号策略，不自动读取本地账号文件；打包时将 root/reimuks 重置为不含密码哈希的锁定状态，并移除构建时生成的 SSH 主机密钥。主机密钥由部署后的 SSH 前置服务生成。私有账号、网络和蓝牙配置通过独立用户 overlay 合并，基础归档不会被修改。需要定制密码时，将对应目标系统的 shadow 配置放入私有 overlay，保持严格权限；不要把私有配置提交到仓库。

```sh
python3 scripts/user_overlay.py pack --source <私有配置目录> --output build/boards/w202ds/artifacts/user-overlay.tar.gz
python3 scripts/user_overlay.py merge \
  --base build/boards/w202ds/artifacts/desktop-kde-arm64-rootfs.tar.gz \
  --overlay build/boards/w202ds/artifacts/user-overlay.tar.gz \
  --output build/boards/w202ds/artifacts/desktop-kde-arm64-deployment.tar.gz
```

私有目录采用目标系统相对路径，如 `etc/NetworkManager/system-connections/`、`var/lib/bluetooth/`、`home/reimuks/.ssh/`。overlay 和部署归档权限为 0600。合并保留基础目录权限和已有系统文件的 uid/gid，用户家目录按基础 passwd 中的 uid/gid 处理，拒绝穿越符号链接路径。合并输出是独立部署包，应在安装前重新检查用户配置，基础包的验证结果不替代部署包的配置验证。

每次 rootfs 打包都会重建固定的 `work/package-rootfs` 暂存目录，从配置完成的包树复制，再安装当前板级文件；不把板级文件或 overlay 写回原树。需要额外暂存空间，支持 reflink 的文件系统会复用数据块。旧版曾原地打包的树必须移除 rootfs/work 后，从保留的 APT 缓存重新 assemble、configure；不能仅补一个标记文件继续打包。公开模板移除组/其他用户写权限，保留包目录已有权限与归属；目标命令固定 HOME、隔离 XDG 环境，构建使用 umask 022。

基础包不为 `reimuks` 自动授予 sudo 权限。

构建工具固定使用 [PRoot v5.5.0](https://github.com/proot-me/proot/releases/tag/v5.5.0) 的上游静态二进制，并校验发布资产的 SHA-256；ARM64 用户态模拟器及包元数据来自 Debian 的签名仓库。

## W202DS 工程入口

设备入口保留 `devices/` 分组，W202DS 放在 `devices/w202ds/`：

```text
devices/w202ds/
├── kernel -> ../../../w202ds-linux/6.18.35
└── boot   -> ../../../w202ds-boot
```

Git 中两项都是固定提交的 submodule/gitlink，远程同为 `Yeamika/w202ds-linux`，分别对应 `6.18.35` 与 `boot` 分支。共享 PocketJS 组件使用 `Yeamika/pj4edk2` 的对应分支。Polaris 的 kernel 和 boot 分别引用 `Yeamika/Polaris-linux` 的 `7.1-rc1` 与 `boot` 分支；这些依赖必须先发布，再更新本仓库的固定提交。

```sh
git submodule sync --recursive
git submodule update --init
# 按目标初始化其下的依赖；例如 W202DS：
git -C devices/w202ds/kernel submodule update --init
git -C devices/w202ds/boot submodule update --init
```

子模块按记录的提交检出，不使用 `--remote` 自动追踪最新分支。开发环境可用相对符号链接连接独立检出的同一提交；提交时仍须保留 gitlink，不能把链接目标或工作目录路径写入仓库。工具链、原厂固件和私有配置仍是单独的构建输入。

启动包组装入口为 `scripts/boot_bundle.py`，生成独立的内核、initramfs、DTB、校验元数据和 `linuxboot.conf`；LinuxBoot EFI 从 ESP 配置选择文件、根分区 PARTUUID 和启动参数。调整启动目标不需要重新生成 initramfs。接口见 [启动交接说明](boot/doces/efi_dtbchosen.md)。

准备完整 ESP 目录树后，可生成 FAT32 分区镜像：

```sh
python3 reimuks.py --board w202ds --target esp \
  --esp-tree <完整ESP目录树> --esp-size-mib 512 \
  --esp-tools <dosfstools和mtools的bin目录>
```

固定输出为 `build/boards/w202ds/artifacts/esp.img` 及其文件哈希清单；生成时检查文件系统并逐文件读回校验。输入树必须包含需要保留的其他系统、菜单和设置文件；此目标不读取或修改 GPT，也不刷写设备。宿主工具已在 PATH 时可省略 `--esp-tools`。

### Wayland 桌面策略

rootfs 打包会在板级文件和用户覆盖全部安装后，通过 PRoot＋QEMU 执行目标
ARM64 登录程序、systemd 和桌面程序，检查板级 shell 语法、辅助程序引用及
systemd 服务依赖；任一检查失败均停止发布归档。检查结果写入工作目录的
`startup-preflight.json`，并包含在产物 manifest 中。离线安装脚本还会在
目标机器上通过真正的 chroot 重跑同一套检查。也可单独检查现有树：

```sh
python3 scripts/startup_preflight.py --rootfs <rootfs目录> --profile kde
```

这项检查验证用户态依赖，不能模拟完整 PID 1 启动或验证板上 DRM、USB、
充电等硬件；实机冷启动仍是独立验收步骤。

KDE 使用 Wayland 登录器和 Plasma Wayland，不提供 X11 桌面会话；保留标准
Plasma 会话所需的 Xwayland 兼容入口，以及 EGL、GLES 和 OpenGL 硬件渲染包。
不主动选择基于 GLX 的 mesa-utils。
Debian trixie 的 KWin、GNOME Session 仍硬依赖 xwayland，SDDM 硬依赖 X server，
因此发行版二进制包及其 X11 库仍可能出现在镜像中；Xwayland 仅服务兼容客户端，
不会把 KWin 或桌面切换成 X11 会话。
若要彻底删除这些包或去掉 Mesa 的 X11 编译支持，需要单独重建相关发行版包；
当前不修改包依赖、不强制卸载系统库。GNOME 启用 Wayland，但其 XWayland
支持尚未禁用，不将 GNOME 标为纯 Wayland 验收通过。
以上是新构建 rootfs 的策略，尚未实机验证 Wayland 登录器。

## 当前集成与重建验证

发行版附加包为 Chrome、VS Code、btop、fastfetch、Vim 和 lazygit，适用于 KDE/GNOME；Server 保持核心包。图形公共依赖包含 EGL/GLES/OpenGL、Vulkan 和 VA-API。浏览器启动策略见 `scripts/acceleration.py`，硬件驱动由板级 Linux 工程提供。

rootfs、内核运行包和 ESP 分别构建、分别校验；rootfs 不包含内核或模块。桌面硬件控件、左侧面板初始布局和板级服务均通过构建流程安装，手电筒控件的显示仍取决于硬件接口是否可用。构建测试通过不等于基带注册、桌面交互或休眠已完成设备验收。

跨主机重建须使用相同 Git 提交及子模块、工具链、APT 包版本、源码锁定清单和配置。先比较各文件的长度与 SHA-256，再比较包版本和归档内容；含时间戳、账户初始化状态及设备私有输入的 rootfs 压缩包不能仅凭外层哈希判断代码差异。私有配置和设备固件不提交到仓库。

附加应用不默认加入基础 rootfs；可通过 `scripts/addons.py` 单独打包。应用软件源与 Chrome 启动策略随附加包提供，桌面基础层仍保留通用加速 API。APT 缓存可保留其他软件组的包，但 assemble 只安装当前 fetch 清单选定且已校验的文件。

rootfs 的 tar 流仍由目标端 fakeroot 生成以保留包元数据，压缩由宿主机的 `gzip` 执行；宿主机需提供 gzip。只有归档与压缩进程均成功才发布最终文件。


## 可组合的桌面附加包

基础 rootfs、板级基础、通用 DE 兼容、标准 DE、板级桌面适配与用户配置可独立交付。
标准 DE 使用发行版元包；板级通用兼容由 KDE/GNOME 共用，桌面专属控件单独打包。

```sh
python3 scripts/layers.py plan --profile kde
python3 scripts/layers.py fetch-board --profile kde
python3 scripts/layers.py pack --profile kde --context build/distributions/debian/trixie/arm64/rootfs/kde/rootfs
python3 scripts/layers.py fetch --profile kde
python3 scripts/layers.py bundle --profile kde
python3 reimuks.py --board w202ds --target rootfs --profile desktop/server --base-only
python3 reimuks.py --board w202ds --target rootfs --profile desktop/kde --from-base
```

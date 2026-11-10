# REIMUKS

REIMUKS 是面向多个设备的 Linux 发行版组装项目。本轮在本目录构建 Debian 13（trixie）ARM64 的 initramfs、Server rootfs 和 KDE rootfs。

本轮只接收预编译内核与匹配模块，不编译内核，不导入板级用户态程序、服务、配置、私有固件或修改版 Mesa / ModemManager。KDE 使用 Debian 自带软件栈，能否在 W202DS 上显示桌面、使用 GPU 和外设仍须实机验证。

## 构建目录

专属工作区：`/state/workspace/pushup/reimuks`。所有下载、工具、解包目录、日志和产物均在忽略的 `build/` 内；不会安装到宿主系统。

- `profiles/server.json`：命令行系统，`multi-user.target`。
- `profiles/kde.json`：继承 Server，增加 Plasma、SDDM、Konsole、Dolphin、NetworkManager 和 PipeWire，`graphical.target`。
- `initramfs/init`：等待根分区、验证内核身份、挂载 ext4、切换到 systemd。
- `scripts/build.py`：隔离 APT 状态，下载、解包及配置 ARM64 软件包。
- `scripts/pack.py`：导入内核、打包 initramfs 和 rootfs。
- `scripts/verify.py`：检查压缩格式、架构、包状态、所有权、启动目标和模块数量。

依赖宿主 Python 3.11+、APT、dpkg-deb、curl、liblz4；x86_64 宿主使用项目内下载的 QEMU 和 PRoot。当前 Python 路径为 `/state/home/.local/bin/python3.12`。PRoot 需要容器允许 ptrace；不需要 root、mount 或 user namespace。包配置在 PRoot + QEMU 内执行，fakeroot 保存包所有权后交给目标 tar 导出。

下载默认显式经过 Cudy `http://10.0.0.1:18080`，使用 Debian 官方镜像 `https://ftp.debian.org/debian`。APT 状态、缓存、源配置及钩子与宿主隔离；依赖版本和下载哈希记录在产物 manifest 中。在线镜像会更新，本实现记录输入，尚不保证跨日期字节一致的重建。

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

## 启动交接

initramfs 使用 LinuxBoot 所需的 **legacy LZ4（魔数 `0x184c2102`）+ newc CPIO**，不是 gzip 或现代 LZ4 frame。`/w202diag` 指向 `/init`，兼容现有内核强制命令行。

根分区选择优先读取 DT `/chosen/w202,root-partuuid`，否则读取内核命令行 `root=PARTUUID=…`、`root=UUID=…`、`root=LABEL=…` 或 `root=/dev/…`，等待最多 60 秒。当前没有内置真实分区 ID，避免误选设备分区。DT 消费逻辑是本项目新增；本地 LinuxBoot 已实现相应属性写入，详见 [DTB 约定](boot/doces/efi_dtbchosen.md)。`CONFIG_CMDLINE_FORCE=y` 的内核可能忽略启动器传入的 `root=`，应使用 DT 属性或重编译内核配置。

rootfs 默认用 ext4。initramfs 核对 rootfs 的 kernel release 和 Image 身份后切换到 systemd。内核需内建存储和 ext4 驱动；其他需要提前加载的模块填入 initramfs 的 `etc/early-modules`。当前初版不提前加载板级显示、无线等模块，rootfs 由标准 udev 按 modalias 加载。

## 产物与部署前事项

最终输出在 `build/artifacts/`：

- `initramfs-arm64.cpio.lz4`
- `server-arm64-rootfs.tar.gz`
- `kde-arm64-rootfs.tar.gz`
- `SHA256SUMS`、`verification.json`、各自 manifest 和软件包版本清单。

两个 rootfs 都带相同 Image、配置及模块。rootfs tar 包用于由有权限的部署环境解包到目标 ext4 分区，须保留数字 UID/GID、权限、ACL 和扩展属性。这不是分区磁盘镜像，也不包含 EFI / LinuxBoot 更新。

默认创建 `reimuks` 用户，root 和该用户的密码均锁定。部署前需要离线设置密码或其他登录方式，再用于实际启动；不会发布固定密码或配置自动登录。SDDM、GPU 加速、显示旋转、网络、音频及完整启动均未宣称经过硬件验收。本轮不推送 GitHub、不同步 CM2、不刷机。

在交互终端中，可执行 `python3 scripts/build.py password --profile server` 为本地 Server 根目录内的 `reimuks` 用户设置密码，再重新执行对应的 `pack.py rootfs` 和 `verify.py`；KDE 将 profile 改为 `kde`。密码由目标系统的 `passwd` 交互读取，不写入命令行或构建脚本。若重新运行 `configure`，默认账号锁定策略会重新应用。

管理账号也需部署者配置：同一命令增加 `--user root` 可设置目标 root 密码。初版不为 `reimuks` 自动授予 sudo 权限。

构建工具固定使用 [PRoot v5.5.0](https://github.com/proot-me/proot/releases/tag/v5.5.0) 的上游静态二进制，并校验发布资产的 SHA-256；ARM64 用户态模拟器及包元数据来自 Debian 的签名仓库。

## W202DS 工程入口

设备入口保留 `devices/` 分组，W202DS 放在 `devices/w202ds/`：

```text
devices/w202ds/
├── kernel -> ../../../w202ds-linux/6.18.35
└── boot   -> ../../../w202ds-boot
```

Git 中两项都是固定提交的 submodule/gitlink，远程同为 `Yeamika/w202ds-linux`，分别对应 `6.18.35` 与 `boot` 分支；本地使用上述相对符号链接。当前 boot 及 pj4edk2 中间件的源码提交只保存在本地，它们的远端分支只发布 readme.md，因此本地固定源码提交不保证能从远端获取。这套本地布局不能直接当作已经发布、可全新递归克隆的源码发行版。

启动包组装入口为 `scripts/boot_bundle.py`，具体输入与 ESP 路径见 [交接说明](boot/doces/efi_dtbchosen.md#本地-efi--initramfs-组装2026-11-10)。

# 发行版配置

发行版与 profile 仅用于 rootfs 目标；UEFI、EFI、initramfs 不接受这两个选择参数：

```sh
python3 reimuks.py --list-distributions
python3 reimuks.py --board w202ds --distribution debian/trixie \
  --target rootfs --profile desktop/server desktop/kde desktop/gnome
python3 reimuks.py --board w202ds --target initramfs
```

当前正式配置只有 `debian/trixie`，对应 Debian 13 ARM64。默认选择它，以兼容
现有命令。其他发行版、架构和包管理器尚未验证；当前后端仅实现 Debian 的
APT/dpkg、PRoot/QEMU、systemd 用户态，不把添加配置等同于支持新发行版。

每个发行版版本一个 JSON，例如 `distributions/debian/trixie.json`：

- `id`：相对本目录的路径，去掉 `.json`。
- `backend`、`architecture`：包管理后端与用户态架构。
- `suite`、`os_release`：版本标识及实际 rootfs 身份检查条件。
- `build_repositories`：主机下载目标软件包使用的源，使用已校验的 Debian keyring。
- `target_repositories`：写入目标系统 `/etc/apt/sources.list` 的源。
- `components`、`install_recommends`：组件与推荐包策略。
- `profiles`：各 profile 软件包映射文件的相对路径，以发行版主 JSON 所在目录为基准。

```text
distributions/debian/
├── trixie.json
└── trixie/
    └── desktop/
        ├── server.json
        ├── kde.json
        └── gnome.json
```

子文件分别维护软件包、验收必需包和显示管理器，不能作为发行版选择。
子文件可以用布尔字段 `install_recommends` 覆盖发行版默认的推荐包策略；
构建器将解析后的策略传给 APT。Debian KDE 使用 `kde-standard`、GNOME 使用
`gnome` 元包，两者均启用推荐依赖，并补充 Wayland、中文字体与设备集成包。
desktop/server 保留发行版默认的精简策略。标准桌面元包及关键设置、portal
等组件列入 `required_packages`，验收时不能只检查 shell 或窗口管理器。
桌面包列表仅列元包和必要补充，不重复罗列元包已经提供的应用和组件。
server 基础清单保留启动、登录、SSH、DNS/校时、文件系统管理和联网工具，
不包含 Vulkan 测试或桌面程序；`fakeroot` 目前用于目标架构的软件包配置与
归档，仍是当前构建链的必需包。initramfs 的 BusyBox 来自独立工具清单。
加载时合并子文件后计算配置哈希，单纯拆文件不影响现有缓存身份，修改包清单仍会触发身份检查。
发行版注册入口固定为 `distributions/<发行版>/<版本>.json`；也兼容主文件内联的 profile 映射。

`profiles/` 保留用途、systemd target、继承关系及占位状态；具体包名属于发行版。
解析 KDE 或 GNOME 时会先合并 desktop/server 的包，再加入相应桌面包，去重保留顺序。
未提供包映射或仍是占位的 profile 会在下载前被拒绝。

`scripts/build.py`、`scripts/pack.py`、`scripts/verify.py` 均接受
`--distribution debian/trixie`。统一入口仅在构建 rootfs 时向子进程传递该选择。initramfs 固定使用内部
默认最小用户态提供 BusyBox/blkid，不随 rootfs 发行版或桌面选项变化。
宿主工具和 boot 工具链是独立的构建依赖，不随目标发行版一起改换。

现有 Debian trixie 的目录和产物名保持不变：`build/{server,kde,gnome}`、
`build/apt-{server,kde,gnome}`、`build/artifacts/`。其他发行版使用
`build/distributions/<发行版>/<版本>/` 下独立的 rootfs、APT 缓存
和 artifacts。initramfs 作为板级公共产物仍放在默认 artifacts 下。内核导入仍共用 `build/kernel`，工具共用 `build/tools`；内核的
多版本选择不属于本次发行版抽象。

缓存和工作目录会记录发行版配置哈希，配置变化时拒绝复用，要求使用干净目录。
复用历史 Debian rootfs 前检查真实 `os-release`，不会重新 configure 已配置系统
或重设账号。新 rootfs/initramfs 和清单写入发行版身份，验证器拒绝身份不一致的
产物；没有身份字段的历史产物只兼容默认 Debian trixie。

桌面附加应用由 `debian/trixie/additional-packages.json` 独立定义，KDE、GNOME
共用 Chrome、VS Code、btop、fastfetch、vim、lazygit；不把它们写进 DE 元包
清单，也不默认加入基础 rootfs。通过 `scripts/addons.py` 生成独立软件附加包；Chrome 和 VS Code 使用各自签名的软件源，公开密钥
随配置提供并验证 SHA256，APT 仍须验证仓库签名和软件包哈希。

图形接口使用发行版 EGL/GLES/OpenGL、Vulkan loader、VA-API 和 V4L2。
硬件驱动及其选择策略由板级提供，不用发行版脚本替换驱动。
`reimuks-chrome` 默认使用 Wayland、ANGLE GLES 与 Linux GL 视频解码功能；
可显式传入 `--reimuks-vulkan` 测试 ANGLE Vulkan。附加包通过本地 desktop
覆盖使用该启动器，不修改发行版的 Chrome desktop 文件，也不禁用浏览器沙箱。
板级可在 `/etc/reimuks/acceleration.json` 指定 `va_driver`；该名称只是 libva
后端选择，不保证视频实际走硬件，仍需检查浏览器 GPU 页面和解码统计。

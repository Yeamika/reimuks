# W202DS 集成

`kernel/` 和 `boot/` 是固定提交的组件入口。硬件驱动及用户态适配由 kernel 项目 `Devices/<设备>/` 维护；REIMUKS 在本目录解释硬件状态、选择组件并定义系统行为。

- [`rootfs/`](rootfs/README.md)：先安装板级 userspace，再叠加 common 和 profile 覆盖，控制服务启用与输入语义。
- [`initramfs/`](initramfs/README.md)：W202DS 早期硬件启动动作，复用板级 USB 实现。
- [`desktop/kde/`](desktop/kde/README.md)：可选桌面网络策略与适配。
- [`userspace/display/`](userspace/display/README.md)：可选控制台息屏/合盖策略工具。

当前实现 `desktop/server` 与 `desktop/kde`；它们使用 desktop 内核。顶层 `server` 尚未实现。霍尔默认是磁感应状态，由本目录选择标准 `SW_LID` 映射，再由对应 profile 决定保持运行或交给 KDE 管理。

## 构建输入检查

`build.local.json` 保存本地编译器与 SDK 位置，不提交到仓库。编译前可以运行：

```sh
python3 devices/w202ds/build.py --profile desktop/kde --check
```

该命令只检查输入，不编译。正常构建也会先执行相同检查，集中报告缺失的编译器、SDK 头文件和宿主工具。
统一构建入口为 `reimuks.py --board w202ds --target userspace --profile desktop/kde`。

可从 [`build.example.json`](build.example.json) 创建本地配置。硬件 producer 的参数以硬件源码根目录为基准；`command_prefix` 可指定具备 Meson、Ninja、交叉编译器和代码生成工具的构建环境。GPU producer 会依次构建原生工具、目标 ICD 并生成安装树；ModemManager producer 构建硬件插件及其 daemon。缺少 producer 配置时直接报错，不复用未经检查的旧安装树。

依赖 SDK 可由发行版包离线展开，工具不会安装到宿主系统。例如：

```sh
python3 scripts/prepare_sdk.py --name modem-sdk \
  --output devices/w202ds/kernel/output/dependencies/modem \
  libglib2.0-dev libdbus-1-dev libgudev-1.0-dev \
  libpolkit-gobject-1-dev libsystemd-dev
```

生成 `root/`、`arm64.ini` 和依赖包哈希清单。SDK 包版本来自所选发行版，硬件构建脚本只消费 SDK；更换 SDK 后必须重新构建对应组件。

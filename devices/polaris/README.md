# Polaris / Xiaomi MIX 2S

SDM845 板级工程按与 W202DS 相同的职责边界组织。当前只登记 `desktop/server`；
KDE、GNOME 和 Niri 保持未实现状态。

```text
devices/polaris/
├── board.json
├── kernel -> ../../../POLARIS-DEV/git-sources/linux
├── boot -> ../../../POLARIS-DEV/git-sources/boot
├── initramfs/rootfs/              # 早期启动 hook 与独立工具
├── overlays/
│   ├── polaris-kernel/            # 内核构建和产物描述
│   ├── polaris-hardware/          # USB、DRM、看门狗等板级接口
│   └── polaris-server/            # Server 登录和 Polaris 电源键参数
└── tests/

overlays/services/powerkey/        # 可复用的 logind 策略和电源键服务

config/boards/polaris/
├── packages.json
└── server.json
```

`server.json` 选择共享电源键服务、内核层、板级硬件层和 Server 层。共享服务
实现输入事件与短按状态机；Polaris 只提供电源键设备名、显示 blank 接口和
Server profile 启用策略，设备特定行为不放进共享服务源码。
发行版包、桌面包、用户配置
由上级 REIMUKS 配置组合；MIX 2S 的私有账号和联网配置不进入公共板级层。

```sh
python3 scripts/overlay-scan.py --board polaris
python3 reimuks.py --board polaris --target userspace rootfs --profile desktop/server
```

内核、boot、UEFI、EFI、ESP、initramfs 与 rootfs 产物统一进入
`build/boards/polaris/`，构建不写手机分区。rootfs 使用 Debian `non-free-firmware`
组件。启动时由 EFI 传入 root PARTUUID，initramfs 校验并挂载 ext4 rootfs；rootfs
另安装 ABI 匹配的内核运行时包并生成 depmod 索引。

initramfs 可通过 `reimuks.break=initramfs` 停在 USB ACM 检查点；`reimuks.drm=0`
关闭原生 DRM 接管。`reimuks.logpart=PARTUUID=<ESP GUID>` 启用 EFI diagnostics
目录日志，`reimuks.recover=1` 在检查点不可用时自动恢复。看门狗由固件、内核、
initramfs 和 systemd 分阶段接管，行为及实机验证记录放在板级测试说明中。

当前已验证 USB ACM、UFS、Debian Server switch_root 和原生 DPU/DSI 输出；GPU
加速及图形桌面仍未验收。kernel 与 boot 保留指向各自源码工程的相对链接。

# EFI 与 Linux 的 DTB `/chosen` 参数

本文记录三类启动参数。LinuxBoot 在交接内核前将它们写入 DTB 的 `/chosen` 节点，Linux 内核及 initramfs 分别读取。

W202DS 生产方状态以 2026-11-08 检查的板级源码为准。2026-11-10，REIMUKS 在 `initramfs/init` 新增 rootfs 分区属性消费逻辑；LinuxBoot 写入该属性仍待实现，尚未完成实机联调。

```text
Boot 页面选择启动项
  → EFI 宿主启动 LinuxBoot
  → LinuxBoot 加载内核与 initramfs，并更新 DTB
  → 将 DTB 地址通过 ARM64 x0 寄存器交给 Linux
  → 内核启动 initramfs，由其挂载并切换到目标 rootfs
```

## 参数总览

| 参数 | DTB 属性 | 接收方 | 当前状态 |
| --- | --- | --- | --- |
| initramfs 内存范围 | `linux,initrd-start`、`linux,initrd-end` | Linux 内核 | W202DS 已实现 |
| rootfs 分区 | `w202,root-partuuid` | initramfs | REIMUKS 已新增读取，LinuxBoot 写入待实现 |
| 启动显示信息 | `pocketjs,boot-display` | Linux 早期控制台和 DRM 驱动 | W202DS 已实现 |

## 1. `linux,initrd-start` / `linux,initrd-end`

这两个属性指明已经加载到物理内存中的 initramfs 范围，由内核在早期读取。

- `linux,initrd-start`：实际加载的物理起始地址。
- `linux,initrd-end`：起始地址加实际加载的 ramdisk 字节数；该结束地址不包含在范围内。
- W202DS LinuxBoot 使用 `fdt_setprop_u64()` 写入大端 64 位值。
- 属性中的地址与大小必须对应实际载荷；写入属性前，由加载器完成内存布局和载荷检查。

这两个地址用于找到 initramfs。最终磁盘上的 rootfs 由 initramfs 中的启动逻辑选择。

## 2. rootfs 分区：`w202,root-partuuid`

拟定使用 `/chosen/w202,root-partuuid` 传递目标根分区的 GPT PARTUUID，属性类型为以 NUL 结尾的字符串。PARTUUID 标识磁盘分区，与 ext4 文件系统 UUID 分别处理。

LinuxBoot 负责将所选启动项对应的分区标识写入 DTB。initramfs 挂载 sysfs 后，从以下属性文件读取，去掉字符串末尾的 NUL：

```text
/sys/firmware/devicetree/base/chosen/w202,root-partuuid
```

initramfs 根据 PARTUUID 查找并等待目标块设备，复用 rootfs 身份、内核版本及模块匹配检查，然后挂载根文件系统并执行 `switch_root`。

同一分区放置多个 rootfs 时，可扩展 `w202,root-subdir` 指定分区内的相对目录；该扩展同样待实现。

`w202,root-partuuid` 是本项目拟定的自定义属性。REIMUKS 新增的 `initramfs/init` 优先读取该属性，使用 `blkid` 查找 GPT PARTUUID 对应的设备，等待最多 60 秒，并核对 rootfs 内的 kernel release 和 Image 身份后切换根目录；缺少属性时回退到命令行 `root=`。原 W202DS 根选择脚本读取 `/bsp/root.conf`，与此新实现不同。LinuxBoot 已写入的 `w202,uefi-profile` 目前仅标记 KDE/Server，本轮 REIMUKS 也不据此自动猜测分区。

## 3. `pocketjs,boot-display`

该属性传递启动画面的显示交接信息，包括 framebuffer 布局、输出区域的位置和大小、旋转等。

现有传递路径为：

```text
Boot 页面 display_regions
  → EFI 宿主生成 PJB_BOOT_DISPLAY 并发布到 UEFI 配置表
  → LinuxBoot 校验显示布局并转换为 DTB 属性
  → Linux 早期控制台及 DRM 驱动读取 pocketjs,boot-display
```

W202DS 当前编码为 **20 个大端 u32，共 80 字节**。生产方与消费方须使用一致的布局，沿用 `LinuxDisplayCells()` 与显示驱动的校验约定。当前布局包含 W202DS 的 framebuffer 和旋转约束，其他板型需定义对应的显示适配。

## 与内核命令行的关系

上述属性通过 DTB 传递，独立于 `/chosen/bootargs` 中的内核命令行。`CONFIG_CMDLINE_FORCE=y` 不会阻止内核、显示驱动或 initramfs 读取这些属性。

## 参考实现位置

- `w202ds-boot/pocketjs4edk2_uefi/efi/LinuxBoot/LinuxBoot.c`：更新 `/chosen` 和发布显示属性。
- `w202ds-boot/pocketjs4edk2_uefi/efi/LinuxBoot/LinuxDisplay.h`：当前显示属性的编码。
- `w202ds-boot/pocketjs4edk2_uefi/efi/LinuxBoot/EnterKernel.S`：通过 `x0` 交接 DTB。
- `w202ds-linux/6.18.35/kernel/drivers/of/fdt.c`：内核读取 initrd 地址。
- `reimuks/initramfs/init`：本轮新 initramfs 的 rootfs 选择、身份检查与切换逻辑。
- `w202ds-linux/6.18.35/integration/kernel/initramfs/try-persistent-root.sh`：原板级 initramfs 的根选择参考。
- `w202ds-linux/6.18.35/Devices/drm/source/pj4edk-boot-display/pj4edk-boot-display.c`：早期显示交接。
- `w202ds-linux/6.18.35/Devices/drm/source/baseline/w202_boot_console.c`：DRM 阶段的启动控制台。

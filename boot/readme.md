# 启动交接

[`initramfs/init`](../initramfs/init) 优先读取 DT `/chosen/pj4edk2,root-partuuid`，兼容 `w202,root-partuuid`。值为 36 字节 GPT PARTUUID 加 NUL。无属性时回退到内核命令行 `root=`。

initramfs 挂载 ext4，并核对根系统记录的内核版本、Image 校验值和模块目录，再切换到根系统。

W202DS 可用 [`scripts/boot_bundle.py`](../scripts/boot_bundle.py) 从匹配的 Image、initramfs、DTB 和实际 PARTUUID 生成 ESP 载荷。LinuxBoot EFI 由板级启动工程提供；载荷组装不分区、不刷机。

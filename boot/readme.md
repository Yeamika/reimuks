# REIMUKS Boot

本目录记录 REIMUKS 与 EFI 加载器、Linux 内核及 initramfs 之间的启动交接约定。

- [EFI DTB `/chosen` 参数](doces/efi_dtbchosen.md)：initramfs 内存范围、rootfs 分区标识、启动显示信息。

当前以 W202DS 的 LinuxBoot 实现为参考：initramfs 地址和启动显示信息已有板级实现；通过 DTB 选择 rootfs 分区的读写逻辑待实现。这里只记录接口，不代表发行版构建器或新的启动流程已经完成。

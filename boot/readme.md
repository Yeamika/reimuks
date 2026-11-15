# REIMUKS Boot

本目录记录 EFI、Linux 内核、initramfs 与根系统的交接约定。

- [DT `/chosen` 参数](doces/efi_dtbchosen.md)：initramfs 内存范围、根分区标识与启动显示信息。

启动配置位于 ESP，由 LinuxBoot EFI 读取；EFI 传递根分区 PARTUUID 和内核启动参数，initramfs 挂载根分区并交接给系统 init。切换根分区或 systemd 启动目标无需重新打包 initramfs。

REIMUKS 不读取 GPT，也不把分区号或磁盘容量绑定到 rootfs 构建。ESP 文件树由明确指定的启动产物与配置组合；生成文件系统镜像时单独指定容量。分区表管理、格式化和刷写属于部署步骤。

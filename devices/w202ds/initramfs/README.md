# W202DS initramfs 集成

此目录只定义 W202DS 早期启动行为，通过 `rootfs/usr/lib/reimuks/initramfs.d/20-hardware` 启动 ACM/NCM 并选择 stock DVFS 电压偏移。通用 `initramfs/init` 仅执行板级钩子、定位根分区并切换根文件系统。

USB gadget 的唯一实现来自板型 kernel 项目的 `Devices/usb3/userspace/rootfs/usr/libexec/w202-usb-gadget`，打包到 `/bin/w202-usb-gadget`，与 rootfs 共用源码。地址和 gadget 名称来自 `../rootfs/common/etc/default/w202-usb-gadget`，不会在 initramfs 中维护第二套硬件脚本。

打包仅复制文件，不运行钩子或操作构建机硬件。

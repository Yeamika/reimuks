# 小米 MIX 2S（Polaris）

[debian-server](targets/debian-server.json) 组合 Polaris 内核、板级硬件和通用电源键层。板级配置在 [board.json](board.json) 和 [overlays/](overlays/)；内核和启动源码由 [子模块](../../.gitmodules) 提供。

[initramfs](initramfs/rootfs/) 负责板端早期初始化。排查启动可用 `reimuks.break=initramfs` 等待 USB ACM，或用 `reimuks.drm=0` 跳过早期 DRM 接管。根分区参数见[启动交接](../../boot/readme.md)。

# Polaris initramfs

早期启动文件只放在 `initramfs/rootfs/`，由 Polaris 板级 initramfs 配置独立纳入，
不作为普通 rootfs overlay。当前 hook 初始化看门狗、尝试 USB ACM shell、按启动参数
控制 MSM DRM 接管，并在挂载 rootfs 前提供诊断检查点。

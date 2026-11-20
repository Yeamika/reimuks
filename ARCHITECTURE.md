# 分层与产物

[统一入口](README.md)按 `devices/<board>/targets/` 的 JSON 配方组合层包。

- [发行版](distributions/)提供基础用户态和标准桌面包；[板级目录](devices/)选择匹配的内核、硬件服务和桌面适配。
- `overlays/services/` 放通用服务；`overlays/apps/` 放可选应用组；`overlays/user/` 放私有层的打包脚本。
- 各层自行出包并提供 `package.json`。配方可引用已有包，也可声明 `producer` 和 `requires` 以在缺包时调用该层脚本。组合过程不改写基础层。

账号、SSH 授权和桌面偏好单独叠加。命名用户层默认从 `build/private-overlay-inputs/<board>/<id>/` 读取输入，也可传 `--user-overlay ID=PATH`。设备私有 NV 由 rootfs 配方单独引用，不进入公共层包。

`rexeterm` 只安装板端 `rexed` 服务。私有输入为 ARM64 的 `rexed`、`server-cert.pem`、`server-key.pem` 和 `client-cert.pem`。

组合预设输出层包归档；rootfs 预设把选定层安装到文件系统。内核镜像与 [EFI、initramfs](boot/readme.md) 是独立启动产物；分区和刷写在部署时处理。

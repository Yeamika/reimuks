# 可选控制台显示策略

`source/w202-screen.c` 提供控制台空闲、输入、合盖和背光联动。该工具包含系统行为，因此由 REIMUKS 板型集成维护；板级 DRM 模块及显示准备脚本仍由 kernel 项目的 `Devices/drm/` 维护。

```sh
make OUT=/path/to/output
make OUT=/path/to/output DESTDIR=/path/to/staging install
```

只编译或离线暂存，不启用服务。当前 desktop/server 采用 `rootfs/profiles/desktop/server/` 中的全屏登录流程，不默认运行此策略循环。启用前应针对目标内核和 backlight 接口单独验收。

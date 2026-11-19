# GNOME 实验桌面

`desktop/gnome` 继承 desktop/server 的基础软件包，使用独立的 GNOME Shell、
GNOME Session、GDM 登录、NetworkManager、PipeWire 和方向传感器服务。
软件包映射见 `distributions/debian/trixie/desktop/gnome.json`，默认目标为 graphical.target。
共享硬件服务与 C JSON 控制入口由 `devices/w202ds/rootfs/desktop-common/`
及 `devices/w202ds/desktop/common/` 提供，打包前需先构建并暂存 ARM64 后端。
不包含 KDE 的 KWin 脚本、网络面板补丁或自定义开关，它们不能直接作为 GNOME 插件使用。

从仓库根目录构建：

```sh
python3 reimuks.py --board w202ds --distribution debian/trixie \
  --target rootfs --profile desktop/gnome
```

通用包树在 `build/distributions/debian/trixie/arm64/rootfs/gnome/`，
软件包缓存位于同一发行版目录的 `cache/apt-gnome/`；板级产物为
`build/boards/w202ds/artifacts/desktop-gnome-arm64-rootfs.tar.gz`。
账号按通用账号配置提供，不设置默认密码或自动登录。
这是独立 rootfs；不是在现有 KDE 系统上直接替换显示管理器的安装脚本。

当前完成配置解析、板级策略测试及 Debian ARM64 APT 依赖模拟；
尚未完成完整 rootfs 构建及实机启动验证。
实机应检查 GDM 登录、Wayland 会话、Mali/DRM 渲染、触摸、屏幕键盘、
方向传感器、接键盘锁定、网络和音频，并保留串口或 USB 恢复通道。
不要把 KDE 开关已具备的功能视为 GNOME 已支持。

新增软件包映射会改变发行版配置哈希。已有缓存若提示身份不匹配，
按项目缓存规则处理，不要删除或伪造身份标记来强行复用。

共享后端接口和构建见 `devices/w202ds/desktop/common/README.md`；
多 DE 验收矩阵见 `devices/w202ds/desktop/TESTING.md`。GNOME 自定义快捷开关尚未实现。

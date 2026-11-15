# 附加软件

发行版的软件包名称、额外软件源和加速依赖配置见 [Debian trixie 配置](../../distributions/debian/trixie/additional-packages.json)。软件组包含 Chrome、VS Code、btop、fastfetch、vim 和 lazygit，独立于桌面环境选择。

```sh
python3 scripts/addons.py fetch --profile kde
python3 scripts/addons.py pack --profile kde
```

输出为 `build/artifacts/apps-arm64.tar.gz`，包含应用、APT 解析出的依赖、版本/哈希清单、离线安装脚本和 Chrome 加速启动策略。支持 `--distribution`；GNOME 可选择 `--profile gnome`。若已有包含这些软件的完整认证缓存，可用 `pack --cache <缓存目录>`，无需重新下载。

在目标系统解包到一个临时目录，然后以 root 执行其中的 `install.sh`。脚本先校验包哈希，再通过 `apt-get --no-download` 安装；保留依赖检查。附加包不携带 W202DS 专用驱动，通用图形库仍由 APT 管理。安装后由 APT 正常管理、升级或卸载软件。目标必须是匹配架构/发行版的 REIMUKS 基础系统，硬件加速仍依赖板级提供的驱动；附加包不代表加速已通过真机验证。

应用不再默认加入基础 rootfs 的直接包清单；EGL/GLES/OpenGL/Vulkan/VA-API 等通用加速依赖仍属于桌面基础层。

已有认证缓存也可以离线更新基础包选择：`python3 scripts/build.py fetch --offline --profile kde`，再运行 `configure`、`pack.py rootfs` 和 `verify.py --profile kde`。`configure` 会通过 dpkg 清除不再属于选择清单的包；旧版原地叠加过私有文件的树仍须重新 assemble，不能以包清理替代干净暂存。

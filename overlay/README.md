# 可选叠加层

| 入口 | 职责 |
| --- | --- |
| [board](board/README.md) | 板级基础服务与硬件运行接口 |
| [de](de/README.md) | 发行版通用桌面接口及标准 KDE/GNOME |
| [board-de](board-de/README.md) | 板级通用 DE 兼容，多个桌面复用 |
| [board-desktop](board-desktop/README.md) | 板级对具体桌面的控件和行为适配 |
| [apps](apps/README.md) | Chrome、VS Code 等独立附加应用 |
| [user](user/README.md) | 私有账号、连接及用户设置 |

软件层使用 `.deb` 和 APT 管理依赖、文件归属及升级；离线压缩包只是运输容器。用户文件独立打包并合并到最终部署归档。源码保留在发行版和设备目录，本目录不复制另一份配置。

```sh
# 查看包的依赖和责任边界
python3 scripts/layers.py plan --profile kde
# 生成当前组合的板级包与桌面元包；需先构建板级 userspace
python3 scripts/layers.py pack --profile kde --context build/kde/rootfs
# 生成不含板级/桌面包的基础归档（需先配置 server 包树）
python3 scripts/pack.py rootfs --profile server --base-only
# 获取可离线安装的桌面依赖，随后在构建机组合完整 rootfs
python3 scripts/layers.py fetch --profile kde
python3 scripts/layers.py bundle --profile kde
python3 scripts/pack.py rootfs --profile kde --from-base
```

基础归档为 `build/artifacts/desktop-base-arm64-rootfs.tar.gz`。完整组合仍输出固定的 `desktop-kde-arm64-rootfs.tar.gz`（GNOME 类似）；账号默认锁定，私有设置通过 user overlay 合并。`--from-base` 从已配置的标准 server 包树复制暂存，离线安装 DE 和板级包，不修改基础树，目标设备无需编译。

原有 `reimuks.py --target rootfs --profile desktop/kde` 保留完整构建入口，板级内容改为通过 dpkg 安装。统一入口也支持 `--base-only`、`--from-base` 和 `--de-cache`。基础归档、附加包和完整镜像均不携带内核/模块；硬件运行所需的合法私有固件和匹配内核仍由部署阶段提供。

同一镜像选择一套板级场景策略：Server 策略与图形兼容包互斥，KDE/GNOME 的板级专属策略也互斥。通过 APT 切换时需要处理这些依赖；不把已定制的用户家目录当作可自动回滚的软件包内容。

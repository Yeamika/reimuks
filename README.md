# REIMUKS

用可复用的内核、Debian、板级适配和桌面层，为 W202DS 与小米 MIX 2S 组装 ARM64 系统。每层由自己的脚本出包，应用和用户配置按需叠加。

## 构建

在仓库根目录使用 Python 3.11+，选择板子和预设：

```sh
python3 reimuks.py --board w202ds --preset debian-niri --plan
```

`--plan` 只检查构建输入。准备好预设所需的层包和私有输入后，去掉 `--plan` 即可构建。层包默认从 `build/packages/` 读取，可用 `--package-root` 指定。

| 板子 (`--board`) | 预设 (`--preset`) | 默认产物 |
| --- | --- | --- |
| [W202DS](devices/w202ds/) `w202ds` | `debian-server`、`debian-kde` | 层包归档 `.tar` |
| W202DS `w202ds` | `debian-niri`、`debian-kde-remote` | 完整 rootfs `.tar.gz` |
| [小米 MIX 2S](devices/polaris/) `polaris` | `debian-server` | 层包归档 `.tar` |

预设在 `devices/<board>/targets/`。成品默认在 `build/boards/<board>/artifacts/targets/`，可用 `--build-root` 调整。

- `--app-overlay` 添加应用组：`remote`、`tui-app-basic`、`gui-test`。
- `--user-overlay` 添加私有配置，如 `passkey` 和 `kde-theme`。两种 overlay 参数都可以重复使用。
- `--clean` 替换同名 rootfs 预设成品，保留共享层包和下载缓存。

更多参数见 `python3 reimuks.py --help`。原理与接口见[分层说明](ARCHITECTURE.md)，基础系统配置见[发行版说明](distributions/README.md)。

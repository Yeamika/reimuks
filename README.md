# REIMUKS

为 W202DS 与小米 MIX 2S 组合可复用的内核、Debian、板级和桌面层包。

在仓库根目录使用 Python 3.11+：

```sh
python3 reimuks.py --board w202ds --preset debian-niri --plan
```

`--plan` 检查输入并列出构建计划；去掉它即可构建。预设在 `devices/<board>/targets/`。

| 板子 (`--board`) | 预设 (`--preset`) | 产物 |
| --- | --- | --- |
| [W202DS](devices/w202ds/) `w202ds` | `debian-server`、`debian-kde` | 层包归档 `.tar` |
| W202DS `w202ds` | `debian-niri`、`debian-kde-remote` | 完整 rootfs `.tar.gz` |
| [小米 MIX 2S](devices/polaris/) `polaris` | `debian-server` | 层包归档 `.tar` |

- `--app-overlay` 叠加 `remote`、`tui-app-basic` 或 `gui-test`，可重复指定。
- `--user-overlay` 叠加 `passkey` 或 `kde-theme`，可重复指定；私有输入可用 `--user-input-root` 指定。
- `--clean` 替换默认路径下同名的 rootfs 预设成品，保留共享层包和下载缓存。

层包默认从 `build/packages/` 读取，成品默认写到 `build/boards/<board>/artifacts/targets/`。
更多参数见 `python3 reimuks.py --help`；层包和私有输入见[分层说明](ARCHITECTURE.md)。

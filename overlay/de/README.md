# 标准桌面附加包

`reimuks-de-common` 提供发行版通用桌面接口依赖；`reimuks-de-kde` / `reimuks-de-gnome` 选择发行版标准桌面及 Wayland 登录。包内不含 W202DS 控件或驱动。

通用包清单在 `distributions/debian/trixie/desktop/common.json`，桌面清单在同目录的 `kde.json` / `gnome.json`。

```sh
python3 scripts/layers.py fetch --profile kde
python3 scripts/layers.py bundle --profile kde
```

输出 `build/artifacts/de-kde-arm64.tar.gz`，内含依赖闭包、两个元包、SHA-256 清单及离线安装脚本。已解包的附加包可在匹配发行版/架构的目标系统以 root 执行 `install.sh`。安装由 APT 管理，缺少依赖时不会联网补包。

也可从已有认证缓存离线重新选择，任何新增或哈希不同的包都会被拒绝：

```sh
python3 scripts/layers.py fetch --offline --profile kde --cache build/apt-kde
```

GNOME 将上述 `kde` 替换为 `gnome`。它使用独立缓存和产物，尚需实机验证。GDM 的单一发行版配置文件通过安装脚本更新 daemon 选项，不由两个软件包重复拥有。

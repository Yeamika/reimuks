# 板级桌面专属适配包

`reimuks-w202ds-kde` / `reimuks-w202ds-gnome` 依赖板级通用 DE 兼容包和对应标准桌面包。

KDE 包包含 Plasma 控件、KWin 会话联动、KSystemStats 插件、旋转入口及 PowerDevil 策略。GNOME 包只包含已实现的 GNOME 适配，不安装 KDE 程序。

```sh
python3 scripts/layers.py pack --profile kde --context build/kde/rootfs
```

KDE 小部件从明确的已配置发行版树生成；该树只提供声明的模板输入，不把其账号、包数据库或私有配置带进包。原始发行版小部件保持不变。升级 Plasma 后应重新生成并验证用户级覆盖；既有用户的同名设置不会被强制替换。

源码仍在 `devices/w202ds/desktop/<桌面>/`，选择与策略由 `rootfs/packages.json`、`rootfs/policy.json` 管理。

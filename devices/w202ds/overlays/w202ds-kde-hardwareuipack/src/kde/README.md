# W202DS KDE 适配

Plasma 控件和会话脚本通过 `w202-hardware-controls` 使用 [Pack2](../../../w202ds-hardwarepack2/src/README.md)。本层也提供旋转、键盘套联动和 GPU/VPU 监控。

[prepare.py](prepare.py) 从发行版小部件生成用户覆盖。升级 Plasma 后要基于新版小部件重新生成；删除家目录中对应的覆盖并重新登录，可恢复发行版小部件。

会话沿用用户在 KDE 设置里的合盖动作；选择合盖息屏时，本层负责开盖后唤醒显示。

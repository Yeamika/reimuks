# 电源键服务

共享短按、长按处理。`/etc/default/reimuks-powerkey` 配置输入设备、按键时长和动作；板级提供 `/usr/libexec/reimuks-display-toggle`。动作可选 `display-toggle`、`poweroff`、`suspend`、`ignore`。

由本层 [package.py](package.py) 出包，预设声明所需的板级接口。

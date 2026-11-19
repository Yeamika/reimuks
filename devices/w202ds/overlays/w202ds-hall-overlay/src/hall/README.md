# Server 霍尔显示策略

`desktop/server` 通过 `w202ds-hall-overlay` 启用本策略。
复用公共 `w202-hall-input` 的标准 `SW_LID`：合盖两秒后息屏，开盖立即亮屏；
系统、SSH 和网络继续运行。去抖由公共霍尔桥完成，本程序不重新解释原始 GPIO。

程序只读取 `REIMUKS Lid Switch`，通过原生 DRM fbdev 的 `blank` 接口控制显示，
不独占输入，不处理电源按钮，也不直接控制 DSI 或背光寄存器。
启动／输入设备重建时读取当前开合状态；事件丢失后重新同步。
合盖期间检查意外亮屏并恢复息屏；开盖后不干预其他空闲或电源键策略。
KDE／GNOME 继续使用各自电源管理，不安装本策略。

常规板级集成构建 `scripts/overlay-build.py --board w202ds --profile server` 会同时构建本程序。
也可单独执行 `make -C devices/w202ds/overlays/w202ds-hall-overlay/src/hall stage`，显式传入 `CC`／`OUT`。
默认产物遵循 `REIMUKS_BUILD_ROOT`，位于选定板级构建目录的 `server-hall/`。
rootfs 打包会检查 ARM64 ELF 缺失，不在目标设备上编译。

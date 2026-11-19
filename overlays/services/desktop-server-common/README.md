# Server 公共控制台层

本目录独立打包控制台和电源键服务。输入是 [powerkey 组件](../powerkey/README.md)已构建的目标架构程序；打包不需要设备源码、内核或发行版 rootfs。以 W202DS 的现有 ARM64 构建为例，在 REIMUKS 根目录运行：

```sh
python3 overlays/services/desktop-server-common/package.py \
  --architecture arm64 \
  --powerkey build/boards/w202ds/powerkey/rootfs/usr/libexec/reimuks-powerkey \
  --output build/packages/overlays/services/arm64/server-common-new
```

输出目录只有本层的压缩包和 `package.json`。在目标配置里更换本层的清单路径即可采用新包，其他层继续复用。Debian 的 APT 安装适配器视其文件归属独立导出，安装时应选用与本层同一发布批次的适配器。

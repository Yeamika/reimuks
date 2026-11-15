# 可选叠加层

- [user](user/README.md)：账号、网络、蓝牙和用户文件；私有输入不提交。
- [apps](apps/README.md)：独立的附加软件包组。

基础 rootfs 不携带私有配置。用户配置包通过 `scripts/user_overlay.py` 合并到独立部署归档，基础归档保持不变。软件附加包通过目标系统包管理器安装，保留依赖检查与软件包数据库。

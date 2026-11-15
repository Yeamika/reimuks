# 用户配置

将私有文件放到被 Git 忽略的 `overlay/user/files/`，目录结构对应目标系统路径，例如：

```text
files/
├── etc/
│   ├── shadow
│   └── NetworkManager/system-connections/
├── home/reimuks/.ssh/authorized_keys
└── var/lib/bluetooth/
```

`shadow` 仅保存目标系统密码哈希，建议 0600；网络凭据和 SSH 文件也应设置严格权限。已有私有目录可以直接传给 `--source`。

```sh
python3 scripts/user_overlay.py pack --source overlay/user/files --output build/artifacts/user-overlay.tar.gz
python3 scripts/user_overlay.py merge \
  --base build/artifacts/desktop-kde-arm64-rootfs.tar.gz \
  --overlay build/artifacts/user-overlay.tar.gz \
  --output build/artifacts/desktop-kde-arm64-deployment.tar.gz
```

基础目录权限与系统文件 uid/gid 保留，家目录文件按基础系统账号映射。合并不执行私有文件；部署前需检查配置是否适配基础版本。

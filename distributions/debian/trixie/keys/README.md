# APT 仓库签名公钥

- [Chrome](https://dl.google.com/linux/linux_signing_key.pub)
- [VS Code](https://packages.microsoft.com/keys/microsoft.asc)
- [Moonlight Qt](https://dl.cloudsmith.io/public/moonlight-game-streaming/moonlight-qt/setup.deb.sh)：`402E1E45A2456EDCF32A5E0E2F6AE14E1C660D44`

换钥时同步更新 [additional-packages.json](../additional-packages.json) 中的 SHA256，并验证 APT 可通过签名检查。

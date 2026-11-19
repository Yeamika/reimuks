# Repository signing keys

Google Chrome uses the public key distributed in Google's Chrome package
repository setup script. Microsoft VS Code uses Microsoft's Linux repository
signing key. Moonlight Qt uses the project's Cloudsmith repository key
(`402E1E45A2456EDCF32A5E0E2F6AE14E1C660D44`). The additional-package manifest pins each file's SHA256; APT
validates signed repository metadata before fetching packages.

Upstream key locations:

- https://dl.google.com/linux/linux_signing_key.pub
- https://packages.microsoft.com/keys/microsoft.asc
- https://dl.cloudsmith.io/public/moonlight-game-streaming/moonlight-qt/setup.deb.sh

Key rotation requires updating the public key and its manifest digest together,
then verifying a fresh authenticated APT update. Never disable signature checks.

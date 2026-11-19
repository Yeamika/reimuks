# 发行版配置

当前发行版是 [Debian trixie ARM64](debian/trixie.json)。主配置选用软件源和包映射，[desktop/](debian/trixie/desktop/) 定义各环境的软件包，[additional-packages.json](debian/trixie/additional-packages.json) 定义可选应用的来源。

基础用户态在 `build/distributions/` 共享；板级依赖和用户层在组合时加入。[第三方签名公钥](debian/trixie/keys/README.md)随配置维护。

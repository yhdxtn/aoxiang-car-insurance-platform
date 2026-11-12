# 源码包说明

建议使用 `taikang-mini-suite-source.zip`，它包含四端源码、泰康协议适配器、全部运行说明及部署模板。

另提供四个分包，全部保留相同的 `taikang-mini-suite/` 顶层目录，可以在同一目标目录解压合并：

| 文件 | 包含内容 |
|---|---|
| `taikang-mini-program-source.zip` | `miniprogram` 原生小程序 |
| `taikang-backend-source.zip` | `backend` Java后端、`services/taikang-gateway`、共享文档/脚本/部署模板及配置示例 |
| `taikang-admin-web-source.zip` | `apps/admin-web` 管理网页 |
| `taikang-service-web-source.zip` | `apps/service-web` 客服网页 |

只运行某个前端时，进入对应目录阅读其 README，并将API指向已启动的Java服务。后端分包可独立运行Java和网关；其Docker网页构建模板仍需要两个网页目录，因此完整部署使用完整包，或先合并四个分包。

完整包的 `SOURCE-MANIFEST.json` 记录源码相对路径、字节数及SHA256，可检查解压后文件是否完整。分包与完整包采用同一版本源文件。

压缩包不包含依赖缓存、构建产物、演示数据库、真实密码或本机私有配置。网页执行 `npm ci`，Java执行 `mvn package`，网关安装 `requirements.lock` 即可重建；小程序由微信开发者工具直接导入。

# 运行与部署说明

## 一、开发运行顺序

本地先运行演示后端，再启动管理端和客服端，最后导入小程序。演示不需要泰康账号、OCR 服务和 MySQL。根 README 已给出完整命令与四个演示账号。

| 组件 | 要求 | 默认端口 |
|---|---|---:|
| Java 后端 | **JDK 21**（含 javac，不是仅 JRE）、Maven 3.9+ | 18080 |
| 管理网页 | Node.js 22+，npm | 5173 |
| 客服网页 | Node.js 22+，npm | 5174 |
| 小程序 | 微信开发者工具与对应小程序 AppID | 不单独占服务器端口 |
| 正式数据库 | MySQL 8.4，utf8mb4 | 3306或你配置的端口 |
| 泰康协议适配器 | Python 3.12/3.13，单实例 | 私有18081 |

浏览器开发代理与小程序配置不同：网页的 `/api` 会由 Vite 转发；小程序 `config.js` 必须填写完整 Java API 基址，例如 `https://api.example.com/api/v1`。

## 二、生产配置准备

项目根目录运行：

```bash
python3 scripts/generate-env.py
```

生成 `.env` 后修改实际微信配置、承保地区、域名等。该文件不自动加载到所有进程：Docker Compose 会通过 `env_file` 读取；systemd 使用 `EnvironmentFile`；命令行启动请先加载环境。

若使用 shell，不要直接把未加引号且含 `&` 的 JDBC URL 当成 shell 命令执行。可用下列 Python 方式加载简单 `KEY=value` 环境文件并启动 Java：

```python
from pathlib import Path
import os, subprocess
env = os.environ.copy()
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        env[key.strip()] = value
subprocess.run(['java', '-jar', 'backend/target/mini-insurance-api-1.0.0.jar'], env=env, check=True)
```

环境文件是简单字面量格式，不支持 shell 命令替换。首次启动正式后端会创建用户名 `admin`，密码取 `BOOTSTRAP_ADMIN_PASSWORD`。后续修改该变量不会重置已存在管理员，密码在网页“账号设置”里更改。

## 三、普通 Linux 服务器（无需 Docker）

### 1. 数据库

建立一个**独立新库**，不要指向旧企业微信系统的库。

```sql
CREATE DATABASE taikang_mini CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'taikang_mini'@'127.0.0.1' IDENTIFIED BY '替换为你生成的数据库密码';
GRANT ALL PRIVILEGES ON taikang_mini.* TO 'taikang_mini'@'127.0.0.1';
```

上面的 SQL 是管理员创建专用数据库账户的示例；请使用真实密码并按 MySQL 连接来源配置账户主机。后端配置：

```dotenv
DB_URL=jdbc:mysql://127.0.0.1:3306/taikang_mini?useUnicode=true&characterEncoding=utf8&serverTimezone=UTC
DB_USERNAME=taikang_mini
DB_PASSWORD=你的数据库密码
```

启动时 Flyway 自动执行 `backend/src/main/resources/db/migration/V1__initial_schema.sql`，不需要再手工重复建表。若已有库，先备份，后续版本用新增迁移；不要直接改已上线迁移文件的校验值。

### 2. 编译和运行 Java

```bash
cd backend
mvn -B package
java -jar target/mini-insurance-api-1.0.0.jar
```

正式环境不加 `--spring.profiles.active=demo`。默认正式模式会要求 MySQL 和资料加密密钥；不会因为缺真实配置而切入演示数据。

推荐将项目放在 `/opt/taikang-mini`，创建专用 `taikang` 系统账户，将环境文件放到 `/etc/taikang-mini.env`，权限限制为该服务账户可读。参考 `deploy/taikang-api.service`，按实际 JDK 路径、内存和工作目录调整，再交给 systemd 管理。

首次部署须创建两个可写数据目录；例如由服务器管理员执行：

```bash
install -d -o taikang -g taikang -m 0700 /opt/taikang-mini/backend/data/private-files
install -d -o taikang -g taikang -m 0700 /opt/taikang-mini/services/taikang-gateway/var
```

服务账户还须能读取程序和配置、遍历其父目录。若更改了 `UPLOAD_DIR` 或 `TK_LEDGER_PATH`，请给实际目标目录设置相同的写入权限。

健康接口：`GET http://127.0.0.1:18080/api/v1/public/health`。它只用于健康检查，不返回环境密钥。

### 3. 运行泰康适配器

```bash
cd services/taikang-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
```

使用 `deploy/taikang-gateway.service` 或在加载环境变量后运行：

```bash
PYTHONPATH=src .venv/bin/uvicorn tk_gateway.app:create_app --factory --host 127.0.0.1 --port 18081 --workers 1 --no-access-log
```

不要启用多个 worker，不要让两个网关共用同一泰康账号同时处理业务。保持账本目录可写，Java 与网关配置相同 `TK_GATEWAY_TOKEN`。

需要填写的地区参数为：

```dotenv
TK_PROVINCE_CODE=实际省代码
TK_PROVINCE_NAME=实际省名称
TK_CITY_CODE=实际市代码
TK_CITY_NAME=实际市名称
```

旧源码默认是云南/曲靖；新网关要求显式配置，并不会根据车牌或部署城市猜承保地区。填写账号与地区后启用 `TK_LIVE_ENABLED=true`，在管理端“泰康配置”中执行登录检查。需要额外验证时在官方入口完成，不绕过验证。

### 4. 部署两个网页

分别进入 `apps/admin-web` 和 `apps/service-web`，按 `.env.example` 配置导航地址及 API 基址，然后：

```bash
npm ci
npm test
npm run build
```

把各自 `dist/` 目录部署到两个站点，如 `admin.example.com`、`service.example.com`。两个站点的 `/api/` 都反向代理到 Java 18080。报价接口需要较长等待，代理读超时建议250秒，上传限制11MB。

Nginx 的同域 API 配置示例：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_connect_timeout 10s;
    proxy_read_timeout 250s;
    proxy_send_timeout 250s;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_request_buffering off;
    proxy_buffering off;
}
```

证书和域名按你已有服务器管理方式配置。不要将 `services/taikang-gateway`、私有证件目录或数据库端口映射为公共静态资源。前端通过鉴权的 `/api/v1/files/{id}` 下载图片。

## 四、可选 Docker Compose

先完成根目录 `.env` 的配置。在项目根目录执行：

```bash
docker compose --env-file .env -f deploy/compose.yaml up -d --build
```

入口：

- Java：`127.0.0.1:18080`。
- 管理网页：`127.0.0.1:8088`。
- 客服网页：`127.0.0.1:8089`。
- MySQL 和网关只在 Compose 内部网络可达。

由宿主机现有 HTTPS 反向代理转发这些本机地址。Compose 会启动4个服务：MySQL、Java、泰康网关、包含两个站点的 Nginx。数据使用独立卷持久化。

根 `.env` 中的 `VITE_SERVICE_URL` 是管理端跳转客服网页的地址，构建时写入前端；请改成你的客服域名。只在本机试运行 Compose 时可填 `http://localhost:8089`。修改后需重新构建 `web` 服务。

```bash
docker compose --env-file .env -f deploy/compose.yaml logs --tail=100 api
docker compose --env-file .env -f deploy/compose.yaml stop
```

`stop` 不删除数据；不要随意使用带删除数据卷的操作。Compose 文件和镜像构建路径已检查，但当前交付环境未运行 Docker，所以需在你的服务器做最终启动验证。

## 五、微信小程序上线配置

1. 修改 `miniprogram/project.config.json` 的 `appid`。
2. 修改 `config.js`，将 `apiBaseUrl` 指向正式 HTTPS API。
3. 微信后台设置 request、uploadFile、downloadFile 合法域名；本系统三类接口都访问同一 Java 域名。
4. 微信后台配置隐私保护指引，图片与聊天文件选择应与实际调用保持一致。
5. Java 环境填写同一小程序的 `WX_APP_ID`、`WX_APP_SECRET`，由服务端完成 code2session。AppSecret 不得填到小程序代码中。
6. 开发者工具真机调试：微信登录、相册、拍照、微信群图片选择、图片上传/预览、资料确认、人工转接、报价和订单。
7. 创建客服/代理账号及组织，按业务实际配置政策。测试符合预期后，按微信平台流程上传、提交审核和发布。

微信聊天选图指用户主动从微信客户端会话选择图片，不涉及登录用户的企业微信机器人或后台读取群聊天记录。

## 六、数据与异常处理

一起备份 MySQL、私有图片目录、网关账本和两个加密密钥。丢失密钥后无法解密历史资料；更换密钥需要迁移方案，不能简单改变量覆盖。

报价 `OUTCOME_UNKNOWN` 表示请求可能已经到达泰康。客服先核查返回的原单引用；内部人工核查申请不会再次请求保司。不要通过删除记录、清空账本或反复创建新会话来“刷新报价”。

演示数据和正式数据不可混用。正式迁移旧系统历史客户/保单没有自动包含在本项目，需要单独核对字段和归属；本次源码不会改动你的旧系统。

## 七、验收命令

```bash
cd backend
mvn test
```

```bash
cd apps/admin-web
npm ci
npm test
npm run build
```

客服端同上。小程序无 npm 安装步骤：

```bash
node miniprogram/tests/validate.js
node --test miniprogram/tests/logic.test.js
```

泰康网关：

```bash
cd services/taikang-gateway
python -m pytest -q
```

该测试只使用离线样本，不执行真实报价。真正 MySQL JDBC 联调与微信/泰康账号测试应在本节部署完成后执行，验收记录必须区分演示、离线模拟与实际保司结果。

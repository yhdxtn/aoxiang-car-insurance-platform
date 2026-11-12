# 泰康独立报价网关

这是 Java 后端的私有协议适配器，**不连接旧企微系统、旧数据库或旧执行器任务队列**。新系统的用户、资料、会话、订单、政策和权限均由 Java + MySQL 管理。Python 仅复用你提供的泰康协议代码，执行登录检查和家用车报价，并提供可配置的图片识别接口。

## 运行

要求 Python 3.12 或 3.13。Linux、Windows 均可运行；仅启动一个网关进程。

```bash
python3 -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell 使用 .venv\Scripts\Activate.ps1
pip install -r requirements.lock
```

将 `.env.example` 的变量配置为进程环境变量。Python/uvicorn 不自动加载该文件；可使用系统服务 `EnvironmentFile`、Docker Compose `env_file`，或自己导出变量。

```bash
export PYTHONPATH=src
uvicorn tk_gateway.app:create_app --factory --host 127.0.0.1 --port 18081 --workers 1 --no-access-log
```

Windows PowerShell：

```powershell
$env:PYTHONPATH='src'
python -m uvicorn tk_gateway.app:create_app --factory --host 127.0.0.1 --port 18081 --workers 1 --no-access-log
```

`TK_GATEWAY_TOKEN` 应为独立随机密钥，至少32字符。`TK_LEDGER_KEY` 为 base64 编码的32字节随机密钥。根目录的 `scripts/generate-env.py` 可生成整套环境文件。`TK_GATEWAY_TOKEN` 必须与 Java 后端一致，`TK_LEDGER_KEY` 不同于 Java 资料加密密钥。

## 真实业务配置

- `TK_LIVE_ENABLED=true` 后才会进行真实泰康调用。
- `TK_USERNAME`、`TK_PASSWORD` 是你授权的新系统使用的泰康账号。源码中不带真实密码。
- `TK_PROVINCE_CODE/NAME`、`TK_CITY_CODE/NAME` 必须填写实际获准承保地区。适配器不会静默使用旧代码中的“云南/曲靖”默认值。
- 当前只自动处理家用车和“家庭自用”用途。原代码写死小型汽车号牌及 `useNatureCodeCode=8A`，无法据此宣称支持货车；货车、摩托车会转人工，不做错误的家用车映射。
- `COMPULSORY`：交强险；`STANDARD`：交强险＋已选择的三者/驾乘人员责任险/医保外三者责任；`FULL`：在标准方案上增加车损。车船税按保司实际结果展示。
- 未请求的独立驾乘意外险产品不自动捆绑。若保司必须绑定或返回方案与请求不一致，则转人工。
- 每次只提交用户选定的一种方案；不后台偷偷创建三笔报价。

## OCR

配置 `OCR_BASE_URL`（包含 `/v1`）、`OCR_API_KEY` 和 `OCR_MODEL` 后，对接支持图片消息的 OpenAI 兼容接口。只允许 HTTPS；资料只传给你配置的识别服务。

未配置、图片格式错误、无法识别或上游故障时，返回 `MANUAL_REQUIRED`，用户仍可手工填写。识别只提取可读字段，并要求用户核对。此接口不调用泰康 `smartOcr`：旧协议的该步骤要求已创建外部订单，因此新系统不会为了“看一张图”而提前创建保司业务订单。

## 路由与边界

| 路由 | 用途 |
|---|---|
| `GET /health` | 仅返回进程健康状态 |
| `POST /internal/login-check` | 检查当前环境账号登录，不建报价单 |
| `POST /internal/ocr` | 识别图片，失败明确转手填 |
| `POST /internal/quote` | 对已确认资料生成一种报价 |

内部接口均需 `X-Gateway-Token`。网关只部署在本机或私有网络，不应经公网 Nginx 暴露。保留 TLS 校验，不禁用证书验证。

### 幂等与故障

SQLite `request_journal` 是技术去重账本，**不是订单数据库**。请求在外调前持久登记，相同 `requestId` 和内容复用已保存结果，内容变化拒绝。尚未完成的请求在重启后返回 `OUTCOME_UNKNOWN`，不会再次调用保司。进程级文件锁防止同一账本多实例。

结果、原外部单号和必要协议上下文使用 AES-GCM 加密。请求内容只保存 HMAC 指纹，不保存明文姓名证件。请同步备份账本、加密密钥和 Java MySQL 数据，**不要为了重试而删除账本或换请求编号**。若账号配置变化，必须先核查在途请求。

一笔报价总调用期限约150秒，每个外部请求最多连接8秒/读取30秒；最末一步可能略超总期限。Java 等待210秒，小程序等待240秒。超时不自动重报。

`validUntil` 是新平台的15分钟本地确认期限，不是对保险公司锁价的承诺。真实承保、支付、签章及出单仍须人工核实。代码对外主动阻止 `/proposal`、`/pay` 等调用；本期不含自动支付或自动投保。

## 来源与验证

`src/taikang_executor` 为上传的 `泰康报价接口与登录逻辑.zip` 中必要协议模块，按导入依赖收集。原文件未改动，其 SHA256 见 `vendor-provenance.json`。`src/tk_gateway` 为本次新写的独立入口、配置、安全边界和去重账本。原协议中保留的后续投保方法不会通过本服务暴露。

```bash
python -m pytest -q
```

测试全部使用离线对象或模拟 HTTP 响应，不需要真实账号，不向保司下单。测试覆盖去重、重启未知状态、跨进程锁、密钥一致性、接口认证、货车/摩托车拦截、未配置不产生假报价、登录状态校验、车型歧义、原协议险种映射、金额合计及 OCR 输入。

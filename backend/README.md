# 独立泰康小程序后端

Java 21、Spring Boot 3.5.16、Spring JDBC、Flyway，生产使用 MySQL 8.4。小程序、管理端和客服端统一请求 `/api/v1`，不依赖旧企业微信平台、PostgreSQL 或 Windows Connector。

## 本地演示

```bash
mvn test
mvn package
java -jar target/mini-insurance-api-1.0.0.jar --spring.profiles.active=demo
```

端口默认为 `18080`。演示数据库存放 `data/demo.mv.db`，私有图片存放 `data/private-files`。所有演示报价都带 `demo:true`，报价金额为固定样例；演示模式不联系微信或泰康接口，不具备真实识别、投保或支付含义。

| 角色 | 账号 | 演示密码 |
| --- | --- | --- |
| 管理员 | admin | DemoAdmin!2026 |
| 客服 | service | DemoService!2026 |
| 代理 | agent | DemoAgent!2026 |
| 普通用户 | customer | DemoCustomer!2026 |

演示环境和正式环境不能共用数据库。数据库保存环境标识，模式不一致会拒绝启动，防止把演示用户和报价带入生产。

## 正式启动

1. 安装 Java 21、Maven 3.9 和 MySQL 8.4。
2. 创建独立数据库和最小权限的业务数据库账号。Flyway 首次建表需要 DDL 权限，部署迁移后可另用仅 DML 账号运行。
3. 按 `.env.example` 设置环境变量。Spring Boot **不会自动读取 `.env` 文件**；可用操作系统服务环境配置、容器 `env_file`，或受控启动脚本导入。
4. 用 `openssl rand -base64 32` 生成 `DATA_ENCRYPTION_KEY`。此密钥用于数据库资料和图片加密，必须与数据库及文件同时备份，变更密钥前必须迁移历史密文。
5. 首次启动设置 `BOOTSTRAP_ADMIN_PASSWORD`（至少12字符、UTF-8不超过72字节）；系统创建账号 `admin`。后续启动已有管理员时不再创建。不要使用演示密码。
6. 配置小程序 `WX_APP_ID`、`WX_APP_SECRET`；`POST /auth/wechat` 仅接受一次性 code，由服务端调用微信 code2session，不接受客户端自行声明的 OpenID。
7. 配置独立网关 `TK_GATEWAY_URL`、`TK_GATEWAY_TOKEN`，两个服务使用同一个随机内部令牌。网关跨主机访问要求 HTTPS，受信 Docker 服务名 `taikang-gateway` 或本机回环可用 HTTP。
8. 使用 `java -jar target/mini-insurance-api-1.0.0.jar` 正式启动。正式模式不允许 H2 数据库。

```sql
CREATE DATABASE taikang_mini CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'taikang_mini'@'127.0.0.1' IDENTIFIED BY '请替换为随机数据库密码';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON taikang_mini.* TO 'taikang_mini'@'127.0.0.1';
```

配置生产 HTTPS 反向代理，并把小程序后台的 request / uploadFile / downloadFile 合法域名设为实际 API 域名。前端 `Authorization: Bearer <token>` 不能转发到泰康网关或任何第三方。

## 业务规则

- 只支持 `TAIKANG` 渠道。家用车资料确认后可报价，报价失败或要求人工审核时可转客服登记内部人工核查申请（不重新向保司建单）；当前参考协议尚未确认货车吨位等必要映射，货车转人工；摩托车入口直接转人工且不会调用泰康接口。
- 自动报价只处理用户选中的一个方案，不为展示三个按钮而重复建立三笔外部订单。
- 本系统创建的是投保申请。`PENDING_REVIEW → PROCESSING → COMPLETED` 为内部人工处理状态，完成必须由有权限的人员核实并填写保单号；人工订单核价前返回 `totalPremium:null` / `premiumConfirmed:false`，只有管理员或已接入客服可以通过订单状态接口同时录入实际保费（最多2位小数，必须大于0），已核价才纳入保费和佣金估算；未集成自动投保、收款和出单，不以二维码或报价成功冒充付款成功。
- 正式报价前需确认车牌、车架号、发动机号、品牌型号、注册日期、车主、使用性质、座位数、身份证号、地址和手机。OCR结果不直接替代确认动作，用户需保存核对后的资料。
- 已确认的资料变更会失效旧报价；已生成订单的会话资料被冻结。车辆资料、报价版本、订单组织和政策比例保留历史快照。
- 佣金采用可配置百分比，未配置精确下发到该订单所属组织的有效政策时为0，**不会自动继承总部佣金比例**。下级下发必须引用生效日最新适用的上级版本，不能用历史高比例绕过新上限；降低上级比例时必须先处理下级冲突。财务页为申请保费及佣金估算，非支付流水或可提现结算余额。
- 积分支持余额、明细及管理员/财务人工调整（必须提交 `idempotencyKey`，相同调整重试只记一笔；同键不同内容返回409），不自动推断奖励比例，也不实现未确认商品和兑换规则。

## 权限及资料

- `ADMIN` 查看与管理全局；`FINANCE` 只访问财务和相关只读业务，不能查看证件图片或客服会话；`AGENT` 查看自身及下级组织业务；`CUSTOMER` 仅本人；`SERVICE` 仅其组织范围内待领取或已分配给自己的会话。
- 客服需先领取会话才能修改资料和发送客服消息，另一客服不能抢占；转接目标必须有该组织权限。
- 更改用户角色、归属或停用账号会撤销其登录 token；历史订单仍保留原归属。停用组织会阻止该组织及其下级账号登录。
- 密码使用 BCrypt，token 仅保存 SHA-256 哈希，默认12小时失效；修改密码撤销全部旧 token。
- 车辆个人资料、客户资料、消息正文和订单备注以 AES-256-GCM 加密保存；图片也加密保存，不提供公开静态图片目录。下载仍校验会话权限。
- 上传限制10MB，并校验 JPEG、PNG、WEBP 文件头；后端生成随机存储路径，不接受客户端远程文件地址。
- 关键变更写审计；审计只保存业务动作和记录ID，不保存证件明文、密码或第三方异常正文。

## 重复提交与不确定结果

报价请求以 `(sessionId, idempotencyKey)` 唯一约束去重，消息也有幂等键，订单一个会话只能生成一笔。提交报价前先持久化 `PROCESSING`，然后释放数据库事务等待网关；不在长网络调用时持有数据库锁。

网关超时、连接中断或无法确认外部写入结果时写 `OUTCOME_UNKNOWN` 并转人工；同一会话的新报价请求会被阻止。进程重启后遗留 `PROCESSING` 超过300秒，下一次读取或提交时转为 `OUTCOME_UNKNOWN`，不会自动重放。在客服端根据 `supplierOrderId`、`supplierQuoteRef` 核查泰康原记录；当前版本不提供无证据地重置未知状态的按钮。

## 测试

`mvn test` 默认使用 H2 MySQL兼容模式，仅用于快速应用集成测试，包括：角色越权、数据隔离、报价/消息/订单幂等、旧报价失效、私有文件权限及加密、客服抢占、政策约束、积分扣减、订单流转和中断恢复。H2测试不替代正式MySQL验证。

真实MySQL执行相同迁移及业务回归时，可使用独立数据库并将测试配置覆盖为：

```bash
mvn test \
  -Dspring.datasource.url='jdbc:mysql://127.0.0.1:3306/taikang_test?serverTimezone=UTC' \
  -Dspring.datasource.username=taikang_test \
  -Dspring.datasource.password='本地测试库密码'
```

此测试使用明确的演示模式和隔离数据库，仍不会调用真实保司。不要对现有生产数据库运行这些集成测试。

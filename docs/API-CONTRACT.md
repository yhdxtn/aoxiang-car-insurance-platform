# 四端共用 API 合同 v1

独立新系统，Java 21 / Spring Boot 3.5.x + MySQL 8.4，微信原生小程序，两个独立 Vue 3 Web 应用。所有前端只访问 Java `/api/v1`。身份来自 Bearer token；不从请求体接受角色或订单归属。成功响应直接 JSON（无 data 包装）；错误 `{code,message,fieldErrors?,traceId?}`。列表 `{items:[],total:0,page:1,size:20}`。ID 为字符串 UUID，金额为人民币元的十进制字符串。日期 ISO，角色 `ADMIN,FINANCE,AGENT,CUSTOMER,SERVICE`；车辆类型 `CAR,TRUCK,MOTORCYCLE`；渠道固定 `TAIKANG`。

## 认证
- `GET /public/config` -> `{mode:'demo'|'live',insurer:'TAIKANG',allowDemoLogin:boolean}`
- `POST /auth/login` `{username,password}` -> `{token,user:{id,name,role,orgId,orgName,points},mode}`
- `POST /auth/wechat` `{code,inviteCode?}` -> 同上，仅服务端 code2session；真实模式不能接受客户端 openid。
- `GET /auth/me` -> user；`POST /auth/logout` -> `{ok:true}`
- `PUT /auth/password` `{oldPassword,newPassword}` -> `{ok:true}`
- demo profile 初始账号 `admin / DemoAdmin!2026`, `service / DemoService!2026`, `agent / DemoAgent!2026`, `customer / DemoCustomer!2026`；仅 demo 可用，不允许 live 复用。

## 小程序及客服共同流程
- `POST /sessions` `{vehicleType}` -> session。摩托车立即 `WAITING` 人工；其他 `BOT`。
- `GET /sessions?status=&page=&size=` -> 分页 session（用户本人、客服授权、代理组织范围）
- `GET /sessions/{id}` -> `{id,vehicleType,status,stage(数字1/2/3),ownerId,ownerName,assignedTo,vehicle:{},quotes:[],orderId,createdAt}`
- `GET /sessions/{id}/messages?after=0` -> `{items:[{id,seq,role:'USER'|'ASSISTANT'|'SERVICE'|'SYSTEM',content,fileId?,fileName?,createdAt}],cursor}`
- `POST /sessions/{id}/messages` `{content,clientMessageId,fileId?}` -> message；用户消息只写 USER，客服 SERVICE。
- `POST /sessions/{id}/handoff` `{reason}` -> session
- `POST /sessions/{id}/claim` -> session；客服领取且不可抢占
- `POST /sessions/{id}/transfer` `{serviceUserId}` -> session；当前客服或 ADMIN
- `POST /sessions/{id}/close` -> session；人工状态 CLOSED，关闭不抹除资料
- `PUT /sessions/{id}/vehicle` vehicle -> session；修改使旧报价失效
- vehicle 字段 `{plateNo,vin,engineNo,brandModel,registerDate,issueDate,ownerName,idNumber,address,phone,vehicleType,useNature,seatCount,selectedModelCode?}`；中文描述 useNature 默认为家庭自用，货车需要确认使用性质；后端校验必填/格式；数字 seatCount。
- `POST /sessions/{id}/files` multipart `file`, `documentType` (`DRIVING_LICENSE,ID_CARD,OTHER`), `source` (`ALBUM,CHAT,CAMERA,WEB`) -> `{id,fileName,mimeType,size}`；10MB JPEG/PNG/WEBP，有文件头校验。
- `GET /files/{id}` -> 授权后的原始图片；禁止公开静态目录，前端用授权下载或 blob；上传字段不可包含任意远程 URL。
- `POST /sessions/{id}/ocr` `{fileId}` -> `{status:'RECOGNIZED'|'MANUAL_REQUIRED',vehicle:{},message}`；无法识别清晰要求人工，不得假造 OCR。
- `POST /sessions/{id}/quotes` `{plan:'COMPULSORY'|'STANDARD'|'FULL',thirdPartyAmount:'2000000',driverAmount:'10000',passengerAmount:'10000',medicalAmount:'200000',idempotencyKey}` -> quote `{id,sessionId,insurer:'TAIKANG',plan,status:'QUOTED'|'MANUAL_REQUIRED'|'FAILED'|'OUTCOME_UNKNOWN',totalPremium,commercialPremium,compulsoryPremium,vehicleTax,coverages:[{name,amount,premium}],demo,validUntil,message,revision}`。只生成选定方案，不偷偷三次外部建单；不可用货车转人工，不切保司。新 quote 失效旧版本。
- `POST /sessions/{id}/orders` `{quoteId,idempotencyKey,confirmed:true}` -> order。创建本平台投保申请，状态 `PENDING_REVIEW`，不代表已支付/出单；所有车型在 WAITING/ACTIVE 人工会话中可由 ADMIN/已领取 SERVICE 不带 quoteId 登记人工申请；PROCESSING 时拒绝，UNKNOWN 仅登记原单核查，不外调或重报。

## 订单/客户
- `GET /orders?search=&status=&page=&size=` -> `{items,total,page,size}`，搜索订单号/车牌/姓名/VIN/保单号。
- `GET /orders/{id}` -> `{id,orderNo,sessionId,ownerId,customerName,phone,plateNo,vin,vehicleType,insurer,status,totalPremium,quoteId,policyNo,createdAt,history:[],demo}`
- `PATCH /orders/{id}/status` `{status,note,policyNo?,totalPremium?}` -> order；人工内部跟进仅 `PENDING_REVIEW -> PROCESSING -> COMPLETED` 或 CANCELLED，COMPLETED 必须有核实后录入保单号（不伪称接口出单）。人工订单 `premiumConfirmed=false` 时 `totalPremium=null`；仅 ADMIN/已授权 SERVICE 可录入人工核实保费，完成前必须核价；自动报价金额不可人工覆盖。
- `GET /customers?search=&page=&size=` -> page；`POST /customers`、`PUT /customers/{id}` `{name,phone,notes}` -> customer，严格角色与组织范围。

## 管理/我的
- `GET /dashboard` -> `{orders,customers,pendingSessions,premium,completedOrders}`
- `GET /organizations` -> `{items:[{id,name,parentId,level,enabled}]}`；`POST /organizations` `{name,parentId}`，`PATCH /organizations/{id}` `{name?,enabled?}`。总部可全局；代理仅创建自己直接子级。
- `GET /users?role=&page=&size=` -> page；`POST /users` `{username,password,name,role,orgId}`，`PATCH /users/{id}` `{name?,enabled?,role?,orgId?}`；ADMIN 管理角色，代理仅创建授权下级 AGENT；组织变更不重写历史订单归属。
- `GET /policies?history=false` -> `{items:[{id,title,content,orgId,parentPolicyId,version,rate,enabled,effectiveFrom,effectiveTo,vehicleType}]}`
- `POST /policies` `{title,content,orgId,parentPolicyId?,rate,effectiveFrom,effectiveTo?,vehicleType}` -> policy。上级政策归属/有效期/车种匹配并限制子级 rate <= parent rate，政策不可原地覆盖，创建新版本。rate 为百分比，不默认写入讨论数字。
- `GET /finance` -> `{premium,estimatedCommission,items:[{orderNo,orgName,totalPremium,rate,commission,status}]}`。仅 ADMIN/FINANCE/AGENT，按订单冻结政策统计；没有政策则0；非真实付款结算系统。
- `GET /points` -> `{balance,items:[{id,delta,reason,createdAt}]}` 当前本人；`POST /points/adjust` `{userId,delta,reason,idempotencyKey}` 仅 ADMIN/FINANCE，有审计，不自动按猜测规则赠送。
- `GET /audit?page=&size=` -> page，只 ADMIN；敏感字段不进入日志。
- `GET /settings/taikang` -> `{enabled,mode,gatewayConfigured,accountMasked,loginStatus,message}`，不返回密码。
- `POST /settings/taikang/check` -> `{status,message}`；ADMIN 触发配置环境中的泰康账号真实登录检查。
- `GET /service/agents` -> `{items:[{id,name}]}` 客服转接列表。

## 内部泰康网关（root负责实现）
Java 使用 `TK_GATEWAY_URL` 和 `TK_GATEWAY_TOKEN`，header `X-Gateway-Token`。Python 网关复用上传包 client/staged_client 的原协议，独立单实例账户串行，凭据来自环境，TLS 校验开启；不需要旧系统 Java、企微或 PostgreSQL。
- `POST /internal/login-check` `{}` -> `{status:'ONLINE'|'VERIFICATION_REQUIRED'|'ERROR',message}`
- `POST /internal/ocr` `{imageBase64,mimeType,documentType}` -> `{status,vehicle,message}`
- `POST /internal/quote` `{requestId,vehicleType,vehicle,plan,thirdPartyAmount,driverAmount,passengerAmount,medicalAmount}` -> 上述 quote 不含 Java id；`requestId` 持久化去重，含结果未知保护。网关不调用投保或支付接口。
- 请求超时、网关业务写入结果不明 -> OUTCOME_UNKNOWN，转人工核查，不自动重试制造新外部订单。

## 实现要求
真实模式缺少微信/泰康配置要明确报配置错误，不降级为 demo。demo 前后端始终显示“演示数据”，禁止与真实订单混用。前端提供加载/错误/空状态，不把按钮写成无后端的占位。所有重复写入均使用唯一键或行锁保证幂等。Web 轮询只在活动客服会话可见时有界进行，页面离开/隐藏清除。原需求模糊的佣金/积分兑换规则不伪造落地；积分明细和人工调整已覆盖，商城兑换为后续规则确认项。

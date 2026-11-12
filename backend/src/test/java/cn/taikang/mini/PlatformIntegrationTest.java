package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestExecutionListeners;
import org.springframework.test.web.servlet.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@TestExecutionListeners(
    listeners = {
      org.springframework.test.context.web.ServletTestExecutionListener.class,
      org.springframework.test.context.support.DependencyInjectionTestExecutionListener.class
    },
    mergeMode = TestExecutionListeners.MergeMode.REPLACE_DEFAULTS)
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class PlatformIntegrationTest {
  @Autowired MockMvc mvc;
  @Autowired ObjectMapper json;
  @Autowired Store db;
  @Autowired AppConfig config;
  String admin, customer, agent, service, other, service2;
  String adminId, customerId, rootOrg, agentOrg, otherId;

  @BeforeAll
  void setup() throws Exception {
    Map<String, Object> a = login("admin", "DemoAdmin!2026"),
        c = login("customer", "DemoCustomer!2026"),
        g = login("agent", "DemoAgent!2026");
    admin = str(a, "token");
    customer = str(c, "token");
    agent = str(g, "token");
    service = str(login("service", "DemoService!2026"), "token");
    Map<String, Object> au = (Map<String, Object>) a.get("user"),
        cu = (Map<String, Object>) c.get("user"),
        gu = (Map<String, Object>) g.get("user");
    rootOrg = str(au, "orgId");
    agentOrg = str(gu, "orgId");
    adminId = str(au, "id");
    customerId = str(cu, "id");
    Map<String, Object> u =
        postJson(
            "/users",
            admin,
            map(
                "username",
                "other",
                "password",
                "OtherCustomer!2026",
                "name",
                "另一用户",
                "role",
                "CUSTOMER",
                "orgId",
                rootOrg),
            200);
    otherId = str(u, "id");
    other = str(login("other", "OtherCustomer!2026"), "token");
    postJson(
        "/users",
        admin,
        map(
            "username",
            "service2",
            "password",
            "SecondService!2026",
            "name",
            "第二客服",
            "role",
            "SERVICE",
            "orgId",
            rootOrg),
        200);
    service2 = str(login("service2", "SecondService!2026"), "token");
  }

  Map<String, Object> login(String u, String p) throws Exception {
    return postJson("/auth/login", null, map("username", u, "password", p), 200);
  }

  Map<String, Object> parse(MvcResult result) throws Exception {
    return json.readValue(
        result.getResponse().getContentAsByteArray(),
        new TypeReference<LinkedHashMap<String, Object>>() {});
  }

  Map<String, Object> postJson(String path, String token, Object body, int status)
      throws Exception {
    return request("POST", path, token, body, status);
  }

  Map<String, Object> request(String method, String path, String token, Object body, int status)
      throws Exception {
    var builder =
        switch (method) {
          case "GET" -> get("/api/v1" + path);
          case "PUT" -> put("/api/v1" + path);
          case "PATCH" -> patch("/api/v1" + path);
          default -> post("/api/v1" + path);
        };
    if (token != null) builder.header("Authorization", "Bearer " + token);
    if (body != null) builder.contentType("application/json").content(json.writeValueAsBytes(body));
    return parse(mvc.perform(builder).andExpect(status().is(status)).andReturn());
  }

  String session(String token, String type) throws Exception {
    return str(postJson("/sessions", token, map("vehicleType", type), 200), "id");
  }

  Map<String, Object> vehicle() {
    return map(
        "plateNo",
        "云A12345",
        "vin",
        "LHGCM82633A123456",
        "engineNo",
        "ENG2026001",
        "brandModel",
        "演示车辆型号",
        "ownerName",
        "测试车主",
        "registerDate",
        "2020-01-01",
        "issueDate",
        "2020-01-01",
        "useNature",
        "家庭自用",
        "seatCount",
        5,
        "phone",
        "13800000000",
        "idNumber",
        "530102199001010011",
        "address",
        "云南省昆明市测试地址",
        "vehicleType",
        "CAR");
  }

  Map<String, Object> quote(String sid, String token) throws Exception {
    request("PUT", "/sessions/" + sid + "/vehicle", token, vehicle(), 200);
    return postJson(
        "/sessions/" + sid + "/quotes", token, map("plan", "FULL", "idempotencyKey", id()), 200);
  }

  @Test
  void authenticationAndModeAreExplicit() throws Exception {
    request("GET", "/auth/me", null, null, 401);
    Map<String, Object> c = request("GET", "/public/config", null, null, 200);
    assertEquals("demo", c.get("mode"));
    assertEquals(true, c.get("allowDemoLogin"));
    postJson("/auth/login", null, map("username", "admin", "password", "incorrect-password"), 401);
    postJson("/auth/wechat", null, map("code", "fake-client-code", "openid", "spoofed"), 503);
    assertNotNull(
        db.maybe("SELECT token_hash FROM auth_tokens WHERE token_hash=?", Crypto.hash(admin)));
    assertNull(db.maybe("SELECT token_hash FROM auth_tokens WHERE token_hash=?", admin));
  }

  @Test
  void quotationOrderIsIdempotentAndSnapshotFrozen() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    assertEquals("QUOTED", q.get("status"));
    assertEquals(true, q.get("demo"));
    assertEquals("3796.50", q.get("totalPremium"));
    Map<String, Object> o =
        postJson(
            "/sessions/" + sid + "/orders",
            customer,
            map("quoteId", q.get("id"), "idempotencyKey", "order-key-1", "confirmed", true),
            200);
    Map<String, Object> repeated =
        postJson(
            "/sessions/" + sid + "/orders",
            customer,
            map("quoteId", q.get("id"), "idempotencyKey", "order-key-1", "confirmed", true),
            200);
    assertEquals(o.get("id"), repeated.get("id"));
    assertEquals("PENDING_REVIEW", o.get("status"));
    request("PUT", "/sessions/" + sid + "/vehicle", customer, vehicle(), 409);
    request("GET", "/orders/" + o.get("id"), other, null, 404);
    assertEquals(1, db.rows("SELECT * FROM insurance_orders WHERE session_id=?", sid).size());
    assertFalse(
        String.valueOf(
                db.one("SELECT * FROM insurance_orders WHERE id=?", o.get("id"))
                    .get("vehicle_data"))
            .contains("测试车主"));
  }

  @Test
  void oldQuoteCannotBeUsedAfterVehicleEdit() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    Map<String, Object> v = vehicle();
    v.put("plateNo", "云A54321");
    request("PUT", "/sessions/" + sid + "/vehicle", customer, v, 200);
    postJson(
        "/sessions/" + sid + "/orders",
        customer,
        map("quoteId", q.get("id"), "idempotencyKey", id(), "confirmed", true),
        409);
  }

  @Test
  void idempotencyKeysCannotChangeCoverage() throws Exception {
    String sid = session(customer, "CAR");
    request("PUT", "/sessions/" + sid + "/vehicle", customer, vehicle(), 200);
    String key = id();
    Map<String, Object> first =
        postJson(
            "/sessions/" + sid + "/quotes",
            customer,
            map("plan", "FULL", "idempotencyKey", key),
            200);
    Map<String, Object> second =
        postJson(
            "/sessions/" + sid + "/quotes",
            customer,
            map("plan", "FULL", "idempotencyKey", key),
            200);
    assertEquals(first.get("id"), second.get("id"));
    postJson(
        "/sessions/" + sid + "/quotes",
        customer,
        map("plan", "STANDARD", "idempotencyKey", key),
        409);
    assertEquals(1, db.rows("SELECT * FROM quotes WHERE session_id=?", sid).size());
  }

  @Test
  void ordinaryUserCannotEscalateAndCannotReadAnotherSession() throws Exception {
    String sid = session(customer, "CAR");
    request("GET", "/sessions/" + sid, other, null, 404);
    request("GET", "/sessions/" + sid + "/messages", other, null, 404);
    postJson(
        "/users",
        customer,
        map(
            "username",
            "evil",
            "password",
            "LongPassword!2026",
            "name",
            "bad",
            "role",
            "ADMIN",
            "orgId",
            rootOrg),
        403);
    postJson("/policies", customer, map(), 403);
    request("GET", "/finance", customer, null, 403);
    request("GET", "/audit", customer, null, 403);
    request("GET", "/settings/taikang", customer, null, 403);
  }

  @Test
  void motorcyclesAlwaysRouteToManual() throws Exception {
    String sid = session(customer, "MOTORCYCLE");
    Map<String, Object> s = request("GET", "/sessions/" + sid, customer, null, 200);
    assertEquals("WAITING", s.get("status"));
    Map<String, Object> q =
        postJson(
            "/sessions/" + sid + "/quotes",
            customer,
            map("plan", "COMPULSORY", "idempotencyKey", id()),
            200);
    assertEquals("MANUAL_REQUIRED", q.get("status"));
    assertFalse(q.containsKey("totalPremium"));
    postJson(
        "/sessions/" + sid + "/orders",
        customer,
        map("idempotencyKey", id(), "confirmed", true),
        403);
  }

  @Test
  void messagesAreDeduplicatedAndRoleCannotBeSpoofed() throws Exception {
    String sid = session(customer, "CAR"), key = id();
    Map<String, Object> m =
        postJson(
            "/sessions/" + sid + "/messages",
            customer,
            map("content", "测试消息", "clientMessageId", key, "role", "SERVICE"),
            200);
    assertEquals("USER", m.get("role"));
    Map<String, Object> duplicate =
        postJson(
            "/sessions/" + sid + "/messages",
            customer,
            map("content", "测试消息", "clientMessageId", key),
            200);
    assertEquals(m.get("id"), duplicate.get("id"));
    postJson(
        "/sessions/" + sid + "/messages",
        customer,
        map("content", "different", "clientMessageId", key),
        409);
  }

  @Test
  void privateFilesHaveContentChecksOwnershipAndEncryption() throws Exception {
    String sid = session(customer, "CAR");
    MockMultipartFile bad =
        new MockMultipartFile("file", "bad.png", "image/png", "<script>bad</script>".getBytes());
    mvc.perform(
            multipart("/api/v1/sessions/" + sid + "/files")
                .file(bad)
                .header("Authorization", "Bearer " + customer))
        .andExpect(status().isBadRequest());
    byte[] png =
        Base64.getDecoder()
            .decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=");
    MockMultipartFile image = new MockMultipartFile("file", "license.png", "image/png", png);
    Map<String, Object> f =
        parse(
            mvc.perform(
                    multipart("/api/v1/sessions/" + sid + "/files")
                        .file(image)
                        .param("documentType", "DRIVING_LICENSE")
                        .param("source", "CHAT")
                        .header("Authorization", "Bearer " + customer))
                .andExpect(status().isOk())
                .andReturn());
    String fid = str(f, "id");
    mvc.perform(get("/api/v1/files/" + fid).header("Authorization", "Bearer " + customer))
        .andExpect(status().isOk())
        .andExpect(content().bytes(png));
    request("GET", "/files/" + fid, other, null, 404);
    request("GET", "/files/" + fid, null, null, 401);
    assertFalse(
        Arrays.equals(png, Files.readAllBytes(Path.of(config.uploadDir()).resolve(fid + ".enc"))));
    String otherSession = session(other, "CAR");
    postJson(
        "/sessions/" + otherSession + "/messages",
        other,
        map("content", "borrow", "fileId", fid, "clientMessageId", id()),
        400);
  }

  @Test
  void customerMustBeClaimedBeforeServiceMutationAndSecondServiceCannotSteal() throws Exception {
    String sid = session(customer, "MOTORCYCLE");
    postJson(
        "/sessions/" + sid + "/messages",
        service,
        map("content", "你好", "clientMessageId", id()),
        409);
    postJson("/sessions/" + sid + "/claim", service, map(), 200);
    postJson("/sessions/" + sid + "/claim", service2, map(), 404);
    postJson(
        "/sessions/" + sid + "/messages",
        service2,
        map("content", "抢单", "clientMessageId", id()),
        404);
    Map<String, Object> services = request("GET", "/service/agents", service, null, 200);
    String second =
        ((List<Map<String, Object>>) services.get("items"))
            .stream()
                .filter(x -> "第二客服".equals(x.get("name")))
                .findFirst()
                .orElseThrow()
                .get("id")
                .toString();
    postJson("/sessions/" + sid + "/transfer", service, map("serviceUserId", second), 200);
    postJson(
        "/sessions/" + sid + "/messages",
        service,
        map("content", "旧客服", "clientMessageId", id()),
        404);
    postJson(
        "/sessions/" + sid + "/messages",
        service2,
        map("content", "接入", "clientMessageId", id()),
        200);
  }

  @Test
  void policyInheritanceRejectsUnauthorizedRateAndPreservesVersions() throws Exception {
    Map<String, Object> root =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "总部测试政策",
                "content",
                "测试政策内容",
                "orgId",
                rootOrg,
                "vehicleType",
                "TRUCK",
                "rate",
                "10",
                "effectiveFrom",
                "2020-01-01"),
            200);
    postJson(
        "/policies",
        admin,
        map(
            "title",
            "越界",
            "content",
            "越界政策",
            "orgId",
            agentOrg,
            "vehicleType",
            "TRUCK",
            "rate",
            "11",
            "parentPolicyId",
            root.get("id"),
            "effectiveFrom",
            "2020-01-01"),
        400);
    Map<String, Object> child =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "团队政策",
                "content",
                "团队内容",
                "orgId",
                agentOrg,
                "vehicleType",
                "TRUCK",
                "rate",
                "6",
                "parentPolicyId",
                root.get("id"),
                "effectiveFrom",
                "2020-01-01"),
            200);
    assertEquals("6.0000", child.get("rate"));
    Map<String, Object> later =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "团队第二版",
                "content",
                "新内容",
                "orgId",
                agentOrg,
                "vehicleType",
                "TRUCK",
                "rate",
                "5",
                "parentPolicyId",
                root.get("id"),
                "effectiveFrom",
                "2020-01-01"),
            200);
    assertEquals(2, ((Number) later.get("version")).intValue());
    assertNotNull(db.maybe("SELECT * FROM policies WHERE id=?", child.get("id")));
    postJson(
        "/policies",
        agent,
        map(
            "title",
            "擅改自己授权",
            "content",
            "wrong",
            "orgId",
            agentOrg,
            "vehicleType",
            "TRUCK",
            "rate",
            "1",
            "parentPolicyId",
            root.get("id"),
            "effectiveFrom",
            "2020-01-01"),
        403);
  }

  @Test
  void frozenPolicyCommissionDoesNotChangeWithNewPolicy() throws Exception {
    Map<String, Object> p =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "总部车险政策",
                "content",
                "车险政策内容",
                "orgId",
                rootOrg,
                "vehicleType",
                "CAR",
                "rate",
                "4",
                "effectiveFrom",
                "2020-01-01"),
            200);
    String sid = session(other, "CAR");
    Map<String, Object> q = quote(sid, other);
    Map<String, Object> o =
        postJson(
            "/sessions/" + sid + "/orders",
            other,
            map("quoteId", q.get("id"), "idempotencyKey", id(), "confirmed", true),
            200);
    postJson(
        "/policies",
        admin,
        map(
            "title",
            "总部新版车险政策",
            "content",
            "新版本",
            "orgId",
            rootOrg,
            "vehicleType",
            "CAR",
            "rate",
            "1",
            "effectiveFrom",
            "2020-01-01"),
        200);
    Map<String, Object> stored = db.one("SELECT * FROM insurance_orders WHERE id=?", o.get("id"));
    assertEquals(p.get("id"), stored.get("policy_id"));
    assertEquals("4.0000", stored.get("commission_rate").toString());
  }

  @Test
  void pointsCannotOverdrawAndAuditContainsNoDocuments() throws Exception {
    postJson(
        "/points/adjust",
        customer,
        map("userId", customerId, "delta", 50, "reason", "bad", "idempotencyKey", id()),
        403);
    postJson(
        "/points/adjust",
        admin,
        map(
            "userId",
            customerId,
            "delta",
            100,
            "reason",
            "测试奖励",
            "idempotencyKey",
            "test-point-award"),
        200);
    postJson(
        "/points/adjust",
        admin,
        map("userId", customerId, "delta", -101, "reason", "不能超扣", "idempotencyKey", id()),
        400);
    postJson(
        "/points/adjust",
        admin,
        map(
            "userId",
            customerId,
            "delta",
            100,
            "reason",
            "测试奖励",
            "idempotencyKey",
            "test-point-award"),
        200);
    Map<String, Object> points = request("GET", "/points", customer, null, 200);
    assertEquals(100, ((Number) points.get("balance")).intValue());
    assertTrue(
        db.rows("SELECT * FROM audit_logs").stream()
            .noneMatch(x -> str(x, "summary").contains("530102199001010011")));
  }

  @Test
  void orderStatusRequiresValidSequenceAndVerifiedPolicyNumber() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    Map<String, Object> o =
        postJson(
            "/sessions/" + sid + "/orders",
            customer,
            map("quoteId", q.get("id"), "idempotencyKey", id(), "confirmed", true),
            200);
    String endpoint = "/orders/" + o.get("id") + "/status";
    request("PATCH", endpoint, customer, map("status", "PROCESSING", "note", "越权"), 403);
    request(
        "PATCH",
        endpoint,
        admin,
        map("status", "COMPLETED", "note", "跳状态", "policyNo", "test-policy"),
        409);
    request("PATCH", endpoint, admin, map("status", "PROCESSING", "note", "客服已接手"), 200);
    request("PATCH", endpoint, admin, map("status", "COMPLETED", "note", "缺保单号"), 400);
    request(
        "PATCH",
        endpoint,
        admin,
        map("status", "COMPLETED", "note", "演示人工核实完成", "policyNo", "DEMO-POLICY-001"),
        200);
  }

  @Test
  void interruptedQuoteIsDurablyUnknownAndNeverAutomaticallyReplayed() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    db.update(
        "UPDATE quotes SET status='PROCESSING',deadline_at=? WHERE id=?",
        Store.timestamp(Instant.now().minusSeconds(1)),
        q.get("id"));
    Map<String, Object> s = request("GET", "/sessions/" + sid, customer, null, 200);
    assertEquals("WAITING", s.get("status"));
    assertEquals(
        "OUTCOME_UNKNOWN", db.one("SELECT * FROM quotes WHERE id=?", q.get("id")).get("status"));
    postJson(
        "/sessions/" + sid + "/quotes", customer, map("plan", "FULL", "idempotencyKey", id()), 409);
    assertEquals(1, db.rows("SELECT * FROM quotes WHERE session_id=?", sid).size());
  }

  @Test
  void agentCannotReadSiblingOrCreateHeadquartersAdministrator() throws Exception {
    String sid = session(other, "CAR");
    request("GET", "/sessions/" + sid, agent, null, 404);
    postJson(
        "/users",
        agent,
        map(
            "username",
            "fake-admin",
            "password",
            "LongPassword!2026",
            "name",
            "bad",
            "role",
            "ADMIN",
            "orgId",
            agentOrg),
        403);
    postJson("/organizations", agent, map("name", "越权组织", "parentId", rootOrg), 403);
  }

  @Test
  void concurrentOrderSubmissionCreatesOneRow() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    String key = id();
    ExecutorService pool = Executors.newFixedThreadPool(2);
    try {
      Callable<String> task =
          () ->
              str(
                  postJson(
                      "/sessions/" + sid + "/orders",
                      customer,
                      map("quoteId", q.get("id"), "idempotencyKey", key, "confirmed", true),
                      200),
                  "id");
      List<Future<String>> results = pool.invokeAll(List.of(task, task));
      assertEquals(results.get(0).get(), results.get(1).get());
      assertEquals(1, db.rows("SELECT * FROM insurance_orders WHERE session_id=?", sid).size());
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void concurrentPointAdjustmentIsAppliedExactlyOnce() throws Exception {
    String key = id();
    long before = number(db.one("SELECT points FROM users WHERE id=?", otherId).get("points"));
    ExecutorService pool = Executors.newFixedThreadPool(2);
    try {
      Callable<String> task =
          () ->
              str(
                  postJson(
                      "/points/adjust",
                      admin,
                      map(
                          "userId",
                          otherId,
                          "delta",
                          25,
                          "reason",
                          "并发幂等测试",
                          "idempotencyKey",
                          key),
                      200),
                  "id");
      List<Future<String>> results = pool.invokeAll(List.of(task, task));
      assertEquals(results.get(0).get(), results.get(1).get());
      assertEquals(
          before + 25,
          number(db.one("SELECT points FROM users WHERE id=?", otherId).get("points")));
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void agentWithoutExplicitPolicyDoesNotInheritHeadquartersCommission() throws Exception {
    Map<String, Object> org =
        postJson("/organizations", admin, map("name", "未授权佣金团队", "parentId", rootOrg), 200);
    Map<String, Object> u =
        postJson(
            "/users",
            admin,
            map(
                "username",
                "no-policy-agent",
                "password",
                "LongPassword!2026",
                "name",
                "待授权代理",
                "role",
                "AGENT",
                "orgId",
                org.get("id")),
            200);
    String token = str(login("no-policy-agent", "LongPassword!2026"), "token");
    String sid = session(token, "CAR");
    Map<String, Object> q = quote(sid, token);
    Map<String, Object> o =
        postJson(
            "/sessions/" + sid + "/orders",
            token,
            map("quoteId", q.get("id"), "idempotencyKey", id(), "confirmed", true),
            200);
    Map<String, Object> stored = db.one("SELECT * FROM insurance_orders WHERE id=?", o.get("id"));
    assertNull(stored.get("policy_id"));
    assertEquals("0.0000", stored.get("commission_rate").toString());
  }

  @Test
  void financeHasReadOnlyBusinessAccessWithoutDocuments() throws Exception {
    postJson(
        "/users",
        admin,
        map(
            "username",
            "finance-test",
            "password",
            "FinancePassword!2026",
            "name",
            "测试财务",
            "role",
            "FINANCE",
            "orgId",
            rootOrg),
        200);
    String token = str(login("finance-test", "FinancePassword!2026"), "token");
    request("GET", "/finance", token, null, 200);
    request("GET", "/users", token, null, 200);
    request("GET", "/organizations", token, null, 200);
    request("GET", "/sessions", token, null, 403);
    request("GET", "/customers", token, null, 403);
    postJson("/organizations", token, map("name", "越权", "parentId", rootOrg), 403);
    postJson("/settings/taikang/check", token, map(), 403);
  }

  @Test
  void bcryptRejectsPasswordsBeyond72Utf8Bytes() throws Exception {
    postJson("/auth/login", null, map("username", "admin", "password", "中".repeat(30)), 401);
    postJson(
        "/users",
        admin,
        map(
            "username",
            "long-password-user",
            "password",
            "中".repeat(30),
            "name",
            "测试",
            "role",
            "CUSTOMER",
            "orgId",
            rootOrg),
        400);
  }

  @Test
  void manualOrdersRequireVerifiedPremiumBeforeCompletion() throws Exception {
    String sid = session(customer, "MOTORCYCLE");
    request(
        "PUT",
        "/sessions/" + sid + "/vehicle",
        customer,
        map("ownerName", "摩托测试车主", "phone", "13800000001", "vehicleType", "MOTORCYCLE"),
        200);
    postJson("/sessions/" + sid + "/claim", service, map(), 200);
    Map<String, Object> order =
        postJson(
            "/sessions/" + sid + "/orders",
            service,
            map("confirmed", true, "idempotencyKey", id()),
            200);
    assertEquals(false, order.get("premiumConfirmed"));
    assertNull(order.get("totalPremium"));
    String endpoint = "/orders/" + order.get("id") + "/status";
    request("PATCH", endpoint, service, map("status", "PROCESSING", "note", "人工跟进"), 200);
    request(
        "PATCH",
        endpoint,
        service,
        map("status", "COMPLETED", "policyNo", "TEST-MANUAL-POLICY", "note", "未核价"),
        400);
    request(
        "PATCH",
        endpoint,
        service,
        map("status", "PROCESSING", "totalPremium", "0", "note", "无效核价"),
        400);
    Map<String, Object> priced =
        request(
            "PATCH",
            endpoint,
            service,
            map("status", "PROCESSING", "totalPremium", "355.50", "note", "已核实承保资料"),
            200);
    assertEquals(true, priced.get("premiumConfirmed"));
    assertEquals("355.50", priced.get("totalPremium"));
    request(
        "PATCH",
        endpoint,
        service,
        map("status", "COMPLETED", "policyNo", "TEST-MANUAL-POLICY", "note", "人工核验保单完成"),
        200);
  }

  @Test
  void automaticQuotedPremiumCannotBeOverwritten() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    Map<String, Object> order =
        postJson(
            "/sessions/" + sid + "/orders",
            customer,
            map("confirmed", true, "quoteId", q.get("id"), "idempotencyKey", id()),
            200);
    request(
        "PATCH",
        "/orders/" + order.get("id") + "/status",
        admin,
        map("status", "PROCESSING", "totalPremium", "1.00", "note", "不能改自动价"),
        400);
  }

  @Test
  void processingQuotePreventsClosingSession() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    db.update(
        "UPDATE quotes SET status='PROCESSING',deadline_at=? WHERE id=?",
        Store.timestamp(Instant.now().plusSeconds(300)),
        q.get("id"));
    postJson("/sessions/" + sid + "/close", admin, map(), 409);
    assertNotEquals("CLOSED", db.one("SELECT * FROM quote_sessions WHERE id=?", sid).get("status"));
  }

  @Test
  void financeCannotReadSensitiveFreeTextHistory() throws Exception {
    postJson(
        "/users",
        admin,
        map(
            "username",
            "finance-notes",
            "password",
            "FinanceNotes!2026",
            "name",
            "备注测试财务",
            "role",
            "FINANCE",
            "orgId",
            rootOrg),
        200);
    String token = str(login("finance-notes", "FinanceNotes!2026"), "token");
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    Map<String, Object> order =
        postJson(
            "/sessions/" + sid + "/orders",
            customer,
            map("confirmed", true, "quoteId", q.get("id"), "idempotencyKey", id()),
            200);
    String note = "证件核对备注 530102199001010011 13800000000 详细家庭地址";
    request(
        "PATCH",
        "/orders/" + order.get("id") + "/status",
        admin,
        map("status", "PROCESSING", "note", note),
        200);
    Map<String, Object> view = request("GET", "/orders/" + order.get("id"), token, null, 200);
    String rendered = json.writeValueAsString(view);
    assertFalse(rendered.contains("530102199001010011"));
    assertFalse(rendered.contains("13800000000"));
    assertFalse(rendered.contains("详细家庭地址"));
    assertFalse(view.containsKey("vehicle"));
  }

  @Test
  void policyHistoricalVersionCannotBypassCurrentAuthorization() throws Exception {
    Map<String, Object> old =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "原上级政策",
                "content",
                "原比例",
                "orgId",
                rootOrg,
                "vehicleType",
                "MOTORCYCLE",
                "rate",
                "10",
                "effectiveFrom",
                "2020-01-01"),
            200);
    Map<String, Object> latest =
        postJson(
            "/policies",
            admin,
            map(
                "title",
                "下调上级政策",
                "content",
                "最新比例",
                "orgId",
                rootOrg,
                "vehicleType",
                "MOTORCYCLE",
                "rate",
                "5",
                "effectiveFrom",
                "2020-01-01"),
            200);
    postJson(
        "/policies",
        admin,
        map(
            "title",
            "不能引用旧授权",
            "content",
            "旧授权",
            "orgId",
            agentOrg,
            "parentPolicyId",
            old.get("id"),
            "vehicleType",
            "MOTORCYCLE",
            "rate",
            "8",
            "effectiveFrom",
            "2020-01-01"),
        400);
    postJson(
        "/policies",
        admin,
        map(
            "title",
            "当前有效授权",
            "content",
            "合法政策",
            "orgId",
            agentOrg,
            "parentPolicyId",
            latest.get("id"),
            "vehicleType",
            "MOTORCYCLE",
            "rate",
            "4",
            "effectiveFrom",
            "2020-01-01"),
        200);
    postJson(
        "/policies",
        admin,
        map(
            "title",
            "冲突下调",
            "content",
            "下调前需处理下级",
            "orgId",
            rootOrg,
            "vehicleType",
            "MOTORCYCLE",
            "rate",
            "3",
            "effectiveFrom",
            "2020-01-01"),
        400);
  }

  @Test
  void failedCarQuoteCanBecomeInternalManualApplicationWithoutExternalReplay() throws Exception {
    String sid = session(customer, "CAR");
    Map<String, Object> q = quote(sid, customer);
    db.update("UPDATE quotes SET status='OUTCOME_UNKNOWN' WHERE id=?", q.get("id"));
    postJson("/sessions/" + sid + "/handoff", customer, map("reason", "核查外部原单"), 200);
    postJson("/sessions/" + sid + "/claim", service, map(), 200);
    Map<String, Object> order =
        postJson(
            "/sessions/" + sid + "/orders",
            service,
            map("confirmed", true, "idempotencyKey", id()),
            200);
    assertNull(order.get("quoteId"));
    assertEquals(false, order.get("premiumConfirmed"));
    assertNull(order.get("totalPremium"));
    assertEquals(1, db.rows("SELECT * FROM quotes WHERE session_id=?", sid).size());
    assertEquals(
        "OUTCOME_UNKNOWN", db.one("SELECT * FROM quotes WHERE id=?", q.get("id")).get("status"));
  }
}

package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class Quotes {
  final Store db;
  final Sessions sessions;
  final AppConfig config;
  final Gateway gateway;
  final TransactionTemplate tx;

  public Quotes(
      Store db, Sessions sessions, AppConfig config, Gateway gateway, TransactionTemplate tx) {
    this.db = db;
    this.sessions = sessions;
    this.config = config;
    this.gateway = gateway;
    this.tx = tx;
  }

  private record Prepared(String id, Map<String, Object> result, Map<String, Object> body) {}

  public void expirePending(Actor actor, String sid) {
    tx.executeWithoutResult(
        t -> {
          sessions.raw(actor, sid, true, false);
          expire(sid);
        });
  }

  private void expire(String sid) {
    List<Map<String, Object>> pending =
        db.rows(
            "SELECT * FROM quotes WHERE session_id=? AND status='PROCESSING' AND deadline_at<?",
            sid,
            now());
    for (Map<String, Object> row : pending) {
      db.update(
          "UPDATE quotes SET status='OUTCOME_UNKNOWN',result_data=? WHERE id=? AND"
              + " status='PROCESSING'",
          db.encode(map("message", "报价处理未留下确定结果，已转客服核查；不会自动重新提交。", "coverages", List.of())),
          row.get("id"));
      manual(sid, "报价结果待核实，请客服核对泰康原单，不要重复提交。");
    }
  }

  private void manual(String sid, String message) {
    db.update(
        "UPDATE quote_sessions SET status=CASE WHEN status='ACTIVE' THEN 'ACTIVE' ELSE 'WAITING'"
            + " END,updated_at=? WHERE id=?",
        now(),
        sid);
    sessions.message(sid, "SYSTEM", "ASSISTANT", message, null, id());
  }

  public Map<String, Object> quote(Actor actor, String sid, Map<String, Object> input) {
    String key = required(input, "idempotencyKey", 100), plan = required(input, "plan", 20);
    if (!Set.of("COMPULSORY", "STANDARD", "FULL").contains(plan))
      throw ApiException.bad("不支持的报价方案");
    Map<String, Object> selection =
        map(
            "plan",
            plan,
            "thirdPartyAmount",
            amount(input, "thirdPartyAmount", "2000000", 10000000),
            "driverAmount",
            amount(input, "driverAmount", "10000", 1000000),
            "passengerAmount",
            amount(input, "passengerAmount", "10000", 1000000),
            "medicalAmount",
            amount(input, "medicalAmount", "200000", 10000000));
    String requestHash = Crypto.hash(db.json.write(new TreeMap<>(selection)));
    Prepared prepared =
        tx.execute(
            status -> {
              Map<String, Object> s = sessions.raw(actor, sid, true, true);
              expire(sid);
              Map<String, Object> existing =
                  db.maybe(
                      "SELECT * FROM quotes WHERE session_id=? AND idempotency_key=?", sid, key);
              if (existing != null) {
                if (!requestHash.equals(str(existing, "request_hash")))
                  throw ApiException.conflict("同一幂等键不能用于不同方案");
                if ("PROCESSING".equals(str(existing, "status")))
                  throw ApiException.conflict("该报价正在处理中，请稍后刷新会话，不要重复提交");
                return new Prepared(str(existing, "id"), sessions.quoteView(existing), null);
              }
              sessions.editable(s);
              if (db.maybe(
                      "SELECT id FROM quotes WHERE session_id=? AND status IN"
                          + " ('PROCESSING','OUTCOME_UNKNOWN')",
                      sid)
                  != null) throw ApiException.conflict("会话存在处理中或待核实的报价，请由客服核对原单后处理");
              Map<String, Object> vehicle = db.decode(s.get("vehicle_data"));
              String type = str(s, "vehicle_type");
              if (!"MOTORCYCLE".equals(type)) {
                required(vehicle, "plateNo", 20);
                required(vehicle, "ownerName", 100);
                required(vehicle, "vin", 17);
                required(vehicle, "registerDate", 10);
                required(vehicle, "engineNo", 120);
                required(vehicle, "brandModel", 120);
                required(vehicle, "useNature", 60);
                if (!vehicle.containsKey("seatCount")) throw ApiException.bad("请填写座位数");
                if (!config.demo()) {
                  required(vehicle, "idNumber", 18);
                  required(vehicle, "address", 300);
                  required(vehicle, "phone", 11);
                }
              }
              if (!config.demo()
                  && !"MOTORCYCLE".equals(type)
                  && !"TRUCK".equals(type)
                  && !config.gatewayConfigured())
                throw new ApiException(503, "TAIKANG_NOT_CONFIGURED", "泰康网关尚未配置，请联系管理员，或转人工客服");
              List<Map<String, Object>> revisions =
                  db.rows(
                      "SELECT revision FROM quotes WHERE session_id=? ORDER BY revision DESC LIMIT"
                          + " 1",
                      sid);
              int revision =
                  revisions.isEmpty()
                      ? 1
                      : ((Number) revisions.getFirst().get("revision")).intValue() + 1;
              String qid = id();
              Map<String, Object> body = new LinkedHashMap<>(selection);
              body.putAll(map("requestId", qid, "vehicleType", type, "vehicle", vehicle));
              db.update(
                  "UPDATE quotes SET status='SUPERSEDED' WHERE session_id=? AND status='QUOTED'",
                  sid);
              db.update(
                  "INSERT INTO"
                      + " quotes(id,session_id,revision,vehicle_revision,idempotency_key,request_hash,status,plan,snapshot_data,result_data,deadline_at,demo,created_at)"
                      + " VALUES(?,?,?,?,?,?,'PROCESSING',?,?,?,?,?,?)",
                  qid,
                  sid,
                  revision,
                  s.get("vehicle_revision"),
                  key,
                  requestHash,
                  plan,
                  db.encode(map("vehicle", vehicle, "selection", selection)),
                  db.encode(map("message", "报价处理中", "coverages", List.of())),
                  timestamp(Instant.now().plusSeconds(300)),
                  config.demo(),
                  now());
              db.audit(actor, "QUOTE_REQUESTED", qid, "请求泰康报价；版本 " + revision);
              return new Prepared(qid, null, body);
            });
    if (prepared.result() != null) return prepared.result();
    Map<String, Object> result;
    if ("MOTORCYCLE".equals(str(prepared.body(), "vehicleType")))
      result =
          map("status", "MANUAL_REQUIRED", "message", "摩托车由人工客服报价，已进入人工队列", "coverages", List.of());
    else if ("TRUCK".equals(str(prepared.body(), "vehicleType")))
      result =
          map(
              "status",
              "MANUAL_REQUIRED",
              "message",
              "当前泰康资料包未确认货车车型及吨位报价协议，已转人工处理",
              "coverages",
              List.of());
    else if (config.demo()) result = demo(prepared.body());
    else
      try {
        result = normalize(gateway.call("/internal/quote", prepared.body()));
      } catch (ApiException e) {
        result =
            map(
                "status",
                "OUTCOME_UNKNOWN",
                "message",
                "外部报价未获得确定结果，已转人工核实；系统不会自动重试。",
                "coverages",
                List.of());
      }
    Map<String, Object> finalResult = result;
    return tx.execute(
        status -> {
          Map<String, Object> s = db.one("SELECT * FROM quote_sessions WHERE id=? FOR UPDATE", sid);
          Map<String, Object> q =
              db.one("SELECT * FROM quotes WHERE id=? FOR UPDATE", prepared.id());
          if (!"PROCESSING".equals(str(q, "status"))) return sessions.quoteView(q);
          boolean closed = "CLOSED".equals(str(s, "status"));
          String outcome = str(finalResult, "status");
          Instant until =
              outcome.equals("QUOTED") ? Instant.parse(str(finalResult, "validUntil")) : null;
          db.update(
              "UPDATE quotes SET status=?,result_data=?,valid_until=? WHERE id=?",
              outcome,
              db.encode(finalResult),
              until == null ? null : timestamp(until),
              prepared.id());
          if (closed) {
            db.audit(actor, "QUOTE_RESULT_AFTER_CLOSE", prepared.id(), "保存报价结果但不重新打开关闭会话");
          } else if (outcome.equals("QUOTED")) {
            db.update("UPDATE quote_sessions SET stage=3,updated_at=? WHERE id=?", now(), sid);
            sessions.message(
                sid,
                "SYSTEM",
                "ASSISTANT",
                config.demo() ? "演示报价已生成，仅用于测试页面流程，不可作为真实保费。" : "泰康报价已返回，请核对险种与保费，再确认提交投保申请。",
                null,
                id());
          } else manual(sid, str(finalResult, "message"));
          db.audit(actor, "QUOTE_" + outcome, prepared.id(), "泰康报价处理结果");
          return sessions.quoteView(db.one("SELECT * FROM quotes WHERE id=?", prepared.id()));
        });
  }

  private String amount(Map<String, Object> input, String key, String fallback, int max) {
    String s = str(input, key);
    BigDecimal d = decimal(s.isBlank() ? fallback : s, key);
    if (d.signum() < 0
        || d.compareTo(BigDecimal.valueOf(max)) > 0
        || d.stripTrailingZeros().scale() > 0) throw ApiException.bad(key + " 超出允许的整数保额范围");
    return d.toPlainString();
  }

  private Map<String, Object> normalize(Map<String, Object> result) {
    String status = str(result, "status");
    if (!Set.of("QUOTED", "MANUAL_REQUIRED", "FAILED", "OUTCOME_UNKNOWN").contains(status))
      throw new ApiException(502, "INVALID_QUOTE", "泰康报价返回格式需要人工核查");
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("status", status);
    out.put("message", limited(result, "message", 1000));
    out.put("coverages", result.getOrDefault("coverages", List.of()));
    if (status.equals("QUOTED")) {
      for (String key :
          List.of("totalPremium", "commercialPremium", "compulsoryPremium", "vehicleTax")) {
        BigDecimal d = decimal(result.get(key), key);
        if (d.signum() < 0
            || d.compareTo(new BigDecimal("10000000")) > 0
            || d.stripTrailingZeros().scale() > 2)
          throw new ApiException(502, "INVALID_PREMIUM", "保费字段异常，需要人工核对");
        out.put(key, money(d));
      }
      if (decimal(out.get("totalPremium"), "保费").signum() <= 0)
        throw new ApiException(502, "INVALID_PREMIUM", "保费字段异常，需要人工核对");
      try {
        Instant expiry = Instant.parse(str(result, "validUntil"));
        if (!expiry.isAfter(Instant.now())) throw new IllegalArgumentException();
        out.put("validUntil", expiry.toString());
      } catch (Exception e) {
        throw new ApiException(502, "INVALID_VALIDITY", "报价有效期异常，请客服核查");
      }
      if (!(out.get("coverages") instanceof List<?>))
        throw new ApiException(502, "INVALID_COVERAGE", "险种明细格式异常，请客服核查");
    }
    for (String ref : List.of("supplierOrderId", "supplierQuoteRef"))
      if (result.containsKey(ref)) out.put(ref, limited(result, ref, 200));
    return out;
  }

  private Map<String, Object> demo(Map<String, Object> body) {
    String plan = str(body, "plan");
    BigDecimal commercial =
        switch (plan) {
          case "COMPULSORY" -> BigDecimal.ZERO;
          case "STANDARD" -> new BigDecimal("1260.00");
          default -> new BigDecimal("2486.50");
        };
    List<Map<String, Object>> coverages = new ArrayList<>();
    coverages.add(map("name", "交强险（演示）", "amount", "按条款", "premium", "950.00"));
    if (!plan.equals("COMPULSORY")) {
      coverages.add(
          map(
              "name",
              "商业第三者责任险（演示）",
              "amount",
              body.get("thirdPartyAmount"),
              "premium",
              plan.equals("FULL") ? "1260.00" : money(commercial)));
      if (plan.equals("FULL"))
        coverages.add(map("name", "机动车损失险（演示）", "amount", "以实际核定为准", "premium", "1226.50"));
    }
    return map(
        "status",
        "QUOTED",
        "totalPremium",
        money(commercial.add(new BigDecimal("1310.00"))),
        "commercialPremium",
        money(commercial),
        "compulsoryPremium",
        "950.00",
        "vehicleTax",
        "360.00",
        "coverages",
        coverages,
        "validUntil",
        Instant.now().plus(Duration.ofMinutes(30)).toString(),
        "message",
        "演示数据：固定样例金额，仅用于验证业务流程，不代表泰康真实报价");
  }
}

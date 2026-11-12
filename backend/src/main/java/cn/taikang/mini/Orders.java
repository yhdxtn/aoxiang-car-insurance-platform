package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.math.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class Orders {
  final Store db;
  final Access access;
  final Sessions sessions;
  final TransactionTemplate tx;
  final AppConfig config;

  public Orders(
      Store db, Access access, Sessions sessions, TransactionTemplate tx, AppConfig config) {
    this.db = db;
    this.access = access;
    this.sessions = sessions;
    this.tx = tx;
    this.config = config;
  }

  public boolean visible(Actor a, Map<String, Object> row) {
    if (access.record(a, row)) return true;
    if (a.is("SERVICE")) {
      Map<String, Object> s =
          db.one("SELECT * FROM quote_sessions WHERE id=?", row.get("session_id"));
      return access.session(a, s) && a.id().equals(str(s, "assigned_to"));
    }
    return false;
  }

  public Map<String, Object> create(Actor actor, String sid, Map<String, Object> input) {
    String key = required(input, "idempotencyKey", 100), qid = limited(input, "quoteId", 36);
    if (!bool(input.get("confirmed"))) throw ApiException.bad("请先确认投保资料与所选方案");
    String hash = Crypto.hash(qid + ":confirmed");
    return tx.execute(
        status -> {
          Map<String, Object> s = sessions.raw(actor, sid, true, true);
          Map<String, Object> old =
              db.maybe("SELECT * FROM insurance_orders WHERE session_id=?", sid);
          if (old != null) {
            if (qid.equals(str(old, "quote_id"))) return view(old, actor, true);
            throw ApiException.conflict("本会话已创建申请，不能重复选择其他报价建单");
          }
          sessions.editable(s);
          Map<String, Object> quote = null;
          BigDecimal premium = BigDecimal.ZERO;
          Map<String, Object> vehicle = db.decode(s.get("vehicle_data"));
          if (!qid.isBlank()) {
            quote = db.one("SELECT * FROM quotes WHERE id=? AND session_id=?", qid, sid);
            if (!"QUOTED".equals(str(quote, "status"))
                || quote.get("valid_until") == null
                || !instant(quote.get("valid_until")).isAfter(Instant.now()))
              throw ApiException.conflict("报价已失效或未成功，请重新核对");
            if (number(quote.get("vehicle_revision")) != number(s.get("vehicle_revision")))
              throw ApiException.conflict("车辆资料已变更，不能使用旧报价");
            Map<String, Object> result = db.decode(quote.get("result_data"));
            premium = decimal(result.get("totalPremium"), "总保费");
          } else {
            actor.require("SERVICE", "ADMIN");
            if (!Set.of("WAITING", "ACTIVE").contains(str(s, "status")))
              throw ApiException.conflict("人工申请只能从待接入或接待中的会话创建，请先转人工");
            if (db.maybe("SELECT id FROM quotes WHERE session_id=? AND status='PROCESSING'", sid)
                != null) throw ApiException.conflict("外部报价正在处理中，请先等待结果");
            required(vehicle, "ownerName", 100);
            required(vehicle, "phone", 11);
          }
          Map<String, Object> policy = effectivePolicy(str(s, "org_id"), str(s, "vehicle_type"));
          String oid = id(),
              orderNo =
                  "TK"
                      + DateTimeFormatter.ofPattern("yyyyMMddHHmmss")
                          .withZone(ZoneId.of("Asia/Shanghai"))
                          .format(Instant.now())
                      + oid.substring(0, 8).toUpperCase(Locale.ROOT);
          BigDecimal rate = policy == null ? BigDecimal.ZERO : decimal(policy.get("rate"), "费率");
          db.update(
              "INSERT INTO"
                  + " insurance_orders(id,order_no,session_id,owner_id,org_id,quote_id,idempotency_key,request_hash,vehicle_type,status,total_premium,premium_confirmed,vehicle_data,policy_id,commission_rate,demo,created_at,updated_at)"
                  + " VALUES(?,?,?,?,?,?,?,?,?,'PENDING_REVIEW',?,?,?,?,?,?,?,?)",
              oid,
              orderNo,
              sid,
              s.get("owner_id"),
              s.get("org_id"),
              qid.isBlank() ? null : qid,
              key,
              hash,
              s.get("vehicle_type"),
              premium,
              !qid.isBlank(),
              db.encode(vehicle),
              policy == null ? null : policy.get("id"),
              rate,
              config.demo(),
              now(),
              now());
          db.update(
              "UPDATE quote_sessions SET order_id=?,stage=3,status=CASE WHEN status='ACTIVE' THEN"
                  + " 'ACTIVE' ELSE 'WAITING' END,updated_at=? WHERE id=?",
              oid,
              now(),
              sid);
          history(
              oid,
              "PENDING_REVIEW",
              qid.isBlank()
                  ? "已登记内部人工核查申请；保费待人工核实。如有未知报价先核对原外部单，当前操作未重新请求泰康"
                  : "用户已确认资料与报价，等待人工审核；不代表付款或出单",
              actor.id());
          sessions.message(sid, "SYSTEM", "ASSISTANT", "投保申请已提交，客服将继续协助。当前未支付、未自动出单。", null, id());
          db.audit(actor, "ORDER_CREATED", oid, "创建投保申请并冻结组织及政策版本");
          return view(db.one("SELECT * FROM insurance_orders WHERE id=?", oid), actor, true);
        });
  }

  public Map<String, Object> effectivePolicy(String org, String type) {
    LocalDate today = LocalDate.now(ZoneId.of("Asia/Shanghai"));
    for (String current : List.of(org)) {
      List<Map<String, Object>> rows =
          db.rows(
              "SELECT * FROM policies WHERE org_id=? AND vehicle_type=? AND enabled=TRUE AND"
                  + " effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY"
                  + " version DESC",
              current,
              type,
              java.sql.Date.valueOf(today),
              java.sql.Date.valueOf(today));
      if (!rows.isEmpty()) return rows.getFirst();
    }
    return null;
  }

  public Map<String, Object> list(Actor actor, String search, String status, int page, int size) {
    String term = search == null ? "" : search.toLowerCase(Locale.ROOT).trim();
    List<Map<String, Object>> out =
        db.rows("SELECT * FROM insurance_orders ORDER BY created_at DESC").stream()
            .filter(r -> visible(actor, r))
            .filter(r -> status == null || status.isBlank() || status.equals(str(r, "status")))
            .map(r -> view(r, actor, false))
            .filter(
                r ->
                    term.isBlank()
                        || List.of("orderNo", "plateNo", "customerName", "vin", "policyNo", "phone")
                            .stream()
                            .anyMatch(k -> str(r, k).toLowerCase(Locale.ROOT).contains(term)))
            .toList();
    return page(out, page, size);
  }

  public Map<String, Object> get(Actor actor, String oid) {
    Map<String, Object> row = db.one("SELECT * FROM insurance_orders WHERE id=?", oid);
    if (!visible(actor, row)) throw ApiException.missing();
    return view(row, actor, true);
  }

  public Map<String, Object> view(Map<String, Object> row, Actor actor, boolean full) {
    Map<String, Object> vehicle = db.decode(row.get("vehicle_data"));
    String orgName =
        str(db.one("SELECT name FROM organizations WHERE id=?", row.get("org_id")), "name");
    Map<String, Object> out =
        map(
            "id",
            row.get("id"),
            "orderNo",
            row.get("order_no"),
            "sessionId",
            row.get("session_id"),
            "ownerId",
            row.get("owner_id"),
            "orgId",
            row.get("org_id"),
            "orgName",
            orgName,
            "customerName",
            vehicle.get("ownerName"),
            "phone",
            actor.is("FINANCE") ? mask(str(vehicle, "phone")) : vehicle.get("phone"),
            "plateNo",
            vehicle.get("plateNo"),
            "vin",
            actor.is("FINANCE") ? mask(str(vehicle, "vin")) : vehicle.get("vin"),
            "vehicleType",
            row.get("vehicle_type"),
            "insurer",
            "TAIKANG",
            "status",
            row.get("status"),
            "totalPremium",
            bool(row.get("premium_confirmed")) ? money(row.get("total_premium")) : null,
            "premiumConfirmed",
            bool(row.get("premium_confirmed")),
            "quoteId",
            row.get("quote_id"),
            "policyNo",
            row.get("policy_no"),
            "createdAt",
            iso(row.get("created_at")),
            "updatedAt",
            iso(row.get("updated_at")),
            "demo",
            bool(row.get("demo")));
    if (full) {
      out.put(
          "history",
          db
              .rows(
                  "SELECT h.*,u.name FROM order_history h LEFT JOIN users u ON u.id=h.actor_id"
                      + " WHERE order_id=? ORDER BY h.created_at",
                  row.get("id"))
              .stream()
              .map(
                  h ->
                      map(
                          "id",
                          h.get("id"),
                          "status",
                          h.get("status"),
                          "note",
                          actor.is("FINANCE")
                              ? "业务备注限业务人员查看"
                              : db.crypto.decrypt(str(h, "note_data")),
                          "actorName",
                          h.get("name"),
                          "createdAt",
                          iso(h.get("created_at"))))
              .toList());
      if (!actor.is("FINANCE")) out.put("vehicle", vehicle);
    }
    return out;
  }

  private String mask(String value) {
    return value.length() > 6
        ? value.substring(0, 3) + "****" + value.substring(value.length() - 3)
        : "***";
  }

  public Map<String, Object> change(Actor actor, String oid, Map<String, Object> input) {
    actor.require("ADMIN", "SERVICE", "AGENT");
    String next = required(input, "status", 30),
        note = required(input, "note", 500),
        policyNo = limited(input, "policyNo", 100);
    return tx.execute(
        status -> {
          Map<String, Object> order =
              db.one("SELECT * FROM insurance_orders WHERE id=? FOR UPDATE", oid);
          if (!visible(actor, order)) throw ApiException.missing();
          String prev = str(order, "status");
          boolean priceInput =
              input.containsKey("totalPremium") && !str(input, "totalPremium").isBlank();
          boolean confirmed = bool(order.get("premium_confirmed"));
          BigDecimal premium = decimal(order.get("total_premium"), "保费");
          if (priceInput) {
            actor.require("ADMIN", "SERVICE");
            if (!str(order, "quote_id").isBlank()) throw ApiException.bad("泰康自动报价已冻结，不允许人工修改保费");
            if (!Set.of("PENDING_REVIEW", "PROCESSING").contains(prev))
              throw ApiException.conflict("已完成或取消的订单不能更改保费");
            premium = decimal(input.get("totalPremium"), "人工核实保费");
            if (premium.signum() <= 0
                || premium.compareTo(new BigDecimal("10000000")) > 0
                || premium.stripTrailingZeros().scale() > 2)
              throw ApiException.bad("人工核实保费必须大于0、不超过1000万元且最多2位小数");
            confirmed = true;
          }
          if (prev.equals(next) && !priceInput) return view(order, actor, true);
          boolean allowed =
              prev.equals(next) && priceInput
                  || prev.equals("PENDING_REVIEW")
                      && Set.of("PROCESSING", "CANCELLED").contains(next)
                  || prev.equals("PROCESSING") && Set.of("COMPLETED", "CANCELLED").contains(next);
          if (!allowed) throw ApiException.conflict("不允许从 " + prev + " 变更为 " + next);
          if (next.equals("COMPLETED") && (!confirmed || policyNo.isBlank()))
            throw ApiException.bad("完成处理前必须核实保费并填写正式保单号");
          db.update(
              "UPDATE insurance_orders SET"
                  + " status=?,policy_no=?,total_premium=?,premium_confirmed=?,updated_at=? WHERE"
                  + " id=?",
              next,
              policyNo.isBlank() ? order.get("policy_no") : policyNo,
              premium,
              confirmed,
              now(),
              oid);
          history(
              oid, next, (priceInput ? "人工核实保费 " + money(premium) + " 元。" : "") + note, actor.id());
          db.audit(
              actor,
              priceInput ? "MANUAL_PREMIUM_CONFIRMED" : "ORDER_STATUS_CHANGED",
              oid,
              prev + " -> " + next + (priceInput ? "；核价 " + money(premium) + " 元" : ""));
          return view(db.one("SELECT * FROM insurance_orders WHERE id=?", oid), actor, true);
        });
  }

  private void history(String oid, String status, String note, String actor) {
    db.update(
        "INSERT INTO order_history(id,order_id,status,note_data,actor_id,created_at)"
            + " VALUES(?,?,?,?,?,?)",
        id(),
        oid,
        status,
        db.crypto.encrypt(note),
        actor,
        now());
  }

  public Map<String, Object> finance(Actor actor) {
    actor.require("ADMIN", "FINANCE", "AGENT");
    BigDecimal premium = BigDecimal.ZERO, commission = BigDecimal.ZERO;
    List<Map<String, Object>> items = new ArrayList<>();
    for (Map<String, Object> row :
        db.rows("SELECT * FROM insurance_orders ORDER BY created_at DESC")) {
      if (!visible(actor, row)) continue;
      BigDecimal p = decimal(row.get("total_premium"), "保费"),
          rate = decimal(row.get("commission_rate"), "比例"),
          c = p.multiply(rate).divide(new BigDecimal("100"), 2, RoundingMode.HALF_UP);
      if (bool(row.get("premium_confirmed")) && !"CANCELLED".equals(str(row, "status"))) {
        premium = premium.add(p);
        commission = commission.add(c);
      } else c = BigDecimal.ZERO;
      items.add(
          map(
              "orderNo",
              row.get("order_no"),
              "orgName",
              db.one("SELECT name FROM organizations WHERE id=?", row.get("org_id")).get("name"),
              "totalPremium",
              bool(row.get("premium_confirmed")) ? money(p) : null,
              "premiumConfirmed",
              bool(row.get("premium_confirmed")),
              "rate",
              rate.toPlainString(),
              "commission",
              money(c),
              "status",
              row.get("status"),
              "policyId",
              row.get("policy_id"),
              "demo",
              bool(row.get("demo"))));
    }
    return map(
        "premium",
        money(premium),
        "estimatedCommission",
        money(commission),
        "items",
        items,
        "message",
        "按申请快照估算；不代表已收款、已结算或可提现金额");
  }
}

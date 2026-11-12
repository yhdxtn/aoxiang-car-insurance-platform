package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class Management {
  final Store db;
  final Access access;
  final AuthService auth;
  final TransactionTemplate tx;
  final Orders orders;

  public Management(
      Store db, Access access, AuthService auth, TransactionTemplate tx, Orders orders) {
    this.db = db;
    this.access = access;
    this.auth = auth;
    this.tx = tx;
    this.orders = orders;
  }

  Map<String, Object> orgView(Map<String, Object> row) {
    return map(
        "id",
        row.get("id"),
        "name",
        row.get("name"),
        "parentId",
        row.get("parent_id"),
        "level",
        row.get("depth"),
        "enabled",
        bool(row.get("enabled")),
        "createdAt",
        iso(row.get("created_at")));
  }

  public Map<String, Object> organizations(Actor actor) {
    Set<String> allowed =
        actor.is("CUSTOMER", "SERVICE")
            ? access.ancestors(actor.orgId())
            : access.descendants(actor.orgId());
    return map(
        "items",
        db.rows("SELECT * FROM organizations ORDER BY depth,created_at").stream()
            .filter(r -> actor.is("ADMIN", "FINANCE") || allowed.contains(str(r, "id")))
            .map(this::orgView)
            .toList());
  }

  public Map<String, Object> createOrganization(Actor actor, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT");
    String name = required(input, "name", 100), parent = required(input, "parentId", 36);
    return tx.execute(
        status -> {
          Map<String, Object> p =
              db.one("SELECT * FROM organizations WHERE id=? FOR UPDATE", parent);
          if (!auth.orgEnabled(parent)) throw ApiException.bad("上级组织已停用");
          if (!actor.is("ADMIN") && !actor.orgId().equals(parent)) throw ApiException.forbidden();
          int level = ((Number) p.get("depth")).intValue() + 1;
          if (level > 20) throw ApiException.bad("组织层级最多20级");
          String oid = id();
          db.update(
              "INSERT INTO organizations(id,name,parent_id,depth,enabled,created_at)"
                  + " VALUES(?,?,?,?,TRUE,?)",
              oid,
              name,
              parent,
              level,
              now());
          db.audit(actor, "ORGANIZATION_CREATED", oid, "新增下级组织");
          return orgView(db.one("SELECT * FROM organizations WHERE id=?", oid));
        });
  }

  public Map<String, Object> updateOrganization(
      Actor actor, String oid, Map<String, Object> input) {
    access.manageOrg(actor, oid);
    return tx.execute(
        status -> {
          Map<String, Object> row =
              db.one("SELECT * FROM organizations WHERE id=? FOR UPDATE", oid);
          String name = input.containsKey("name") ? required(input, "name", 100) : str(row, "name");
          boolean enabled =
              input.containsKey("enabled")
                  ? booleanValue(input.get("enabled"))
                  : bool(row.get("enabled"));
          if (!enabled && (str(row, "parent_id").isBlank() || actor.orgId().equals(oid)))
            throw ApiException.bad("不能停用总部或当前账号所在组织");
          db.update("UPDATE organizations SET name=?,enabled=? WHERE id=?", name, enabled, oid);
          if (!enabled)
            for (String id : access.descendants(oid))
              db.update(
                  "DELETE FROM auth_tokens WHERE user_id IN (SELECT id FROM users WHERE org_id=?)",
                  id);
          db.audit(actor, "ORGANIZATION_UPDATED", oid, enabled ? "更新组织" : "停用组织及其登录权限");
          return orgView(db.one("SELECT * FROM organizations WHERE id=?", oid));
        });
  }

  public Map<String, Object> users(Actor actor, String role, int page, int size) {
    actor.require("ADMIN", "FINANCE", "AGENT");
    return page(
        db.rows("SELECT * FROM users ORDER BY created_at DESC").stream()
            .filter(u -> actor.is("ADMIN", "FINANCE") || access.org(actor, str(u, "org_id")))
            .filter(u -> role == null || role.isBlank() || role.equals(str(u, "role")))
            .map(auth::publicUser)
            .toList(),
        page,
        size);
  }

  public Map<String, Object> createUser(Actor actor, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT");
    String username = required(input, "username", 100),
        password = required(input, "password", 128),
        name = required(input, "name", 100),
        role = required(input, "role", 20),
        org = required(input, "orgId", 36);
    if (!username.matches("[a-zA-Z0-9_.@-]{3,100}"))
      throw ApiException.bad("用户名需为3至100位英文字母、数字或_.@-");
    if (!Set.of("ADMIN", "FINANCE", "AGENT", "SERVICE", "CUSTOMER").contains(role))
      throw ApiException.bad("无效角色");
    AuthService.validatePassword(password);
    if (!actor.is("ADMIN")
        && (!role.equals("AGENT")
            || org.equals(actor.orgId())
            || !access.descendants(actor.orgId()).contains(org))) throw ApiException.forbidden();
    if (Set.of("ADMIN", "FINANCE").contains(role) && !auth.rootOrg().equals(org))
      throw ApiException.bad("总部管理员与财务必须归属总部");
    return tx.execute(
        status -> {
          db.one("SELECT * FROM organizations WHERE id=? FOR UPDATE", org);
          if (!auth.orgEnabled(org)) throw ApiException.bad("组织已停用");
          String uid = id();
          db.update(
              "INSERT INTO"
                  + " users(id,username,password_hash,name,role,org_id,enabled,points,invite_code,created_at)"
                  + " VALUES(?,?,?,?,?,?,TRUE,0,?,?)",
              uid,
              username,
              auth.passwords.encode(password),
              name,
              role,
              org,
              role.equals("AGENT") ? id().replace("-", "").substring(0, 16) : null,
              now());
          db.audit(actor, "USER_CREATED", uid, "创建角色：" + role);
          return auth.publicUser(db.one("SELECT * FROM users WHERE id=?", uid));
        });
  }

  public Map<String, Object> updateUser(Actor actor, String uid, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT");
    return tx.execute(
        status -> {
          Map<String, Object> u = db.one("SELECT * FROM users WHERE id=? FOR UPDATE", uid);
          if (!actor.is("ADMIN")
              && (!str(u, "role").equals("AGENT")
                  || str(u, "org_id").equals(actor.orgId())
                  || !access.descendants(actor.orgId()).contains(str(u, "org_id"))))
            throw ApiException.forbidden();
          if (!actor.is("ADMIN") && (input.containsKey("role") || input.containsKey("orgId")))
            throw ApiException.forbidden();
          String name = input.containsKey("name") ? required(input, "name", 100) : str(u, "name"),
              role = input.containsKey("role") ? required(input, "role", 20) : str(u, "role"),
              org = input.containsKey("orgId") ? required(input, "orgId", 36) : str(u, "org_id");
          boolean enabled =
              input.containsKey("enabled")
                  ? booleanValue(input.get("enabled"))
                  : bool(u.get("enabled"));
          if (!Set.of("ADMIN", "FINANCE", "AGENT", "SERVICE", "CUSTOMER").contains(role))
            throw ApiException.bad("无效角色");
          if (Set.of("ADMIN", "FINANCE").contains(role) && !auth.rootOrg().equals(org))
            throw ApiException.bad("总部管理员与财务必须归属总部");
          if (!auth.orgEnabled(org)) throw ApiException.bad("目标组织已停用");
          if (uid.equals(actor.id())
              && (!enabled || !role.equals(actor.role()) || !org.equals(actor.orgId())))
            throw ApiException.bad("不能撤销自身管理权限或移动自身组织");
          if (str(u, "role").equals("ADMIN")
              && (!enabled || !role.equals("ADMIN"))
              && db.rows("SELECT id FROM users WHERE role='ADMIN' AND enabled=TRUE").size() <= 1)
            throw ApiException.bad("至少保留一名启用的管理员");
          db.update(
              "UPDATE users SET name=?,role=?,org_id=?,enabled=?,invite_code=? WHERE id=?",
              name,
              role,
              org,
              enabled,
              role.equals("AGENT")
                  ? (str(u, "invite_code").isBlank()
                      ? id().replace("-", "").substring(0, 16)
                      : u.get("invite_code"))
                  : null,
              uid);
          if (!role.equals(str(u, "role"))
              || !org.equals(str(u, "org_id"))
              || enabled != bool(u.get("enabled")))
            db.update("DELETE FROM auth_tokens WHERE user_id=?", uid);
          db.audit(actor, "USER_UPDATED", uid, "更新账号；历史订单组织保持冻结归属");
          return auth.publicUser(db.one("SELECT * FROM users WHERE id=?", uid));
        });
  }

  boolean booleanValue(Object value) {
    if (!(value instanceof Boolean)) throw ApiException.bad("enabled必须为布尔值");
    return (Boolean) value;
  }

  public Map<String, Object> serviceAgents(Actor actor) {
    actor.require("ADMIN", "SERVICE");
    return map(
        "items",
        db.rows("SELECT * FROM users WHERE role='SERVICE' AND enabled=TRUE ORDER BY name").stream()
            .filter(u -> auth.orgEnabled(str(u, "org_id")))
            .filter(
                u ->
                    actor.is("ADMIN")
                        || access.ancestors(actor.orgId()).contains(str(u, "org_id"))
                        || access.descendants(actor.orgId()).contains(str(u, "org_id")))
            .map(u -> map("id", u.get("id"), "name", u.get("name"), "orgId", u.get("org_id")))
            .toList());
  }

  public Map<String, Object> customers(Actor actor, String search, int page, int size) {
    actor.require("ADMIN", "AGENT", "CUSTOMER", "SERVICE");
    String term = search == null ? "" : search.toLowerCase(Locale.ROOT);
    return page(
        db.rows("SELECT * FROM customers ORDER BY updated_at DESC").stream()
            .filter(c -> customerVisible(actor, c))
            .map(this::customerView)
            .filter(
                c ->
                    term.isBlank()
                        || str(c, "name").toLowerCase(Locale.ROOT).contains(term)
                        || str(c, "phone").contains(term)
                        || str(c, "plateNo").toLowerCase(Locale.ROOT).contains(term))
            .toList(),
        page,
        size);
  }

  boolean customerVisible(Actor actor, Map<String, Object> row) {
    if (access.record(actor, row)) return true;
    if (actor.is("SERVICE") && !str(row, "source_session_id").isBlank()) {
      Map<String, Object> s =
          db.one("SELECT * FROM quote_sessions WHERE id=?", row.get("source_session_id"));
      return actor.id().equals(str(s, "assigned_to")) && access.session(actor, s);
    }
    return false;
  }

  Map<String, Object> customerView(Map<String, Object> row) {
    Map<String, Object> out = new LinkedHashMap<>(db.decode(row.get("details_data")));
    out.putAll(
        map(
            "id",
            row.get("id"),
            "ownerId",
            row.get("owner_id"),
            "orgId",
            row.get("org_id"),
            "sessionId",
            row.get("source_session_id"),
            "createdAt",
            iso(row.get("created_at")),
            "updatedAt",
            iso(row.get("updated_at"))));
    return out;
  }

  Map<String, Object> customerInput(Map<String, Object> input) {
    String name = required(input, "name", 100), phone = required(input, "phone", 11);
    if (!phone.matches("1[3-9]\\d{9}")) throw ApiException.bad("手机号格式不正确");
    return map("name", name, "phone", phone, "notes", limited(input, "notes", 3000));
  }

  public Map<String, Object> createCustomer(Actor actor, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT", "CUSTOMER");
    Map<String, Object> details = customerInput(input);
    return tx.execute(
        status -> {
          String cid = id();
          db.update(
              "INSERT INTO customers(id,owner_id,org_id,details_data,created_at,updated_at)"
                  + " VALUES(?,?,?,?,?,?)",
              cid,
              actor.id(),
              actor.orgId(),
              db.encode(details),
              now(),
              now());
          db.audit(actor, "CUSTOMER_CREATED", cid, "新增客户资料");
          return customerView(db.one("SELECT * FROM customers WHERE id=?", cid));
        });
  }

  public Map<String, Object> updateCustomer(Actor actor, String cid, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT", "CUSTOMER", "SERVICE");
    Map<String, Object> details = customerInput(input);
    return tx.execute(
        status -> {
          Map<String, Object> row = db.one("SELECT * FROM customers WHERE id=? FOR UPDATE", cid);
          if (!customerVisible(actor, row)) throw ApiException.missing();
          Map<String, Object> old = db.decode(row.get("details_data"));
          old.putAll(details);
          db.update(
              "UPDATE customers SET details_data=?,updated_at=? WHERE id=?",
              db.encode(old),
              now(),
              cid);
          db.audit(actor, "CUSTOMER_UPDATED", cid, "维护客户与跟进备注");
          return customerView(db.one("SELECT * FROM customers WHERE id=?", cid));
        });
  }

  public Map<String, Object> policies(Actor actor, boolean history) {
    List<Map<String, Object>> all =
        db.rows("SELECT * FROM policies ORDER BY version DESC,created_at DESC");
    Set<String> visible = new HashSet<>(access.ancestors(actor.orgId()));
    if (actor.is("AGENT")) visible.addAll(access.descendants(actor.orgId()));
    Set<String> latest = new HashSet<>();
    LocalDate today = LocalDate.now(ZoneId.of("Asia/Shanghai"));
    List<Map<String, Object>> out = new ArrayList<>();
    for (Map<String, Object> row : all) {
      if (!actor.is("ADMIN", "FINANCE") && !visible.contains(str(row, "org_id"))) continue;
      if (!history) {
        if (!bool(row.get("enabled"))) continue;
        LocalDate from = date(str(row, "effective_from"), "开始日期"),
            to = str(row, "effective_to").isBlank() ? null : date(str(row, "effective_to"), "结束日期");
        if (from.isAfter(today) || to != null && to.isBefore(today)) continue;
        String key = str(row, "org_id") + ":" + str(row, "vehicle_type");
        if (!latest.add(key)) continue;
      }
      out.add(policyView(row, actor));
    }
    return map("items", out);
  }

  Map<String, Object> policyView(Map<String, Object> row, Actor actor) {
    Map<String, Object> out =
        map(
            "id",
            row.get("id"),
            "title",
            row.get("title"),
            "content",
            row.get("content_text"),
            "orgId",
            row.get("org_id"),
            "parentPolicyId",
            row.get("parent_policy_id"),
            "version",
            row.get("version"),
            "enabled",
            bool(row.get("enabled")),
            "effectiveFrom",
            str(row, "effective_from"),
            "effectiveTo",
            row.get("effective_to") == null ? null : str(row, "effective_to"),
            "vehicleType",
            row.get("vehicle_type"),
            "createdAt",
            iso(row.get("created_at")));
    if (actor.is("ADMIN", "AGENT", "FINANCE")) out.put("rate", String.valueOf(row.get("rate")));
    return out;
  }

  public Map<String, Object> createPolicy(Actor actor, Map<String, Object> input) {
    actor.require("ADMIN", "AGENT");
    String title = required(input, "title", 120),
        content = required(input, "content", 10000),
        org = required(input, "orgId", 36),
        parent = limited(input, "parentPolicyId", 36),
        type = required(input, "vehicleType", 20);
    Sessions.type(type);
    BigDecimal rate = decimal(input.get("rate"), "佣金比例");
    if (rate.signum() < 0 || rate.compareTo(new BigDecimal("100")) > 0 || rate.scale() > 4)
      throw ApiException.bad("佣金比例应为0至100，最多4位小数");
    LocalDate from = date(required(input, "effectiveFrom", 10), "开始日期"),
        to = str(input, "effectiveTo").isBlank() ? null : date(str(input, "effectiveTo"), "结束日期");
    if (to != null && to.isBefore(from)) throw ApiException.bad("结束日期不能早于开始日期");
    return tx.execute(
        status -> {
          Map<String, Object> target =
              db.one("SELECT * FROM organizations WHERE id=? FOR UPDATE", org);
          if (!auth.orgEnabled(org)) throw ApiException.bad("目标组织已停用");
          String upstream = str(target, "parent_id");
          if (!actor.is("ADMIN") && !actor.orgId().equals(upstream)) throw ApiException.forbidden();
          if (!upstream.isBlank()) {
            if (parent.isBlank()) throw ApiException.bad("下级政策必须选择直属上级来源政策");
            Map<String, Object> p = db.one("SELECT * FROM policies WHERE id=?", parent);
            if (!upstream.equals(str(p, "org_id"))
                || !type.equals(str(p, "vehicle_type"))
                || !bool(p.get("enabled"))) throw ApiException.bad("来源政策不属于直属上级或车辆类型不匹配");
            Map<String, Object> currentParent = activePolicy(upstream, type, from);
            if (currentParent == null || !parent.equals(str(currentParent, "id")))
              throw ApiException.bad("请选择生效日对应的直属上级最新适用政策，不能引用过期版本放大授权");
            if (rate.compareTo(decimal(p.get("rate"), "上级比例")) > 0)
              throw ApiException.bad("下级比例不能超过上级授权比例");
            LocalDate pf = date(str(p, "effective_from"), "上级开始日期"),
                pt =
                    str(p, "effective_to").isBlank()
                        ? null
                        : date(str(p, "effective_to"), "上级结束日期");
            if (from.isBefore(pf) || pt != null && (to == null || to.isAfter(pt)))
              throw ApiException.bad("子级政策有效期不能超出来源政策");
          } else if (!parent.isBlank()) throw ApiException.bad("总部总政策不应指定来源政策");
          for (Map<String, Object> childOrg :
              db.rows("SELECT id FROM organizations WHERE parent_id=?", org)) {
            String child = str(childOrg, "id");
            TreeSet<LocalDate> dates = new TreeSet<>();
            dates.add(from);
            for (Map<String, Object> childPolicy :
                db.rows(
                    "SELECT effective_from,effective_to FROM policies WHERE org_id=? AND"
                        + " vehicle_type=? AND enabled=TRUE",
                    child,
                    type)) {
              LocalDate d = date(str(childPolicy, "effective_from"), "日期");
              if (!d.isBefore(from) && (to == null || !d.isAfter(to))) dates.add(d);
              if (childPolicy.get("effective_to") != null) {
                LocalDate end = date(str(childPolicy, "effective_to"), "日期").plusDays(1);
                if (!end.isBefore(from) && (to == null || !end.isAfter(to))) dates.add(end);
              }
            }
            for (LocalDate d : dates) {
              Map<String, Object> cp = activePolicy(child, type, d);
              if (cp != null && decimal(cp.get("rate"), "下级比例").compareTo(rate) > 0)
                throw ApiException.bad("新比例低于下级已配置政策，请先调整下级政策再降低上级授权");
            }
          }
          List<Map<String, Object>> previous =
              db.rows(
                  "SELECT version FROM policies WHERE org_id=? AND vehicle_type=? ORDER BY version"
                      + " DESC LIMIT 1",
                  org,
                  type);
          int version =
              previous.isEmpty() ? 1 : ((Number) previous.getFirst().get("version")).intValue() + 1;
          String pid = id();
          db.update(
              "INSERT INTO"
                  + " policies(id,title,content_text,org_id,parent_policy_id,version,rate,enabled,effective_from,effective_to,vehicle_type,created_by,created_at)"
                  + " VALUES(?,?,?,?,?,?,?,TRUE,?,?,?,?,?)",
              pid,
              title,
              content,
              org,
              parent.isBlank() ? null : parent,
              version,
              rate,
              java.sql.Date.valueOf(from),
              to == null ? null : java.sql.Date.valueOf(to),
              type,
              actor.id(),
              now());
          db.audit(actor, "POLICY_VERSION_CREATED", pid, "创建政策版本 " + version + "，保留历史版本");
          return policyView(db.one("SELECT * FROM policies WHERE id=?", pid), actor);
        });
  }

  private Map<String, Object> activePolicy(String org, String type, LocalDate date) {
    return db.maybe(
        "SELECT * FROM policies WHERE org_id=? AND vehicle_type=? AND enabled=TRUE AND"
            + " effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY version"
            + " DESC LIMIT 1",
        org,
        type,
        java.sql.Date.valueOf(date),
        java.sql.Date.valueOf(date));
  }

  public Map<String, Object> points(Actor actor) {
    Map<String, Object> user = db.one("SELECT points FROM users WHERE id=?", actor.id());
    return map(
        "balance",
        user.get("points"),
        "items",
        db
            .rows(
                "SELECT * FROM points_ledger WHERE user_id=? ORDER BY created_at DESC LIMIT 1000",
                actor.id())
            .stream()
            .map(
                r ->
                    map(
                        "id",
                        r.get("id"),
                        "delta",
                        r.get("delta"),
                        "reason",
                        r.get("reason"),
                        "createdAt",
                        iso(r.get("created_at"))))
            .toList());
  }

  public Map<String, Object> adjustPoints(Actor actor, Map<String, Object> input) {
    actor.require("ADMIN", "FINANCE");
    String uid = required(input, "userId", 36),
        reason = required(input, "reason", 500),
        key = required(input, "idempotencyKey", 100);
    long delta;
    try {
      delta = Long.parseLong(str(input, "delta"));
      if (delta == 0 || delta < -1000000 || delta > 1000000) throw new NumberFormatException();
    } catch (Exception e) {
      throw ApiException.bad("积分调整应为-1000000至1000000的非零整数");
    }
    long amount = delta;
    String hash = Crypto.hash(db.json.write(map("userId", uid, "delta", amount, "reason", reason)));
    return tx.execute(
        status -> {
          Map<String, Object> user = db.one("SELECT * FROM users WHERE id=? FOR UPDATE", uid);
          Map<String, Object> prior =
              db.maybe(
                  "SELECT * FROM points_ledger WHERE actor_id=? AND idempotency_key=?",
                  actor.id(),
                  key);
          if (prior != null) {
            if (!hash.equals(str(prior, "request_hash")))
              throw ApiException.conflict("积分幂等键不能用于不同调整");
            return map("id", prior.get("id"), "balance", prior.get("balance_after"));
          }
          long balance = number(user.get("points")) + amount;
          if (balance < 0 || balance > 1000000000L) throw ApiException.bad("积分余额不足或超出上限");
          String id = id();
          db.update(
              "INSERT INTO"
                  + " points_ledger(id,user_id,delta,idempotency_key,request_hash,balance_after,reason,actor_id,created_at)"
                  + " VALUES(?,?,?,?,?,?,?,?,?)",
              id,
              uid,
              amount,
              key,
              hash,
              balance,
              reason,
              actor.id(),
              now());
          db.update("UPDATE users SET points=? WHERE id=?", balance, uid);
          db.audit(actor, "POINTS_ADJUSTED", uid, "人工调整积分：" + amount);
          return map("id", id, "balance", balance);
        });
  }

  public Map<String, Object> audit(Actor actor, int page, int size) {
    actor.require("ADMIN");
    return page(
        db
            .rows(
                "SELECT a.*,u.name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY"
                    + " a.created_at DESC")
            .stream()
            .map(
                r ->
                    map(
                        "id",
                        r.get("id"),
                        "actorId",
                        r.get("actor_id"),
                        "actorName",
                        r.get("name"),
                        "action",
                        r.get("action"),
                        "targetId",
                        r.get("target_id"),
                        "summary",
                        r.get("summary"),
                        "createdAt",
                        iso(r.get("created_at"))))
            .toList(),
        page,
        size);
  }

  public Map<String, Object> dashboard(Actor actor) {
    List<Map<String, Object>> rows =
        db.rows("SELECT * FROM insurance_orders").stream()
            .filter(r -> orders.visible(actor, r))
            .toList();
    BigDecimal premium =
        rows.stream()
            .filter(r -> bool(r.get("premium_confirmed")) && !str(r, "status").equals("CANCELLED"))
            .map(r -> decimal(r.get("total_premium"), "保费"))
            .reduce(BigDecimal.ZERO, BigDecimal::add);
    long customerCount =
        db.rows("SELECT * FROM customers").stream().filter(r -> customerVisible(actor, r)).count();
    long pending =
        actor.is("FINANCE")
            ? 0
            : db.rows("SELECT * FROM quote_sessions WHERE status='WAITING'").stream()
                .filter(r -> access.session(actor, r))
                .count();
    return map(
        "orders",
        rows.size(),
        "customers",
        customerCount,
        "pendingSessions",
        pending,
        "premium",
        money(premium),
        "completedOrders",
        rows.stream().filter(r -> str(r, "status").equals("COMPLETED")).count());
  }
}

package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AuthService {
  private final Store db;
  private final AppConfig config;
  private final Crypto crypto;
  private final TransactionTemplate tx;
  final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);
  private final HttpClient http =
      HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
  private final Map<String, Attempt> attempts = new ConcurrentHashMap<>();

  private record Attempt(int count, Instant start) {}

  public AuthService(Store db, AppConfig config, Crypto crypto, TransactionTemplate tx) {
    this.db = db;
    this.config = config;
    this.crypto = crypto;
    this.tx = tx;
  }

  synchronized void throttle(String key) {
    Instant now = Instant.now();
    if (attempts.size() > 10000)
      attempts.entrySet().removeIf(e -> e.getValue().start().plusSeconds(120).isBefore(now));
    Attempt old = attempts.get(key);
    if (old == null || old.start().plusSeconds(60).isBefore(now)) old = new Attempt(0, now);
    if (old.count() >= 12) throw new ApiException(429, "RATE_LIMITED", "尝试过于频繁，请一分钟后再试");
    attempts.put(key, new Attempt(old.count() + 1, old.start()));
  }

  public Map<String, Object> login(Map<String, Object> input, String remote) {
    String username = required(input, "username", 100);
    String password = required(input, "password", 200);
    if (password.getBytes(StandardCharsets.UTF_8).length > 72)
      throw new ApiException(401, "LOGIN_FAILED", "账号或密码错误");
    throttle("login:" + remote + ":" + username);
    Map<String, Object> user = db.maybe("SELECT * FROM users WHERE username=?", username);
    String hash =
        user == null
            ? "$2a$12$Jf8y.mB/U9rJ7lKWrQqMWu9P6vuD3.Og9gI8QEj1oV1bwg9UGxQbG"
            : str(user, "password_hash");
    boolean valid = !hash.isBlank() && passwords.matches(password, hash);
    if (!valid || user == null || !bool(user.get("enabled")) || !orgEnabled(str(user, "org_id")))
      throw new ApiException(401, "LOGIN_FAILED", "账号或密码错误，或账号已停用");
    return issue(user);
  }

  public Map<String, Object> wechat(Map<String, Object> input, String remote) {
    String code = required(input, "code", 300);
    throttle("wx:" + remote);
    if (config.wechatAppid() == null
        || config.wechatAppid().isBlank()
        || config.wechatSecret() == null
        || config.wechatSecret().isBlank())
      throw new ApiException(
          503, "WECHAT_NOT_CONFIGURED", "尚未配置微信小程序 AppID/AppSecret；演示环境请使用演示账号登录");
    String openid;
    try {
      String url =
          "https://api.weixin.qq.com/sns/jscode2session?appid="
              + enc(config.wechatAppid())
              + "&secret="
              + enc(config.wechatSecret())
              + "&js_code="
              + enc(code)
              + "&grant_type=authorization_code";
      HttpResponse<String> response =
          http.send(
              HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(15)).GET().build(),
              HttpResponse.BodyHandlers.ofString());
      Map<String, Object> body = db.json.read(response.body());
      openid = str(body, "openid");
      if (response.statusCode() != 200 || openid.isBlank())
        throw new ApiException(401, "WECHAT_LOGIN_FAILED", "微信登录凭证无效或已过期，请重试登录");
    } catch (ApiException e) {
      throw e;
    } catch (Exception e) {
      throw new ApiException(503, "WECHAT_UNAVAILABLE", "微信登录暂不可用，请稍后重试");
    }
    String hash = Crypto.hash(config.wechatAppid() + ":" + openid);
    return tx.execute(
        status -> {
          Map<String, Object> user = db.maybe("SELECT * FROM users WHERE openid_hash=?", hash);
          if (user == null) {
            String rootOrg = rootOrg();
            String invite = limited(input, "inviteCode", 32);
            if (!invite.isBlank()) {
              Map<String, Object> inviter =
                  db.maybe(
                      "SELECT * FROM users WHERE invite_code=? AND enabled=TRUE AND role='AGENT'",
                      invite);
              if (inviter == null || !orgEnabled(str(inviter, "org_id")))
                throw ApiException.bad("邀请编码无效");
              rootOrg = str(inviter, "org_id");
            }
            String uid = id();
            try {
              db.update(
                  "INSERT INTO"
                      + " users(id,username,openid_hash,name,role,org_id,enabled,points,created_at)"
                      + " VALUES(?,?,?,?,?,?,TRUE,0,?)",
                  uid,
                  "wx_" + hash.substring(0, 40),
                  hash,
                  "微信用户",
                  "CUSTOMER",
                  rootOrg,
                  now());
            } catch (org.springframework.dao.DuplicateKeyException conflict) {
            }
            user = db.one("SELECT * FROM users WHERE openid_hash=?", hash);
          }
          if (!bool(user.get("enabled")) || !orgEnabled(str(user, "org_id")))
            throw ApiException.forbidden();
          return issue(user);
        });
  }

  private String enc(String value) {
    return URLEncoder.encode(value, StandardCharsets.UTF_8);
  }

  public boolean orgEnabled(String orgId) {
    Set<String> visited = new HashSet<>();
    String current = orgId;
    while (current != null && !current.isBlank()) {
      if (!visited.add(current)) return false;
      Map<String, Object> org = db.maybe("SELECT * FROM organizations WHERE id=?", current);
      if (org == null || !bool(org.get("enabled"))) return false;
      current = str(org, "parent_id");
    }
    return true;
  }

  public String rootOrg() {
    return str(db.one("SELECT * FROM organizations WHERE parent_id IS NULL"), "id");
  }

  public Map<String, Object> issue(Map<String, Object> user) {
    String token = crypto.token();
    String uid = str(user, "id");
    db.update("DELETE FROM auth_tokens WHERE user_id=? AND expires_at<?", uid, now());
    db.update(
        "INSERT INTO auth_tokens(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
        Crypto.hash(token),
        uid,
        timestamp(
            Instant.now().plus(Duration.ofHours(Math.max(1, Math.min(72, config.tokenHours()))))),
        now());
    return map("token", token, "user", publicUser(user), "mode", config.mode());
  }

  public Actor authenticate(String token) {
    if (token == null || token.length() > 200) throw new ApiException(401, "UNAUTHORIZED", "请先登录");
    Map<String, Object> user =
        db.maybe(
            "SELECT u.* FROM users u JOIN auth_tokens t ON t.user_id=u.id WHERE t.token_hash=? AND"
                + " t.expires_at>? AND u.enabled=TRUE",
            Crypto.hash(token),
            now());
    if (user == null || !orgEnabled(str(user, "org_id")))
      throw new ApiException(401, "UNAUTHORIZED", "登录已失效，请重新登录");
    return new Actor(str(user, "id"), str(user, "name"), str(user, "role"), str(user, "org_id"));
  }

  public Map<String, Object> me(Actor actor) {
    return publicUser(db.one("SELECT * FROM users WHERE id=?", actor.id()));
  }

  public Map<String, Object> publicUser(Map<String, Object> user) {
    Map<String, Object> org = db.one("SELECT * FROM organizations WHERE id=?", user.get("org_id"));
    return map(
        "id",
        user.get("id"),
        "username",
        user.get("username"),
        "name",
        user.get("name"),
        "role",
        user.get("role"),
        "orgId",
        user.get("org_id"),
        "orgName",
        org.get("name"),
        "points",
        user.get("points"),
        "enabled",
        bool(user.get("enabled")),
        "inviteCode",
        user.get("invite_code"),
        "createdAt",
        iso(user.get("created_at")));
  }

  public void logout(String token) {
    if (token != null) db.update("DELETE FROM auth_tokens WHERE token_hash=?", Crypto.hash(token));
  }

  public void password(Actor actor, Map<String, Object> input) {
    String old = required(input, "oldPassword", 200), next = required(input, "newPassword", 200);
    if (old.getBytes(StandardCharsets.UTF_8).length > 72) throw ApiException.bad("原密码不正确");
    validatePassword(next);
    tx.executeWithoutResult(
        status -> {
          Map<String, Object> user =
              db.one("SELECT * FROM users WHERE id=? FOR UPDATE", actor.id());
          if (str(user, "password_hash").isBlank()
              || !passwords.matches(old, str(user, "password_hash")))
            throw ApiException.bad("原密码不正确");
          db.update(
              "UPDATE users SET password_hash=? WHERE id=?", passwords.encode(next), actor.id());
          db.update("DELETE FROM auth_tokens WHERE user_id=?", actor.id());
          db.audit(actor, "PASSWORD_CHANGED", actor.id(), "修改密码并撤销现有登录会话");
        });
  }

  public static void validatePassword(String value) {
    if (value.length() < 12 || value.getBytes(StandardCharsets.UTF_8).length > 72)
      throw ApiException.bad("密码至少12字符且UTF-8编码不超过72字节");
  }
}

package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class Store {
  final JdbcTemplate jdbc;
  final Jsons json;
  final Crypto crypto;

  public Store(JdbcTemplate jdbc, Jsons json, Crypto crypto) {
    this.jdbc = jdbc;
    this.json = json;
    this.crypto = crypto;
  }

  public List<Map<String, Object>> rows(String sql, Object... args) {
    return jdbc.queryForList(sql, args);
  }

  public Map<String, Object> one(String sql, Object... args) {
    List<Map<String, Object>> rows = rows(sql, args);
    if (rows.isEmpty()) throw ApiException.missing();
    return rows.getFirst();
  }

  public Map<String, Object> maybe(String sql, Object... args) {
    List<Map<String, Object>> rows = rows(sql, args);
    return rows.isEmpty() ? null : rows.getFirst();
  }

  public int update(String sql, Object... args) {
    return jdbc.update(sql, args);
  }

  public String encode(Object value) {
    return crypto.encrypt(json.write(value));
  }

  public Map<String, Object> decode(Object value) {
    return json.read(crypto.decrypt(String.valueOf(value)));
  }

  public static Timestamp now() {
    return Timestamp.from(Instant.now());
  }

  public static Timestamp timestamp(Instant value) {
    return Timestamp.from(value);
  }

  public static Instant instant(Object value) {
    if (value instanceof Timestamp t) return t.toInstant();
    if (value instanceof java.time.LocalDateTime t) return t.toInstant(java.time.ZoneOffset.UTC);
    return Instant.parse(String.valueOf(value));
  }

  public static String iso(Object value) {
    return value == null ? null : instant(value).toString();
  }

  public void audit(Actor actor, String action, String target, String summary) {
    update(
        "INSERT INTO audit_logs(id,actor_id,action,target_id,summary,created_at)"
            + " VALUES(?,?,?,?,?,?)",
        id(),
        actor.id(),
        action,
        target,
        summary,
        now());
  }
}

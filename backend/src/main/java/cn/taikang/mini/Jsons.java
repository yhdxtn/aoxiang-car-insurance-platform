package cn.taikang.mini;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.*;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class Jsons {
  final ObjectMapper mapper;

  public Jsons(ObjectMapper mapper) {
    this.mapper = mapper;
  }

  public String write(Object data) {
    try {
      return mapper.writeValueAsString(data);
    } catch (Exception e) {
      throw new IllegalStateException("Cannot encode data");
    }
  }

  public Map<String, Object> read(String text) {
    try {
      return mapper.readValue(text, new TypeReference<LinkedHashMap<String, Object>>() {});
    } catch (Exception e) {
      throw new IllegalStateException("Cannot decode stored data");
    }
  }

  public static Map<String, Object> map(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }

  public static String str(Map<String, ?> map, String key) {
    Object value = map.get(key);
    return value == null ? "" : String.valueOf(value).trim();
  }

  public static String required(Map<String, ?> map, String key, int max) {
    String value = str(map, key);
    if (value.isBlank() || value.length() > max)
      throw ApiException.bad(key + " 必填且不能超过 " + max + " 字符");
    return value;
  }

  public static String limited(Map<String, ?> map, String key, int max) {
    String value = str(map, key);
    if (value.length() > max) throw ApiException.bad(key + " 内容过长");
    return value;
  }

  public static String id() {
    return UUID.randomUUID().toString();
  }

  public static String money(Object value) {
    try {
      return new BigDecimal(String.valueOf(value))
          .setScale(2, RoundingMode.HALF_UP)
          .toPlainString();
    } catch (Exception e) {
      throw ApiException.bad("金额格式错误");
    }
  }

  public static BigDecimal decimal(Object value, String label) {
    try {
      return new BigDecimal(String.valueOf(value));
    } catch (Exception e) {
      throw ApiException.bad(label + " 格式错误");
    }
  }

  public static boolean bool(Object value) {
    return Boolean.TRUE.equals(value)
        || "true".equals(String.valueOf(value))
        || "1".equals(String.valueOf(value));
  }

  public static long number(Object value) {
    return value instanceof Number n ? n.longValue() : Long.parseLong(String.valueOf(value));
  }

  public static LocalDate date(String value, String name) {
    try {
      return LocalDate.parse(value);
    } catch (Exception e) {
      throw ApiException.bad(name + " 应为 YYYY-MM-DD");
    }
  }

  public static Map<String, Object> page(List<Map<String, Object>> rows, int page, int size) {
    int safePage = Math.max(1, page), safeSize = Math.max(1, Math.min(100, size));
    int start = Math.min(rows.size(), (safePage - 1) * safeSize);
    return map(
        "items",
        rows.subList(start, Math.min(rows.size(), start + safeSize)),
        "total",
        rows.size(),
        "page",
        safePage,
        "size",
        safeSize);
  }
}

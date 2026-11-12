package cn.taikang.mini;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;

public record Actor(String id, String name, String role, String orgId) {
  public boolean is(String... roles) {
    return Set.of(roles).contains(role);
  }

  public void require(String... roles) {
    if (!is(roles)) throw ApiException.forbidden();
  }

  public static Actor from(HttpServletRequest request) {
    Actor actor = (Actor) request.getAttribute("actor");
    if (actor == null) throw new ApiException(401, "UNAUTHORIZED", "请重新登录");
    return actor;
  }
}

package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;

import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class Access {
  final Store db;

  public Access(Store db) {
    this.db = db;
  }

  public Set<String> descendants(String root) {
    List<Map<String, Object>> orgs = db.rows("SELECT id,parent_id FROM organizations");
    Set<String> ids = new LinkedHashSet<>();
    ids.add(root);
    boolean changed;
    do {
      changed = false;
      for (Map<String, Object> row : orgs)
        if (ids.contains(str(row, "parent_id"))) changed |= ids.add(str(row, "id"));
    } while (changed);
    return ids;
  }

  public Set<String> ancestors(String org) {
    Set<String> result = new LinkedHashSet<>();
    String current = org;
    while (!current.isBlank() && result.add(current)) {
      Map<String, Object> row = db.maybe("SELECT parent_id FROM organizations WHERE id=?", current);
      if (row == null) break;
      current = str(row, "parent_id");
    }
    return result;
  }

  public boolean record(Actor a, Map<String, Object> row) {
    return a.is("ADMIN", "FINANCE")
        || a.id().equals(str(row, "owner_id"))
        || a.is("AGENT") && descendants(a.orgId()).contains(str(row, "org_id"));
  }

  public boolean session(Actor a, Map<String, Object> row) {
    if (a.is("FINANCE")) return false;
    if (record(a, row)) return true;
    return a.is("SERVICE")
        && descendants(a.orgId()).contains(str(row, "org_id"))
        && (a.id().equals(str(row, "assigned_to"))
            || "WAITING".equals(str(row, "status")) && str(row, "assigned_to").isBlank());
  }

  public void sessionRead(Actor a, Map<String, Object> row) {
    if (!session(a, row)) throw ApiException.missing();
  }

  public void sessionWrite(Actor a, Map<String, Object> row) {
    sessionRead(a, row);
    if (a.is("SERVICE") && !a.id().equals(str(row, "assigned_to")))
      throw ApiException.conflict("请先领取会话，再处理用户资料");
  }

  public boolean org(Actor a, String id) {
    return a.is("ADMIN", "FINANCE") || descendants(a.orgId()).contains(id);
  }

  public void manageOrg(Actor a, String id) {
    a.require("ADMIN", "AGENT");
    if (!a.is("ADMIN") && !descendants(a.orgId()).contains(id)) throw ApiException.forbidden();
  }
}

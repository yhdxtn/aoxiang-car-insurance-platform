package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.util.Map;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

@Component
public class Bootstrap implements ApplicationRunner {
  final Store db;
  final AppConfig config;
  final AuthService auth;
  final Environment env;
  final TransactionTemplate tx;

  public Bootstrap(
      Store db, AppConfig config, AuthService auth, Environment env, TransactionTemplate tx) {
    this.db = db;
    this.config = config;
    this.auth = auth;
    this.env = env;
    this.tx = tx;
  }

  @Override
  public void run(ApplicationArguments args) {
    if (!config.demo() && !env.getProperty("spring.datasource.url", "").startsWith("jdbc:mysql:"))
      throw new IllegalStateException(
          "Live mode requires MySQL; use --spring.profiles.active=demo for offline demonstration");
    tx.executeWithoutResult(
        status -> {
          Map<String, Object> saved =
              db.maybe("SELECT * FROM app_metadata WHERE meta_key='environment_mode'");
          if (saved != null && !config.mode().equals(str(saved, "meta_value")))
            throw new IllegalStateException(
                "Do not mix demo and live data. Use a separate database.");
          if (saved == null)
            db.update(
                "INSERT INTO app_metadata(meta_key,meta_value) VALUES('environment_mode',?)",
                config.mode());
          if (!db.rows("SELECT id FROM users").isEmpty()) return;
          String org = id();
          db.update(
              "INSERT INTO organizations(id,name,parent_id,depth,enabled,created_at)"
                  + " VALUES(?,?,NULL,0,TRUE,?)",
              org,
              "总部",
              now());
          if (config.demo()) {
            create("admin", "DemoAdmin!2026", "演示管理员", "ADMIN", org);
            create("service", "DemoService!2026", "演示客服", "SERVICE", org);
            String agentOrg = id();
            db.update(
                "INSERT INTO organizations(id,name,parent_id,depth,enabled,created_at)"
                    + " VALUES(?,?,?,1,TRUE,?)",
                agentOrg,
                "昆明服务团队",
                org,
                now());
            create("agent", "DemoAgent!2026", "演示代理", "AGENT", agentOrg);
            create("customer", "DemoCustomer!2026", "演示客户", "CUSTOMER", agentOrg);
          } else {
            String password = config.bootstrapPassword();
            if (password == null
                || password.startsWith("replace-")
                || password.equals("DemoAdmin!2026"))
              throw new IllegalStateException(
                  "Set BOOTSTRAP_ADMIN_PASSWORD before first live start");
            AuthService.validatePassword(password);
            create("admin", password, "总部管理员", "ADMIN", org);
          }
        });
  }

  private void create(String username, String password, String name, String role, String org) {
    db.update(
        "INSERT INTO"
            + " users(id,username,password_hash,name,role,org_id,enabled,points,invite_code,created_at)"
            + " VALUES(?,?,?,?,?,?,TRUE,0,?,?)",
        id(),
        username,
        auth.passwords.encode(password),
        name,
        role,
        org,
        role.equals("AGENT") ? id().replace("-", "").substring(0, 16) : null,
        now());
  }
}

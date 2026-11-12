package cn.taikang.mini;

import static cn.taikang.mini.Actor.from;
import static cn.taikang.mini.Jsons.*;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1")
public class ApiController {
  final AuthService auth;
  final AppConfig config;
  final Sessions sessions;
  final Quotes quotes;
  final Orders orders;
  final Management management;
  final Gateway gateway;
  final Store db;

  public ApiController(
      AuthService auth,
      AppConfig config,
      Sessions sessions,
      Quotes quotes,
      Orders orders,
      Management management,
      Gateway gateway,
      Store db) {
    this.auth = auth;
    this.config = config;
    this.sessions = sessions;
    this.quotes = quotes;
    this.orders = orders;
    this.management = management;
    this.gateway = gateway;
    this.db = db;
  }

  @GetMapping("/public/config")
  Object config() {
    return map("mode", config.mode(), "insurer", "TAIKANG", "allowDemoLogin", config.demo());
  }

  @GetMapping("/public/health")
  Object health() {
    return map("status", "UP");
  }

  @PostMapping("/auth/login")
  Object login(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return auth.login(body, req.getRemoteAddr());
  }

  @PostMapping("/auth/wechat")
  Object wechat(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return auth.wechat(body, req.getRemoteAddr());
  }

  @GetMapping("/auth/me")
  Object me(HttpServletRequest req) {
    return auth.me(from(req));
  }

  @PostMapping("/auth/logout")
  Object logout(HttpServletRequest req) {
    auth.logout((String) req.getAttribute("token"));
    return map("ok", true);
  }

  @PutMapping("/auth/password")
  Object password(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    auth.password(from(req), body);
    return map("ok", true);
  }

  @PostMapping("/sessions")
  Object createSession(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return sessions.create(from(req), body);
  }

  @GetMapping("/sessions")
  Object sessions(
      @RequestParam(defaultValue = "") String status,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      HttpServletRequest req) {
    return sessions.list(from(req), status, page, size);
  }

  @GetMapping("/sessions/{id}")
  Object session(@PathVariable String id, HttpServletRequest req) {
    quotes.expirePending(from(req), id);
    return sessions.get(from(req), id);
  }

  @GetMapping("/sessions/{id}/messages")
  Object messages(
      @PathVariable String id,
      @RequestParam(defaultValue = "0") long after,
      HttpServletRequest req) {
    return sessions.messages(from(req), id, after);
  }

  @PostMapping("/sessions/{id}/messages")
  Object postMessage(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return sessions.postMessage(from(req), id, body);
  }

  @PostMapping("/sessions/{id}/handoff")
  Object handoff(
      @PathVariable String id,
      @RequestBody(required = false) Map<String, Object> body,
      HttpServletRequest req) {
    return sessions.handoff(from(req), id, body == null ? map() : body);
  }

  @PostMapping("/sessions/{id}/claim")
  Object claim(@PathVariable String id, HttpServletRequest req) {
    return sessions.claim(from(req), id);
  }

  @PostMapping("/sessions/{id}/transfer")
  Object transfer(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return sessions.transfer(from(req), id, body);
  }

  @PostMapping("/sessions/{id}/close")
  Object close(@PathVariable String id, HttpServletRequest req) {
    return sessions.close(from(req), id);
  }

  @PutMapping("/sessions/{id}/vehicle")
  Object vehicle(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return sessions.vehicle(from(req), id, body);
  }

  @PostMapping(value = "/sessions/{id}/files", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
  Object upload(
      @PathVariable String id,
      @RequestParam("file") MultipartFile file,
      @RequestParam(defaultValue = "DRIVING_LICENSE") String documentType,
      @RequestParam(defaultValue = "WEB") String source,
      HttpServletRequest req) {
    return sessions.upload(from(req), id, file, documentType, source);
  }

  @GetMapping("/files/{id}")
  ResponseEntity<byte[]> file(@PathVariable String id, HttpServletRequest req) {
    Sessions.FileData f = sessions.file(from(req), id);
    return ResponseEntity.ok()
        .contentType(MediaType.parseMediaType(f.mimeType()))
        .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"document\"")
        .cacheControl(CacheControl.noStore())
        .body(f.bytes());
  }

  @PostMapping("/sessions/{id}/ocr")
  Object ocr(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return sessions.ocr(from(req), id, body);
  }

  @PostMapping("/sessions/{id}/quotes")
  Object quote(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return quotes.quote(from(req), id, body);
  }

  @PostMapping("/sessions/{id}/orders")
  Object order(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return orders.create(from(req), id, body);
  }

  @GetMapping("/orders")
  Object orders(
      @RequestParam(defaultValue = "") String search,
      @RequestParam(defaultValue = "") String status,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      HttpServletRequest req) {
    return orders.list(from(req), search, status, page, size);
  }

  @GetMapping("/orders/{id}")
  Object order(@PathVariable String id, HttpServletRequest req) {
    return orders.get(from(req), id);
  }

  @PatchMapping("/orders/{id}/status")
  Object orderStatus(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return orders.change(from(req), id, body);
  }

  @GetMapping("/customers")
  Object customers(
      @RequestParam(defaultValue = "") String search,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      HttpServletRequest req) {
    return management.customers(from(req), search, page, size);
  }

  @PostMapping("/customers")
  Object createCustomer(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.createCustomer(from(req), body);
  }

  @PutMapping("/customers/{id}")
  Object customer(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.updateCustomer(from(req), id, body);
  }

  @GetMapping("/dashboard")
  Object dashboard(HttpServletRequest req) {
    return management.dashboard(from(req));
  }

  @GetMapping("/organizations")
  Object organizations(HttpServletRequest req) {
    return management.organizations(from(req));
  }

  @PostMapping("/organizations")
  Object createOrganization(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.createOrganization(from(req), body);
  }

  @PatchMapping("/organizations/{id}")
  Object organization(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.updateOrganization(from(req), id, body);
  }

  @GetMapping("/users")
  Object users(
      @RequestParam(defaultValue = "") String role,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      HttpServletRequest req) {
    return management.users(from(req), role, page, size);
  }

  @PostMapping("/users")
  Object createUser(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.createUser(from(req), body);
  }

  @PatchMapping("/users/{id}")
  Object user(
      @PathVariable String id, @RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.updateUser(from(req), id, body);
  }

  @GetMapping("/policies")
  Object policies(@RequestParam(defaultValue = "false") boolean history, HttpServletRequest req) {
    return management.policies(from(req), history);
  }

  @PostMapping("/policies")
  Object policy(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.createPolicy(from(req), body);
  }

  @GetMapping("/finance")
  Object finance(HttpServletRequest req) {
    return orders.finance(from(req));
  }

  @GetMapping("/points")
  Object points(HttpServletRequest req) {
    return management.points(from(req));
  }

  @PostMapping("/points/adjust")
  Object points(@RequestBody Map<String, Object> body, HttpServletRequest req) {
    return management.adjustPoints(from(req), body);
  }

  @GetMapping("/audit")
  Object audit(
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      HttpServletRequest req) {
    return management.audit(from(req), page, size);
  }

  @GetMapping("/settings/taikang")
  Object taikang(HttpServletRequest req) {
    from(req).require("ADMIN");
    return gateway.settings();
  }

  @PostMapping("/settings/taikang/check")
  Object check(HttpServletRequest req) {
    Actor actor = from(req);
    actor.require("ADMIN");
    Map<String, Object> result = gateway.check();
    db.audit(actor, "TAIKANG_LOGIN_CHECK", "TAIKANG", str(result, "status"));
    return result;
  }

  @GetMapping("/service/agents")
  Object agents(HttpServletRequest req) {
    return management.serviceAgents(from(req));
  }
}

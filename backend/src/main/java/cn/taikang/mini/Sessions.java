package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;
import static cn.taikang.mini.Store.*;

import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;

@Service
public class Sessions {
  final Store db;
  final Access access;
  final TransactionTemplate tx;
  final AppConfig config;
  final Gateway gateway;

  public Sessions(
      Store db, Access access, TransactionTemplate tx, AppConfig config, Gateway gateway) {
    this.db = db;
    this.access = access;
    this.tx = tx;
    this.config = config;
    this.gateway = gateway;
  }

  public Map<String, Object> raw(Actor actor, String sid, boolean lock, boolean write) {
    Map<String, Object> row =
        db.one("SELECT * FROM quote_sessions WHERE id=?" + (lock ? " FOR UPDATE" : ""), sid);
    if (write) access.sessionWrite(actor, row);
    else access.sessionRead(actor, row);
    return row;
  }

  public void editable(Map<String, Object> session) {
    if ("CLOSED".equals(str(session, "status"))) throw ApiException.conflict("会话已关闭，资料只读");
    if (!str(session, "order_id").isBlank()) throw ApiException.conflict("已生成投保申请，请在订单中跟进；资料不能再变更");
  }

  public Map<String, Object> create(Actor actor, Map<String, Object> input) {
    actor.require("CUSTOMER", "AGENT", "ADMIN");
    String type = required(input, "vehicleType", 20);
    type(type);
    return tx.execute(
        status -> {
          String sid = id();
          boolean manual = "MOTORCYCLE".equals(type);
          db.update(
              "INSERT INTO"
                  + " quote_sessions(id,owner_id,org_id,vehicle_type,status,stage,vehicle_data,created_at,updated_at)"
                  + " VALUES(?,?,?,?,?,1,?,?,?)",
              sid,
              actor.id(),
              actor.orgId(),
              type,
              manual ? "WAITING" : "BOT",
              db.encode(map()),
              now(),
              now());
          message(
              sid,
              "SYSTEM",
              "ASSISTANT",
              manual
                  ? "摩托车业务由人工客服处理，已为你转接。可以先上传行驶证或填写资料。"
                  : "你好，我是你的车险助手。先上传行驶证，我来帮你整理车辆信息，也可以手动填写。",
              null,
              id());
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public static void type(String type) {
    if (!Set.of("CAR", "TRUCK", "MOTORCYCLE").contains(type)) throw ApiException.bad("不支持的车辆类型");
  }

  public Map<String, Object> list(Actor actor, String status, int page, int size) {
    actor.require("ADMIN", "AGENT", "CUSTOMER", "SERVICE");
    List<Map<String, Object>> rows =
        db.rows("SELECT * FROM quote_sessions ORDER BY updated_at DESC");
    List<Map<String, Object>> visible =
        rows.stream()
            .filter(r -> access.session(actor, r))
            .filter(r -> status == null || status.isBlank() || status.equals(str(r, "status")))
            .map(this::view)
            .toList();
    return page(visible, page, size);
  }

  public Map<String, Object> get(Actor actor, String id) {
    return view(raw(actor, id, false, false));
  }

  public Map<String, Object> view(Map<String, Object> row) {
    String sid = str(row, "id");
    Map<String, Object> owner = db.one("SELECT name FROM users WHERE id=?", row.get("owner_id"));
    List<Map<String, Object>> quotes =
        db.rows("SELECT * FROM quotes WHERE session_id=? ORDER BY revision DESC", sid).stream()
            .map(this::quoteView)
            .toList();
    return map(
        "id",
        sid,
        "vehicleType",
        row.get("vehicle_type"),
        "status",
        row.get("status"),
        "stage",
        row.get("stage"),
        "ownerId",
        row.get("owner_id"),
        "ownerName",
        owner.get("name"),
        "orgId",
        row.get("org_id"),
        "assignedTo",
        row.get("assigned_to"),
        "vehicle",
        db.decode(row.get("vehicle_data")),
        "quotes",
        quotes,
        "orderId",
        row.get("order_id"),
        "createdAt",
        iso(row.get("created_at")),
        "updatedAt",
        iso(row.get("updated_at")),
        "demo",
        config.demo());
  }

  public Map<String, Object> quoteView(Map<String, Object> row) {
    Map<String, Object> out = new LinkedHashMap<>(db.decode(row.get("result_data")));
    out.putAll(
        map(
            "id",
            row.get("id"),
            "sessionId",
            row.get("session_id"),
            "insurer",
            "TAIKANG",
            "plan",
            row.get("plan"),
            "status",
            row.get("status"),
            "revision",
            row.get("revision"),
            "demo",
            bool(row.get("demo")),
            "validUntil",
            iso(row.get("valid_until"))));
    return out;
  }

  public Map<String, Object> messages(Actor actor, String sid, long after) {
    raw(actor, sid, false, false);
    List<Map<String, Object>> rows =
        db.rows(
            "SELECT m.*,f.file_name FROM chat_messages m LEFT JOIN private_files f ON"
                + " f.id=m.file_id WHERE m.session_id=? AND m.seq>? ORDER BY m.seq LIMIT 200",
            sid,
            Math.max(0, after));
    List<Map<String, Object>> out = rows.stream().map(this::messageView).toList();
    long cursor = rows.isEmpty() ? Math.max(0, after) : number(rows.getLast().get("seq"));
    return map("items", out, "cursor", cursor, "hasMore", rows.size() == 200);
  }

  Map<String, Object> messageView(Map<String, Object> row) {
    return map(
        "id",
        row.get("id"),
        "seq",
        row.get("seq"),
        "role",
        row.get("message_role"),
        "content",
        db.crypto.decrypt(str(row, "content_data")),
        "fileId",
        row.get("file_id"),
        "fileName",
        row.get("file_name"),
        "createdAt",
        iso(row.get("created_at")));
  }

  public Map<String, Object> postMessage(Actor actor, String sid, Map<String, Object> input) {
    String key = required(input, "clientMessageId", 100),
        text = limited(input, "content", 4000),
        fid = limited(input, "fileId", 36);
    if (text.isBlank() && fid.isBlank()) throw ApiException.bad("请填写消息或选择图片");
    return tx.execute(
        status -> {
          Map<String, Object> session = raw(actor, sid, true, true);
          if ("CLOSED".equals(str(session, "status"))) throw ApiException.conflict("会话已关闭");
          Map<String, Object> old =
              db.maybe(
                  "SELECT m.*,f.file_name FROM chat_messages m LEFT JOIN private_files f ON"
                      + " f.id=m.file_id WHERE m.session_id=? AND m.sender_id=? AND"
                      + " m.client_message_id=?",
                  sid,
                  actor.id(),
                  key);
          if (old != null) {
            if (!text.equals(db.crypto.decrypt(str(old, "content_data")))
                || !fid.equals(str(old, "file_id"))) throw ApiException.conflict("消息幂等键不能用于不同内容");
            return messageView(old);
          }
          if (!fid.isBlank()) {
            Map<String, Object> f = db.one("SELECT * FROM private_files WHERE id=?", fid);
            if (!sid.equals(str(f, "session_id"))) throw ApiException.bad("图片不属于当前会话");
          }
          Map<String, Object> msg =
              message(
                  sid,
                  actor.id(),
                  actor.is("SERVICE", "ADMIN") ? "SERVICE" : "USER",
                  text,
                  fid.isBlank() ? null : fid,
                  key);
          if (actor.is("CUSTOMER", "AGENT")
              && text.contains("人工")
              && "BOT".equals(str(session, "status"))) {
            db.update(
                "UPDATE quote_sessions SET status='WAITING',updated_at=? WHERE id=?", now(), sid);
            message(sid, "SYSTEM", "ASSISTANT", "已为你转接人工客服，请稍候。", null, id());
          }
          return msg;
        });
  }

  public Map<String, Object> message(
      String sid, String sender, String role, String content, String fileId, String key) {
    Map<String, Object> s =
        db.one("SELECT message_seq FROM quote_sessions WHERE id=? FOR UPDATE", sid);
    long seq = number(s.get("message_seq")) + 1;
    String mid = id();
    db.update("UPDATE quote_sessions SET message_seq=?,updated_at=? WHERE id=?", seq, now(), sid);
    db.update(
        "INSERT INTO"
            + " chat_messages(id,session_id,seq,sender_id,message_role,content_data,file_id,client_message_id,created_at)"
            + " VALUES(?,?,?,?,?,?,?,?,?)",
        mid,
        sid,
        seq,
        sender,
        role,
        db.crypto.encrypt(content),
        fileId,
        key,
        now());
    return messageView(
        db.one(
            "SELECT m.*,f.file_name FROM chat_messages m LEFT JOIN private_files f ON"
                + " f.id=m.file_id WHERE m.id=?",
            mid));
  }

  public Map<String, Object> handoff(Actor actor, String sid, Map<String, Object> input) {
    return tx.execute(
        status -> {
          Map<String, Object> s = raw(actor, sid, true, false);
          if ("CLOSED".equals(str(s, "status"))) throw ApiException.conflict("会话已关闭");
          if (Set.of("WAITING", "ACTIVE").contains(str(s, "status"))) return view(s);
          db.update(
              "UPDATE quote_sessions SET status='WAITING',updated_at=? WHERE id=?", now(), sid);
          message(sid, "SYSTEM", "SYSTEM", "已转人工客服。" + limited(input, "reason", 500), null, id());
          db.audit(actor, "SESSION_HANDOFF", sid, "转入人工队列");
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public Map<String, Object> claim(Actor actor, String sid) {
    actor.require("SERVICE", "ADMIN");
    return tx.execute(
        status -> {
          Map<String, Object> s = raw(actor, sid, true, false);
          if (actor.id().equals(str(s, "assigned_to")) && "ACTIVE".equals(str(s, "status")))
            return view(s);
          if (!"WAITING".equals(str(s, "status")) || !str(s, "assigned_to").isBlank())
            throw ApiException.conflict("会话已被领取或不在等待队列");
          db.update(
              "UPDATE quote_sessions SET assigned_to=?,status='ACTIVE',updated_at=? WHERE id=?",
              actor.id(),
              now(),
              sid);
          message(sid, "SYSTEM", "SYSTEM", actor.name() + " 已接入会话。", null, id());
          db.audit(actor, "SESSION_CLAIM", sid, "客服领取会话");
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public Map<String, Object> transfer(Actor actor, String sid, Map<String, Object> input) {
    actor.require("SERVICE", "ADMIN");
    String to = required(input, "serviceUserId", 36);
    return tx.execute(
        status -> {
          Map<String, Object> s = raw(actor, sid, true, true);
          if (!"ACTIVE".equals(str(s, "status"))) throw ApiException.conflict("仅接待中的会话可以转接");
          Map<String, Object> user =
              db.one("SELECT * FROM users WHERE id=? AND role='SERVICE' AND enabled=TRUE", to);
          if (!access.descendants(str(user, "org_id")).contains(str(s, "org_id")))
            throw ApiException.bad("目标客服无权处理该组织会话");
          db.update(
              "UPDATE quote_sessions SET assigned_to=?,updated_at=? WHERE id=?", to, now(), sid);
          message(sid, "SYSTEM", "SYSTEM", "会话已转接给 " + user.get("name") + "。", null, id());
          db.audit(actor, "SESSION_TRANSFER", sid, "客服转接");
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public Map<String, Object> close(Actor actor, String sid) {
    actor.require("SERVICE", "ADMIN");
    return tx.execute(
        status -> {
          Map<String, Object> s = raw(actor, sid, true, true);
          if ("CLOSED".equals(str(s, "status"))) return view(s);
          if (db.maybe("SELECT id FROM quotes WHERE session_id=? AND status='PROCESSING'", sid)
              != null) throw ApiException.conflict("报价正在处理中，不能关闭会话，请等待确定结果");
          db.update(
              "UPDATE quote_sessions SET status='CLOSED',updated_at=? WHERE id=?", now(), sid);
          message(sid, "SYSTEM", "SYSTEM", "本次服务已结束，历史记录可继续查看。", null, id());
          db.audit(actor, "SESSION_CLOSED", sid, "关闭人工会话");
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public Map<String, Object> vehicle(Actor actor, String sid, Map<String, Object> input) {
    Map<String, Object> clean = validateVehicle(input);
    return tx.execute(
        status -> {
          Map<String, Object> s = raw(actor, sid, true, true);
          editable(s);
          if (db.maybe(
                  "SELECT id FROM quotes WHERE session_id=? AND status IN"
                      + " ('PROCESSING','OUTCOME_UNKNOWN')",
                  sid)
              != null) throw ApiException.conflict("报价处理中或结果待核实，不能更改资料");
          if (clean.containsKey("vehicleType")
              && !str(clean, "vehicleType").equals(str(s, "vehicle_type")))
            throw ApiException.bad("车辆类型需与会话入口保持一致");
          clean.put("vehicleType", s.get("vehicle_type"));
          db.update(
              "UPDATE quote_sessions SET"
                  + " vehicle_data=?,vehicle_revision=vehicle_revision+1,stage=2,updated_at=? WHERE"
                  + " id=?",
              db.encode(clean),
              now(),
              sid);
          db.update(
              "UPDATE quotes SET status='SUPERSEDED' WHERE session_id=? AND status='QUOTED'", sid);
          message(
              sid,
              "SYSTEM",
              "ASSISTANT",
              Set.of("MOTORCYCLE", "TRUCK").contains(str(s, "vehicle_type"))
                  ? "资料已保存，人工客服将协助核对与报价。"
                  : "车辆信息已保存，请核对后选择泰康报价方案。",
              null,
              id());
          Map<String, Object> customer =
              db.maybe("SELECT * FROM customers WHERE source_session_id=?", sid);
          Map<String, Object> detail =
              map(
                  "name",
                  clean.get("ownerName"),
                  "phone",
                  clean.get("phone"),
                  "plateNo",
                  clean.get("plateNo"),
                  "notes",
                  customer == null
                      ? ""
                      : db.decode(customer.get("details_data")).getOrDefault("notes", ""));
          if (customer == null)
            db.update(
                "INSERT INTO"
                    + " customers(id,source_session_id,owner_id,org_id,details_data,created_at,updated_at)"
                    + " VALUES(?,?,?,?,?,?,?)",
                id(),
                sid,
                s.get("owner_id"),
                s.get("org_id"),
                db.encode(detail),
                now(),
                now());
          else
            db.update(
                "UPDATE customers SET details_data=?,updated_at=? WHERE id=?",
                db.encode(detail),
                now(),
                customer.get("id"));
          db.audit(actor, "VEHICLE_CONFIRMED", sid, "用户或授权人员确认车辆资料");
          return view(db.one("SELECT * FROM quote_sessions WHERE id=?", sid));
        });
  }

  public Map<String, Object> validateVehicle(Map<String, Object> input) {
    Map<String, Object> clean = new LinkedHashMap<>();
    Set<String> keys =
        Set.of(
            "plateNo",
            "vin",
            "engineNo",
            "brandModel",
            "registerDate",
            "issueDate",
            "ownerName",
            "idNumber",
            "address",
            "phone",
            "vehicleType",
            "useNature",
            "selectedModelCode");
    for (String key : keys) {
      String value = limited(input, key, key.equals("address") ? 300 : 120);
      if (!value.isBlank()) clean.put(key, value);
    }
    String vin = str(clean, "vin").toUpperCase(Locale.ROOT);
    if (!vin.isBlank() && !vin.matches("[A-HJ-NPR-Z0-9]{17}"))
      throw ApiException.bad("车架号应为17位字母数字，不含I、O、Q");
    if (!vin.isBlank()) clean.put("vin", vin);
    String phone = str(clean, "phone");
    if (!phone.isBlank() && !phone.matches("1[3-9]\\d{9}")) throw ApiException.bad("请输入正确的11位手机号");
    String idnum = str(clean, "idNumber").toUpperCase(Locale.ROOT);
    if (!idnum.isBlank() && !idnum.matches("[0-9]{17}[0-9X]")) throw ApiException.bad("身份证号应为18位");
    if (!idnum.isBlank()) clean.put("idNumber", idnum);
    for (String key : List.of("registerDate", "issueDate")) {
      String d = str(clean, key);
      if (!d.isBlank() && date(d, key).isAfter(LocalDate.now(ZoneId.of("Asia/Shanghai"))))
        throw ApiException.bad("证件日期不能晚于今天");
    }
    if (input.containsKey("seatCount") && !str(input, "seatCount").isBlank()) {
      try {
        int seats = Integer.parseInt(str(input, "seatCount"));
        if (seats < 1 || seats > 100) throw new NumberFormatException();
        clean.put("seatCount", seats);
      } catch (NumberFormatException e) {
        throw ApiException.bad("座位数须为1至100的整数");
      }
    }
    if (!str(clean, "vehicleType").isBlank()) type(str(clean, "vehicleType"));
    return clean;
  }

  public Map<String, Object> upload(
      Actor actor, String sid, MultipartFile file, String documentType, String source) {
    raw(actor, sid, false, true);
    if (!Set.of("DRIVING_LICENSE", "ID_CARD", "OTHER").contains(documentType)
        || !Set.of("ALBUM", "CHAT", "CAMERA", "WEB").contains(source))
      throw ApiException.bad("文件来源或证件类型不正确");
    if (file.isEmpty() || file.getSize() > 10 * 1024 * 1024) throw ApiException.bad("请选择10MB以内的图片");
    byte[] bytes;
    try {
      bytes = file.getBytes();
    } catch (Exception e) {
      throw ApiException.bad("无法读取图片");
    }
    String mime = imageType(bytes);
    String fid = id();
    Path root = Path.of(config.uploadDir()).toAbsolutePath().normalize();
    Path dest = root.resolve(fid + ".enc");
    String filename =
        Optional.ofNullable(file.getOriginalFilename())
            .orElse("证件图片")
            .replaceAll("[\\\\/\\p{Cntrl}]", "_");
    if (filename.length() > 180) filename = filename.substring(filename.length() - 180);
    final String savedName = filename;
    try {
      Files.createDirectories(root);
      Files.write(dest, db.crypto.encryptBytes(bytes), StandardOpenOption.CREATE_NEW);
      try {
        return tx.execute(
            status -> {
              Map<String, Object> s = raw(actor, sid, true, true);
              if ("CLOSED".equals(str(s, "status"))) throw ApiException.conflict("会话已关闭");
              db.update(
                  "INSERT INTO"
                      + " private_files(id,session_id,uploader_id,file_name,mime_type,file_size,storage_name,source,document_type,created_at)"
                      + " VALUES(?,?,?,?,?,?,?,?,?,?)",
                  fid,
                  sid,
                  actor.id(),
                  savedName,
                  mime,
                  bytes.length,
                  fid + ".enc",
                  source,
                  documentType,
                  now());
              db.audit(actor, "DOCUMENT_UPLOADED", fid, "上传私有证件图片");
              return map("id", fid, "fileName", savedName, "mimeType", mime, "size", bytes.length);
            });
      } catch (RuntimeException e) {
        Files.deleteIfExists(dest);
        throw e;
      }
    } catch (ApiException e) {
      throw e;
    } catch (Exception e) {
      throw new ApiException(500, "FILE_SAVE_FAILED", "图片保存失败，请重试");
    }
  }

  public static String imageType(byte[] bytes) {
    if (bytes.length >= 3
        && (bytes[0] & 255) == 255
        && (bytes[1] & 255) == 216
        && (bytes[2] & 255) == 255) return "image/jpeg";
    if (bytes.length >= 8
        && Arrays.equals(
            Arrays.copyOf(bytes, 8), new byte[] {(byte) 137, 80, 78, 71, 13, 10, 26, 10}))
      return "image/png";
    if (bytes.length >= 12
        && new String(bytes, 0, 4, java.nio.charset.StandardCharsets.US_ASCII).equals("RIFF")
        && new String(bytes, 8, 4, java.nio.charset.StandardCharsets.US_ASCII).equals("WEBP"))
      return "image/webp";
    throw ApiException.bad("仅支持JPEG、PNG、WEBP真实图片文件");
  }

  public record FileData(byte[] bytes, String mimeType, String fileName) {}

  public FileData file(Actor actor, String fid) {
    Map<String, Object> f = db.one("SELECT * FROM private_files WHERE id=?", fid);
    raw(actor, str(f, "session_id"), false, false);
    try {
      Path root = Path.of(config.uploadDir()).toAbsolutePath().normalize(),
          p = root.resolve(str(f, "storage_name")).normalize();
      if (!p.getParent().equals(root)) throw new IllegalStateException();
      return new FileData(
          db.crypto.decryptBytes(Files.readAllBytes(p)), str(f, "mime_type"), str(f, "file_name"));
    } catch (Exception e) {
      throw new ApiException(404, "FILE_UNAVAILABLE", "图片暂不可读取，请联系管理员");
    }
  }

  public Map<String, Object> ocr(Actor actor, String sid, Map<String, Object> input) {
    raw(actor, sid, false, true);
    String fid = required(input, "fileId", 36);
    Map<String, Object> f =
        db.one("SELECT * FROM private_files WHERE id=? AND session_id=?", fid, sid);
    if (config.demo())
      return map(
          "status", "MANUAL_REQUIRED", "vehicle", map(), "message", "演示模式未调用证件识别，请手动填写并核对车辆信息");
    FileData data = file(actor, fid);
    if (!config.gatewayConfigured())
      return map("status", "MANUAL_REQUIRED", "vehicle", map(), "message", "识别服务尚未配置，请手动填写车辆信息");
    Map<String, Object> result;
    try {
      result =
          gateway.call(
              "/internal/ocr",
              map(
                  "imageBase64",
                  Base64.getEncoder().encodeToString(data.bytes()),
                  "mimeType",
                  data.mimeType(),
                  "documentType",
                  f.get("document_type")));
    } catch (ApiException e) {
      return map("status", "MANUAL_REQUIRED", "vehicle", map(), "message", "识别服务暂不可用，请手动核对并填写资料");
    }
    if (!Set.of("RECOGNIZED", "MANUAL_REQUIRED").contains(str(result, "status")))
      return map("status", "MANUAL_REQUIRED", "vehicle", map(), "message", "识别结果需要人工核对");
    return result;
  }
}

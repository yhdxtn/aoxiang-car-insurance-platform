package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;

import java.util.*;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

@RestControllerAdvice
public class Errors {
  @ExceptionHandler(ApiException.class)
  public ResponseEntity<?> api(ApiException e) {
    return ResponseEntity.status(e.status).body(map("code", e.code, "message", e.getMessage()));
  }

  @ExceptionHandler(MaxUploadSizeExceededException.class)
  public ResponseEntity<?> upload() {
    return ResponseEntity.status(413).body(map("code", "FILE_TOO_LARGE", "message", "图片不得超过10MB"));
  }

  @ExceptionHandler({
    HttpMessageNotReadableException.class,
    org.springframework.web.bind.MissingServletRequestParameterException.class,
    org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class
  })
  public ResponseEntity<?> invalid() {
    return ResponseEntity.badRequest().body(map("code", "INVALID_REQUEST", "message", "请求格式不正确"));
  }

  @ExceptionHandler(DataIntegrityViolationException.class)
  public ResponseEntity<?> conflict() {
    return ResponseEntity.status(409)
        .body(map("code", "DATA_CONFLICT", "message", "记录已存在或被其他操作更新，请刷新后核对"));
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<?> unexpected(Exception error) {
    String trace = id();
    org.slf4j.LoggerFactory.getLogger(Errors.class)
        .error("Request failed [{}], type={}", trace, error.getClass().getSimpleName());
    return ResponseEntity.status(500)
        .body(map("code", "INTERNAL_ERROR", "message", "服务处理失败，请联系管理员并提供追踪编号", "traceId", trace));
  }
}

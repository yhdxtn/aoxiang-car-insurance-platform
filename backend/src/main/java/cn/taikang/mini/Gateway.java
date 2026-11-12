package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class Gateway {
  final AppConfig config;
  final Jsons json;
  final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
  volatile String loginStatus = "UNCHECKED";

  public Gateway(AppConfig config, Jsons json) {
    this.config = config;
    this.json = json;
  }

  public Map<String, Object> call(String endpoint, Map<String, Object> body) {
    if (!config.gatewayConfigured())
      throw new ApiException(503, "TAIKANG_NOT_CONFIGURED", "泰康服务尚未配置，请联系管理员");
    try {
      URI uri = URI.create(config.tkGatewayUrl().replaceAll("/+$", "") + endpoint);
      if (!Set.of("http", "https").contains(uri.getScheme()) || uri.getUserInfo() != null)
        throw new IllegalStateException();
      if (!"https".equals(uri.getScheme())
          && !Set.of("localhost", "127.0.0.1", "::1", "taikang-gateway").contains(uri.getHost()))
        throw new ApiException(503, "GATEWAY_TLS_REQUIRED", "跨主机泰康网关必须使用HTTPS");
      HttpRequest request =
          HttpRequest.newBuilder(uri)
              .timeout(Duration.ofSeconds(Math.max(10, Math.min(300, config.tkTimeoutSeconds()))))
              .header("Content-Type", "application/json")
              .header("X-Gateway-Token", config.tkGatewayToken())
              .POST(HttpRequest.BodyPublishers.ofString(json.write(body)))
              .build();
      HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
      if (response.statusCode() != 200)
        throw new ApiException(502, "GATEWAY_ERROR", "泰康服务返回异常，请交由客服核实");
      Map<String, Object> result = json.read(response.body());
      if (result.isEmpty()) throw new IllegalStateException();
      return result;
    } catch (ApiException e) {
      throw e;
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new ApiException(504, "GATEWAY_OUTCOME_UNKNOWN", "请求中断，报价结果待人工核实，不会自动重试");
    } catch (Exception e) {
      throw new ApiException(504, "GATEWAY_OUTCOME_UNKNOWN", "请求未获得确定结果，请由客服核实，不会自动重试");
    }
  }

  public Map<String, Object> check() {
    if (config.demo()) return map("status", "DEMO", "message", "演示模式未连接泰康，不代表真实登录成功");
    Map<String, Object> result = call("/internal/login-check", map());
    loginStatus = str(result, "status");
    return result;
  }

  public Map<String, Object> settings() {
    return map(
        "enabled",
        config.gatewayConfigured() && !config.demo(),
        "mode",
        config.mode(),
        "gatewayConfigured",
        config.gatewayConfigured(),
        "accountMasked",
        config.tkAccountLabel(),
        "loginStatus",
        config.demo() ? "DEMO" : loginStatus,
        "message",
        config.demo() ? "演示环境不会调用真实泰康接口" : "登录凭据仅由独立网关环境配置，平台不向浏览器返回密码");
  }
}

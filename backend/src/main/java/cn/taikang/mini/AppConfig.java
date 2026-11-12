package cn.taikang.mini;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public record AppConfig(
    String mode,
    String encryptionKey,
    String uploadDir,
    String corsOrigins,
    String bootstrapPassword,
    int tokenHours,
    String wechatAppid,
    String wechatSecret,
    String tkGatewayUrl,
    String tkGatewayToken,
    String tkAccountLabel,
    int tkTimeoutSeconds) {
  public boolean demo() {
    return "demo".equals(mode);
  }

  public boolean gatewayConfigured() {
    return tkGatewayUrl != null
        && !tkGatewayUrl.isBlank()
        && tkGatewayToken != null
        && !tkGatewayToken.isBlank();
  }
}

package cn.taikang.mini;

import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

@Component
public class Crypto {
  private final AppConfig config;
  private SecretKeySpec key;
  private final SecureRandom random = new SecureRandom();

  public Crypto(AppConfig config) {
    this.config = config;
  }

  @PostConstruct
  void initialize() {
    if (!Set.of("demo", "live").contains(config.mode()))
      throw new IllegalStateException("APP mode must be demo or live");
    try {
      byte[] bytes = Base64.getDecoder().decode(config.encryptionKey());
      if (bytes.length != 32) throw new IllegalArgumentException();
      key = new SecretKeySpec(bytes, "AES");
    } catch (Exception e) {
      throw new IllegalStateException(
          "DATA_ENCRYPTION_KEY must be base64 encoding of 32 random bytes");
    }
  }

  public String encrypt(String value) {
    return Base64.getEncoder().encodeToString(encryptBytes(value.getBytes(StandardCharsets.UTF_8)));
  }

  public String decrypt(String value) {
    return new String(decryptBytes(Base64.getDecoder().decode(value)), StandardCharsets.UTF_8);
  }

  public byte[] encryptBytes(byte[] value) {
    try {
      byte[] iv = new byte[12];
      random.nextBytes(iv);
      Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
      c.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(128, iv));
      byte[] encrypted = c.doFinal(value);
      byte[] out = new byte[12 + encrypted.length];
      System.arraycopy(iv, 0, out, 0, 12);
      System.arraycopy(encrypted, 0, out, 12, encrypted.length);
      return out;
    } catch (Exception e) {
      throw new IllegalStateException("Cannot encrypt data");
    }
  }

  public byte[] decryptBytes(byte[] value) {
    try {
      Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
      c.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, Arrays.copyOf(value, 12)));
      return c.doFinal(Arrays.copyOfRange(value, 12, value.length));
    } catch (Exception e) {
      throw new IllegalStateException("Cannot decrypt data; retain the original data key");
    }
  }

  public String token() {
    byte[] bytes = new byte[32];
    random.nextBytes(bytes);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
  }

  public static String hash(String value) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
}

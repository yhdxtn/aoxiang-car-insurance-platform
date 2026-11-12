package cn.taikang.mini;

import static cn.taikang.mini.Jsons.*;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.*;
import org.springframework.context.annotation.*;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.config.annotation.*;

@Configuration
public class WebConfiguration implements WebMvcConfigurer {
  final AppConfig config;

  public WebConfiguration(AppConfig config) {
    this.config = config;
  }

  @Override
  public void addCorsMappings(CorsRegistry registry) {
    registry
        .addMapping("/api/**")
        .allowedOrigins(
            Arrays.stream(config.corsOrigins().split(","))
                .map(String::trim)
                .filter(v -> !v.isBlank())
                .toArray(String[]::new))
        .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        .allowedHeaders("Authorization", "Content-Type", "X-Request-ID")
        .maxAge(600);
  }

  @Bean
  public OncePerRequestFilter authFilter(AuthService auth, Jsons json) {
    return new OncePerRequestFilter() {
      @Override
      protected void doFilterInternal(
          HttpServletRequest req, HttpServletResponse res, FilterChain chain)
          throws ServletException, IOException {
        res.setHeader("X-Content-Type-Options", "nosniff");
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Referrer-Policy", "no-referrer");
        String path = req.getRequestURI();
        try {
          if (path.startsWith("/api/")
              && !Set.of(
                      "/api/v1/auth/login",
                      "/api/v1/auth/wechat",
                      "/api/v1/public/config",
                      "/api/v1/public/health")
                  .contains(path)
              && !"OPTIONS".equals(req.getMethod())) {
            String header = req.getHeader("Authorization");
            if (header == null || !header.startsWith("Bearer "))
              throw new ApiException(401, "UNAUTHORIZED", "请先登录");
            req.setAttribute("actor", auth.authenticate(header.substring(7)));
            req.setAttribute("token", header.substring(7));
          }
          chain.doFilter(req, res);
        } catch (ApiException e) {
          res.setStatus(e.status);
          res.setContentType("application/json;charset=UTF-8");
          res.getWriter().write(json.write(map("code", e.code, "message", e.getMessage())));
        }
      }
    };
  }
}

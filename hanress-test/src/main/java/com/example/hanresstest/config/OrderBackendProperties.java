package com.example.hanresstest.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "order.backend")
public record OrderBackendProperties(
        String baseUrl,
        String bearerToken
) {

    public OrderBackendProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            throw new IllegalArgumentException("必须配置 order.backend.base-url");
        }
        if (bearerToken == null || bearerToken.isBlank()) {
            throw new IllegalArgumentException("必须配置 order.backend.bearer-token");
        }
    }
}

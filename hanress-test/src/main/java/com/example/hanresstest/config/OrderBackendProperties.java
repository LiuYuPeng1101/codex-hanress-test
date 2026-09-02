package com.example.hanresstest.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "order.backend")
public record OrderBackendProperties(String baseUrl) {

    public OrderBackendProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            throw new IllegalArgumentException("必须配置 order.backend.base-url");
        }
    }
}

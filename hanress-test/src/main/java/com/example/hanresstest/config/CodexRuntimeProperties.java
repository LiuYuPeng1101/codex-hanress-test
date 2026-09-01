package com.example.hanresstest.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@ConfigurationProperties(prefix = "codex.runtime")
public record CodexRuntimeProperties(
        String executable,
        Duration startupTimeout
) {
    public CodexRuntimeProperties {
        if (executable == null || executable.isBlank()) {
            executable = "codex";
        }
        if (startupTimeout == null) {
            startupTimeout = Duration.ofSeconds(30);
        }
    }
}

package com.example.hanresstest.config;

import com.example.hanresstest.mcp.OrderMcpTools;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class McpToolConfig {

    @Bean
    public ToolCallbackProvider orderTools(OrderMcpTools orderMcpTools) {
        return MethodToolCallbackProvider
                .builder()
                .toolObjects(orderMcpTools)
                .build();
    }
}

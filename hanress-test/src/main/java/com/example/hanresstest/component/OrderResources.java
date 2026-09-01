package com.example.hanresstest.component;

import org.springframework.ai.mcp.annotation.McpResource;
import org.springframework.stereotype.Component;

@Component
public class OrderResources {

    @McpResource(
            uri = "order://status/guide",
            name = "订单状态说明",
            description = "解释订单系统中的各种状态"
    )
    public String orderStatusGuide() {

        return """
                CREATED    = 已创建
                PAID       = 已付款
                PROCESSING = 处理中
                SHIPPED    = 已发货
                COMPLETED  = 已完成
                CANCELLED  = 已取消
                """;
    }
}

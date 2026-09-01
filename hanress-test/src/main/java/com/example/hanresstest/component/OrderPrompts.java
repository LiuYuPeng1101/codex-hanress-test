package com.example.hanresstest.component;

import org.springframework.ai.mcp.annotation.McpPrompt;
import org.springframework.stereotype.Component;

@Component
public class OrderPrompts {

    @McpPrompt(
            name = "order_analysis",
            description = "生成订单状态与配送异常分析提示"
    )
    public String orderAnalysis(String orderId) {
        return """
                请分析订单 %s 的当前状态和配送情况。

                分析时：
                1. 使用订单工具获取真实数据；
                2. 不要猜测订单状态；
                3. 说明当前状态、预计送达日期和可能的异常；
                4. 清楚区分工具返回的事实与分析结论。
                """.formatted(orderId);
    }
}

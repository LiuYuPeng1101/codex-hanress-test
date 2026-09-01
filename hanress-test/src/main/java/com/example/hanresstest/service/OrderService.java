package com.example.hanresstest.service;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

@Service
public class OrderService {


    @Tool(name = "get_order_status",description = "根据订单ID查询订单当前状态和预计送达日期")
    public String getOrderStatus(@ToolParam(description = "订单ID，例如1001") String orderId) {

        if ("1001".equals(orderId)) {
            return """
                    {
                      "orderId": "1001",
                      "status": "SHIPPED",
                      "deliveryDate": "2026-08-29",
                      "message": "订单已发货"
                    }
                    """;
        }

        return """
                {
                  "orderId": "%s",
                  "status": "NOT_FOUND"
                }
                """.formatted(orderId);
    }
}

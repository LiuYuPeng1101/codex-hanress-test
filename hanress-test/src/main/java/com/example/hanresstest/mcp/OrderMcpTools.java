package com.example.hanresstest.mcp;

import com.example.hanresstest.integration.OrderBackendClient.CancelOrderResponse;
import com.example.hanresstest.integration.OrderBackendClient.OrderStatusResponse;
import com.example.hanresstest.service.OrderApplicationService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class OrderMcpTools {

    private final OrderApplicationService orderApplicationService;

    public OrderMcpTools(OrderApplicationService orderApplicationService) {
        this.orderApplicationService = orderApplicationService;
    }

    @Tool(
            name = "get_order_status",
            description = "根据订单ID查询订单当前状态和预计送达日期"
    )
    public OrderStatusResponse getOrderStatus(
            @ToolParam(description = "订单ID") String orderId
    ) {
        return orderApplicationService.getOrderStatus(orderId);
    }

    @Tool(
            name = "cancel_order",
            description = "取消指定订单。该操作会修改真实业务状态，调用前必须经过 Agent Approval，业务系统仍需执行最终权限校验。"
    )
    public CancelOrderResponse cancelOrder(
            @ToolParam(description = "要取消的订单ID") String orderId
    ) {
        return orderApplicationService.cancelOrder(orderId);
    }
}

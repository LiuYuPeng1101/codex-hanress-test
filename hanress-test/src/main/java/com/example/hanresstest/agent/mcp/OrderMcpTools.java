package com.example.hanresstest.agent.mcp;

import com.example.hanresstest.service.OrderService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * 订单领域的 MCP Tool 适配器。
 *
 * <p>这里只定义 Agent 可见的语义能力与参数，不实现业务规则，也不直接访问数据库。
 * 用户身份、租户和授权信息属于可信控制上下文，不能由模型通过 Tool 参数自行声明。</p>
 */
@Component
public class OrderMcpTools {

    private final OrderService orderService;

    public OrderMcpTools(OrderService orderService) {
        this.orderService = orderService;
    }

    @Tool(
            name = "get_order_status",
            description = "根据订单ID查询真实订单系统中的当前状态、履约信息和预计送达信息"
    )
    public JsonNode getOrderStatus(
            @ToolParam(description = "业务订单ID") String orderId
    ) {
        return orderService.getOrderStatus(orderId);
    }

    @Tool(
            name = "cancel_order",
            description = "向真实订单系统发起取消订单操作。该写操作必须经过 Agent Approval 和业务系统授权。"
    )
    public JsonNode cancelOrder(
            @ToolParam(description = "业务订单ID") String orderId
    ) {
        return orderService.cancelOrder(orderId);
    }
}

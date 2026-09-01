package com.example.hanresstest.service;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 订单领域业务服务，同时通过 Spring AI @Tool 暴露 MCP Tool。
 *
 * <p>这里用内存数据模拟真实订单系统，目的是学习 Agent -> MCP -> 业务服务的完整调用链。
 * 正式项目中应替换为数据库、远程订单服务等真实业务实现。</p>
 */
@Service
public class OrderService {

    /** 用于 Demo：记录已取消订单。生产环境应由订单系统自身维护状态。 */
    private final Set<String> cancelledOrders = ConcurrentHashMap.newKeySet();

    /**
     * 查询类 Tool：只读操作，适合配置为自动批准。
     */
    @Tool(
            name = "get_order_status",
            description = "根据订单ID查询订单当前状态和预计送达日期"
    )
    public String getOrderStatus(
            @ToolParam(description = "订单ID，例如1001") String orderId
    ) {
        if (cancelledOrders.contains(orderId)) {
            return """
                    {
                      "orderId": "%s",
                      "status": "CANCELLED",
                      "message": "订单已取消"
                    }
                    """.formatted(orderId);
        }

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

    /**
     * 写操作 Tool：会改变订单状态，因此用于演示 MCP Tool Approval。
     *
     * <p>Codex 端应把该 Tool 的 approval_mode 配置为 prompt。
     * 只有 Java 宿主对审批请求返回 accept 后，Codex 才会真正调用此方法。</p>
     */
    @Tool(
            name = "cancel_order",
            description = "取消指定订单。这是会修改业务状态的写操作，执行前必须获得审批。"
    )
    public String cancelOrder(
            @ToolParam(description = "要取消的订单ID，例如1001") String orderId
    ) {
        if (!"1001".equals(orderId)) {
            return """
                    {
                      "orderId": "%s",
                      "success": false,
                      "message": "订单不存在"
                    }
                    """.formatted(orderId);
        }

        cancelledOrders.add(orderId);
        return """
                {
                  "orderId": "%s",
                  "success": true,
                  "status": "CANCELLED",
                  "message": "订单已取消"
                }
                """.formatted(orderId);
    }
}

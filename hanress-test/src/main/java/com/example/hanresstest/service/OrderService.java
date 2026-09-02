package com.example.hanresstest.service;

import com.example.hanresstest.gateway.OrderGateway;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

/**
 * 订单应用服务。
 *
 * <p>该类不感知 MCP、LLM 或 Codex，只组织真实订单业务用例。Agent 适配层通过本类调用业务能力。</p>
 */
@Service
public class OrderService {

    private final OrderGateway orderGateway;

    public OrderService(OrderGateway orderGateway) {
        this.orderGateway = orderGateway;
    }

    public JsonNode getOrderStatus(String orderId) {
        return orderGateway.getOrderStatus(orderId);
    }

    public JsonNode cancelOrder(String orderId) {
        return orderGateway.cancelOrder(orderId);
    }
}

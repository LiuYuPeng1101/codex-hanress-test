package com.example.hanresstest.service;

import com.example.hanresstest.gateway.OrderGateway;
import com.example.hanresstest.security.BusinessIdentity;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

/**
 * 订单应用服务。
 *
 * <p>该类不感知 MCP、LLM 或 Codex，只组织真实订单业务用例，并把可信身份继续传给订单系统。</p>
 */
@Service
public class OrderService {

    private final OrderGateway orderGateway;

    public OrderService(OrderGateway orderGateway) {
        this.orderGateway = orderGateway;
    }

    public JsonNode getOrderStatus(String orderId, BusinessIdentity identity) {
        return orderGateway.getOrderStatus(orderId, identity);
    }

    public JsonNode cancelOrder(String orderId, BusinessIdentity identity) {
        return orderGateway.cancelOrder(orderId, identity);
    }
}

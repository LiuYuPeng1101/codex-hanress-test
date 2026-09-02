package com.example.hanresstest.gateway;

import tools.jackson.databind.JsonNode;

/**
 * 订单系统访问端口。
 *
 * <p>MCP Adapter 只依赖这个接口，不绑定具体 HTTP、RPC、数据库或第三方 OMS 实现。</p>
 */
public interface OrderGateway {

    JsonNode getOrderStatus(String orderId);

    JsonNode cancelOrder(String orderId);
}

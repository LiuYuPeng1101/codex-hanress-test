package com.example.hanresstest.service;

import com.example.hanresstest.integration.OrderBackendClient;
import com.example.hanresstest.integration.OrderBackendClient.CancelOrderResponse;
import com.example.hanresstest.integration.OrderBackendClient.OrderStatusResponse;
import org.springframework.stereotype.Service;

@Service
public class OrderApplicationService {

    private final OrderBackendClient orderBackendClient;

    public OrderApplicationService(OrderBackendClient orderBackendClient) {
        this.orderBackendClient = orderBackendClient;
    }

    public OrderStatusResponse getOrderStatus(String orderId) {
        return orderBackendClient.getOrderStatus(orderId);
    }

    public CancelOrderResponse cancelOrder(String orderId) {
        return orderBackendClient.cancelOrder(orderId);
    }
}

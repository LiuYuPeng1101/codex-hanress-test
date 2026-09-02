package com.example.hanresstest.integration;

import com.example.hanresstest.config.OrderBackendProperties;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class OrderBackendClient {

    private final RestClient restClient;

    public OrderBackendClient(
            RestClient.Builder builder,
            OrderBackendProperties properties
    ) {
        this.restClient = builder
                .baseUrl(properties.baseUrl())
                .build();
    }

    public OrderStatusResponse getOrderStatus(String orderId) {
        return restClient.get()
                .uri("/api/orders/{orderId}", orderId)
                .retrieve()
                .body(OrderStatusResponse.class);
    }

    public CancelOrderResponse cancelOrder(String orderId) {
        return restClient.post()
                .uri("/api/orders/{orderId}/cancel", orderId)
                .retrieve()
                .body(CancelOrderResponse.class);
    }

    public record OrderStatusResponse(
            String orderId,
            String status,
            String deliveryDate,
            String message
    ) {
    }

    public record CancelOrderResponse(
            String orderId,
            boolean success,
            String status,
            String message
    ) {
    }
}

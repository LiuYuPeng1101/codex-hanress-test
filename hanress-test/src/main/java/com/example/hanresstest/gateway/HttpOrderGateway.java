package com.example.hanresstest.gateway;

import com.example.hanresstest.config.OrderServiceProperties;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;

/**
 * 通过企业内部 HTTP API 访问真实订单系统。
 *
 * <p>这里不包含任何测试订单或内存状态。上游 API 不可用时直接抛出异常，由调用链和观测系统处理。</p>
 */
@Component
public class HttpOrderGateway implements OrderGateway {

    private final RestClient restClient;
    private final OrderServiceProperties properties;

    public HttpOrderGateway(RestClient.Builder builder, OrderServiceProperties properties) {
        this.properties = properties;
        this.restClient = builder
                .baseUrl(properties.baseUrl())
                .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + properties.serviceToken())
                .build();
    }

    @Override
    public JsonNode getOrderStatus(String orderId) {
        return restClient.get()
                .uri(properties.statusPath(), orderId)
                .retrieve()
                .body(JsonNode.class);
    }

    @Override
    public JsonNode cancelOrder(String orderId) {
        return restClient.post()
                .uri(properties.cancelPath(), orderId)
                .retrieve()
                .body(JsonNode.class);
    }
}

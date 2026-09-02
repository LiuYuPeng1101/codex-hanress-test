package com.example.hanresstest.gateway;

import com.example.hanresstest.config.OrderServiceProperties;
import com.example.hanresstest.security.BusinessIdentity;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;

/**
 * 通过企业内部 HTTP API 访问真实订单系统。
 *
 * <p>服务凭据用于系统间认证；X-User-Id / X-Tenant-Id / X-Roles 表达当前业务主体。
 * 最终订单系统必须基于这些可信身份独立执行 RBAC / ABAC / Tenant / 资源归属和状态校验。</p>
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
    public JsonNode getOrderStatus(String orderId, BusinessIdentity identity) {
        return restClient.get()
                .uri(properties.statusPath(), orderId)
                .headers(headers -> applyIdentity(headers, identity))
                .retrieve()
                .body(JsonNode.class);
    }

    @Override
    public JsonNode cancelOrder(String orderId, BusinessIdentity identity) {
        return restClient.post()
                .uri(properties.cancelPath(), orderId)
                .headers(headers -> applyIdentity(headers, identity))
                .retrieve()
                .body(JsonNode.class);
    }

    private static void applyIdentity(HttpHeaders headers, BusinessIdentity identity) {
        headers.set("X-User-Id", identity.userId());
        headers.set("X-Tenant-Id", identity.tenantId());
        headers.set("X-Roles", String.join(",", identity.roles()));
    }
}

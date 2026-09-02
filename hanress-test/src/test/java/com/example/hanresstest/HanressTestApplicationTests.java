package com.example.hanresstest;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = {
        "order-service.base-url=http://127.0.0.1:65535",
        "order-service.service-token=test-service-token",
        "order-service.status-path=/api/orders/{orderId}/status",
        "order-service.cancel-path=/api/orders/{orderId}/cancel"
})
class HanressTestApplicationTests {

    @Test
    void contextLoads() {
    }
}

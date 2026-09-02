package com.example.hanresstest;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "order.backend.base-url=http://localhost")
class OrderMcpAdapterApplicationTests {

    @Test
    void contextLoads() {
    }
}

package com.example.hanresstest;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class HanressTestApplication {

    public static void main(String[] args) {
        SpringApplication.run(HanressTestApplication.class, args);
    }
}

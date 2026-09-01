package com.example.hanresstest.component;

import com.example.hanresstest.service.OrderService;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

@Component
public class CodexAppServerClient {

    @Value("${agent.order.workspace}")
    private String orderAgentWorkspace;

    private final ObjectMapper mapper = new ObjectMapper();

    private final OrderService orderService;

    private final AtomicLong requestId = new AtomicLong(1);

    private final Map<Long, CompletableFuture<JsonNode>> pendingRequests = new ConcurrentHashMap<>();

    private Process process;

    private BufferedWriter writer;

    private volatile boolean running;

    public CodexAppServerClient(OrderService orderService) {
        this.orderService = orderService;
    }

    public void start() throws Exception {

        ProcessBuilder builder = new ProcessBuilder(
                "cmd.exe",
                "/c",
                "codex",
                "app-server"
        );

        process = builder.start();

        writer = new BufferedWriter(
                new OutputStreamWriter(
                        process.getOutputStream(),
                        StandardCharsets.UTF_8
                )
        );

        running = true;

        startStdoutReader();
        startStderrReader();

        initialize();
    }

    private void initialize() throws Exception {

        ObjectNode clientInfo = mapper.createObjectNode();

        clientInfo.put("name", "spring-boot-harness-test");
        clientInfo.put("title", "Spring Boot Harness Test");
        clientInfo.put("version", "0.1.0");

        ObjectNode capabilities =
                mapper.createObjectNode();

        capabilities.put(
                "experimentalApi",
                true
        );

        ObjectNode params =
                mapper.createObjectNode();

        params.set(
                "clientInfo",
                clientInfo
        );

        params.set(
                "capabilities",
                capabilities
        );

        JsonNode result =
                request(
                        "initialize",
                        params
                ).get(30, TimeUnit.SECONDS);

        System.out.println(
                "✅ App Server initialize 成功"
        );

        notify(
                "initialized",
                mapper.createObjectNode()
        );
    }

    public CompletableFuture<String> startThread() {

        ObjectNode params = mapper.createObjectNode();

        params.put(
                "cwd",
                orderAgentWorkspace
        );

        return request(
                "thread/start",
                params
        ).thenApply(result ->
                result
                        .path("thread")
                        .path("id")
                        .asText()
        );
    }

    public CompletableFuture<String> startTurn(
            String threadId,
            String message
    ) {

        ObjectNode params =
                mapper.createObjectNode();

        params.put(
                "threadId",
                threadId
        );

        ObjectNode input =
                params
                        .putArray("input")
                        .addObject();

        input.put(
                "type",
                "text"
        );

        input.put(
                "text",
                message
        );

        return request(
                "turn/start",
                params
        ).thenApply(result ->
                result
                        .path("turn")
                        .path("id")
                        .asText()
        );
    }

    private CompletableFuture<JsonNode> request(
            String method,
            JsonNode params
    ) {

        long id =
                requestId.getAndIncrement();

        ObjectNode message =
                mapper.createObjectNode();

        message.put("id", id);
        message.put("method", method);
        message.set("params", params);

        CompletableFuture<JsonNode> future =
                new CompletableFuture<>();

        pendingRequests.put(
                id,
                future
        );

        try {

            write(message);

        } catch (Exception e) {

            pendingRequests.remove(id);

            future.completeExceptionally(e);
        }

        return future;
    }

    private void notify(
            String method,
            JsonNode params
    ) throws Exception {

        ObjectNode message =
                mapper.createObjectNode();

        message.put(
                "method",
                method
        );

        message.set(
                "params",
                params
        );

        write(message);
    }

    private void write(
            JsonNode message
    ) throws Exception {

        synchronized (this) {

            writer.write(
                    mapper.writeValueAsString(message)
            );

            writer.newLine();

            writer.flush();
        }
    }

    private void startStdoutReader() {

        Thread readerThread =
                new Thread(() -> {

                    try (
                            BufferedReader reader =
                                    new BufferedReader(
                                            new InputStreamReader(
                                                    process.getInputStream(),
                                                    StandardCharsets.UTF_8
                                            )
                                    )
                    ) {

                        String line;

                        while (
                                running
                                        && (line = reader.readLine()) != null
                        ) {

                            JsonNode json =
                                    mapper.readTree(line);

                            dispatch(json);
                        }

                    } catch (Exception e) {

                        if (running) {
                            e.printStackTrace();
                        }
                    }
                });

        readerThread.setDaemon(true);

        readerThread.setName(
                "codex-app-server-reader"
        );

        readerThread.start();
    }

    private void dispatch(
            JsonNode message
    ) throws Exception {

        // Java -> App Server 请求的响应
        if (
                message.has("id")
                        && !message.has("method")
        ) {

            long id =
                    message.path("id").asLong();

            CompletableFuture<JsonNode> future =
                    pendingRequests.remove(id);

            if (future == null) {
                return;
            }

            if (message.has("error")) {

                future.completeExceptionally(
                        new RuntimeException(
                                message.get("error").toString()
                        )
                );

            } else {

                future.complete(
                        message.get("result")
                );
            }

            return;
        }

        // App Server -> Java 的反向请求
        if (
                message.has("id")
                        && message.has("method")
        ) {



            return;
        }

        // 普通事件
        if (message.has("method")) {

            handleNotification(message);
        }
    }



    private void sendToolResult(
            JsonNode requestId,
            String text,
            boolean success
    ) throws Exception {

        ObjectNode response =
                mapper.createObjectNode();

        response.set(
                "id",
                requestId
        );

        ObjectNode result =
                response.putObject("result");

        ObjectNode content =
                result
                        .putArray("contentItems")
                        .addObject();

        content.put(
                "type",
                "inputText"
        );

        content.put(
                "text",
                text
        );

        result.put(
                "success",
                success
        );

        write(response);
    }

    private void handleNotification(
            JsonNode event
    ) {

        String method =
                event
                        .path("method")
                        .asText();

        if (
                "item/agentMessage/delta"
                        .equals(method)
        ) {

            String delta =
                    event
                            .path("params")
                            .path("delta")
                            .asText();

            System.out.print(delta);

            return;
        }

        if (
                "turn/completed"
                        .equals(method)
        ) {

            System.out.println();
            System.out.println();
            System.out.println(
                    "✅ Turn Completed"
            );
        }
    }

    private void startStderrReader() {

        Thread thread =
                new Thread(() -> {

                    try (
                            BufferedReader reader =
                                    new BufferedReader(
                                            new InputStreamReader(
                                                    process.getErrorStream(),
                                                    StandardCharsets.UTF_8
                                            )
                                    )
                    ) {

                        String line;

                        while (
                                running
                                        && (line = reader.readLine()) != null
                        ) {

                            System.err.println(
                                    "[codex] " + line
                            );
                        }

                    } catch (Exception ignored) {
                    }
                });

        thread.setDaemon(true);

        thread.start();
    }

    @PreDestroy
    public void close() {

        running = false;

        if (process != null) {
            process.destroy();
        }
    }
}

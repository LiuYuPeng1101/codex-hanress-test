package com.example.hanresstest.component;

import com.example.hanresstest.config.CodexRuntimeProperties;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Low-level Codex App Server transport client.
 *
 * <p>This class deliberately knows nothing about order/finance/contract agents.
 * Agent-specific workspace, skills and policies belong to the runtime/service layer.</p>
 */
@Component
public class CodexAppServerClient {

    private static final Logger log = LoggerFactory.getLogger(CodexAppServerClient.class);

    private final ObjectMapper mapper = new ObjectMapper();
    private final CodexRuntimeProperties properties;
    private final AtomicLong requestId = new AtomicLong(1);
    private final Map<Long, CompletableFuture<JsonNode>> pendingRequests = new ConcurrentHashMap<>();
    private final Object writeLock = new Object();

    private Process process;
    private BufferedWriter writer;
    private volatile boolean running;

    public CodexAppServerClient(CodexRuntimeProperties properties) {
        this.properties = properties;
    }

    public synchronized void start() throws Exception {
        if (running) {
            return;
        }

        process = createProcessBuilder().start();
        writer = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
        running = true;

        startStdoutReader();
        startStderrReader();
        initialize(properties.startupTimeout());
    }

    private ProcessBuilder createProcessBuilder() {
        String executable = properties.executable();
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");

        if (windows) {
            return new ProcessBuilder("cmd.exe", "/c", executable, "app-server");
        }
        return new ProcessBuilder(executable, "app-server");
    }

    private void initialize(Duration timeout) throws Exception {
        ObjectNode clientInfo = mapper.createObjectNode();
        clientInfo.put("name", "spring-boot-agent-runtime");
        clientInfo.put("title", "Spring Boot Agent Runtime");
        clientInfo.put("version", "0.1.0");

        ObjectNode params = mapper.createObjectNode();
        params.set("clientInfo", clientInfo);

        request("initialize", params).get(timeout.toMillis(), TimeUnit.MILLISECONDS);
        notify("initialized", mapper.createObjectNode());
        log.info("Codex App Server initialized");
    }

    /** Creates a Codex conversation scoped to an agent workspace. */
    public CompletableFuture<String> startThread(String workspace) {
        ObjectNode params = mapper.createObjectNode();
        params.put("cwd", workspace);

        return request("thread/start", params)
                .thenApply(result -> result.path("thread").path("id").asText());
    }

    /**
     * Lists skills visible from the supplied workspace.
     * This is used for readiness/health validation, not as a registration step per turn.
     */
    public CompletableFuture<JsonNode> listSkills(String workspace, boolean forceReload) {
        ObjectNode params = mapper.createObjectNode();
        params.putArray("cwds").add(workspace);
        params.put("forceReload", forceReload);
        return request("skills/list", params);
    }

    /** Starts a turn and lets Codex select an appropriate discovered skill automatically. */
    public CompletableFuture<String> startTurn(String threadId, String message) {
        return startTurnInternal(threadId, message, null, null);
    }

    /**
     * Starts a turn with an explicit skill. Use this for deterministic business flows where
     * the application already knows which skill should be used.
     */
    public CompletableFuture<String> startTurnWithSkill(
            String threadId,
            String message,
            String skillName,
            String skillPath
    ) {
        return startTurnInternal(threadId, message, skillName, skillPath);
    }

    private CompletableFuture<String> startTurnInternal(
            String threadId,
            String message,
            String skillName,
            String skillPath
    ) {
        ObjectNode params = mapper.createObjectNode();
        params.put("threadId", threadId);

        ArrayNode input = params.putArray("input");
        ObjectNode text = input.addObject();
        text.put("type", "text");
        text.put("text", message);

        if (skillName != null && skillPath != null) {
            ObjectNode skill = input.addObject();
            skill.put("type", "skill");
            skill.put("name", skillName);
            skill.put("path", skillPath);
        }

        return request("turn/start", params)
                .thenApply(result -> result.path("turn").path("id").asText());
    }

    private CompletableFuture<JsonNode> request(String method, JsonNode params) {
        ensureRunning();

        long id = requestId.getAndIncrement();
        ObjectNode message = mapper.createObjectNode();
        message.put("id", id);
        message.put("method", method);
        message.set("params", params);

        CompletableFuture<JsonNode> future = new CompletableFuture<>();
        pendingRequests.put(id, future);

        try {
            write(message);
        } catch (Exception e) {
            pendingRequests.remove(id);
            future.completeExceptionally(e);
        }
        return future;
    }

    private void notify(String method, JsonNode params) throws Exception {
        ensureRunning();
        ObjectNode message = mapper.createObjectNode();
        message.put("method", method);
        message.set("params", params);
        write(message);
    }

    private void write(JsonNode message) throws Exception {
        synchronized (writeLock) {
            writer.write(mapper.writeValueAsString(message));
            writer.newLine();
            writer.flush();
        }
    }

    private void startStdoutReader() {
        Thread readerThread = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while (running && (line = reader.readLine()) != null) {
                    dispatch(mapper.readTree(line));
                }
                if (running) {
                    failAll(new IllegalStateException("Codex App Server stdout closed unexpectedly"));
                }
            } catch (Exception e) {
                if (running) {
                    failAll(e);
                    log.error("Codex App Server reader failed", e);
                }
            }
        }, "codex-app-server-reader");
        readerThread.setDaemon(true);
        readerThread.start();
    }

    private void dispatch(JsonNode message) throws Exception {
        if (message.has("id") && !message.has("method")) {
            handleResponse(message);
            return;
        }

        if (message.has("id") && message.has("method")) {
            handleServerRequest(message);
            return;
        }

        if (message.has("method")) {
            handleNotification(message);
        }
    }

    private void handleResponse(JsonNode message) {
        long id = message.path("id").asLong();
        CompletableFuture<JsonNode> future = pendingRequests.remove(id);
        if (future == null) {
            log.warn("Received response for unknown request id={}", id);
            return;
        }

        if (message.has("error")) {
            future.completeExceptionally(new IllegalStateException(message.get("error").toString()));
        } else {
            future.complete(message.get("result"));
        }
    }

    /**
     * Approval and other server->client requests should be routed here later.
     * Unknown requests are answered immediately instead of leaving a turn hanging forever.
     */
    private void handleServerRequest(JsonNode request) throws Exception {
        ObjectNode response = mapper.createObjectNode();
        response.set("id", request.get("id"));

        ObjectNode error = response.putObject("error");
        error.put("code", -32601);
        error.put("message", "Unsupported server request: " + request.path("method").asText());
        write(response);
    }

    private void handleNotification(JsonNode event) {
        String method = event.path("method").asText();

        if ("item/agentMessage/delta".equals(method)) {
            System.out.print(event.path("params").path("delta").asText());
            return;
        }

        if ("turn/completed".equals(method)) {
            System.out.println();
            log.info("Turn completed");
            return;
        }

        if ("skills/changed".equals(method)) {
            log.info("Codex reported that local skills changed; refresh skills/list before the next validation");
        }
    }

    private void startStderrReader() {
        Thread stderrThread = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getErrorStream(), StandardCharsets.UTF_8))) {
                String line;
                while (running && (line = reader.readLine()) != null) {
                    log.warn("[codex] {}", line);
                }
            } catch (Exception e) {
                if (running) {
                    log.debug("Codex stderr reader stopped", e);
                }
            }
        }, "codex-app-server-stderr");
        stderrThread.setDaemon(true);
        stderrThread.start();
    }

    private void ensureRunning() {
        if (!running) {
            throw new IllegalStateException("Codex App Server is not running");
        }
    }

    private void failAll(Throwable error) {
        pendingRequests.forEach((id, future) -> future.completeExceptionally(error));
        pendingRequests.clear();
    }

    @PreDestroy
    public synchronized void close() {
        running = false;
        failAll(new IllegalStateException("Codex App Server client closed"));

        if (process != null) {
            process.destroy();
            try {
                if (!process.waitFor(5, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                process.destroyForcibly();
            }
        }
    }
}

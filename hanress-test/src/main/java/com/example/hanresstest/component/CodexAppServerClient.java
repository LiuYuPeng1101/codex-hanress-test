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
 * Codex App Server 的底层传输客户端。
 *
 * <p>这个类只负责 App Server 进程生命周期、stdin/stdout JSON-RPC 通信、请求响应关联和事件接收。
 * 它刻意不理解订单、财务、合同等具体业务 Agent。Agent 的 workspace、skills、policy 等信息
 * 应该放在更上层的 Runtime / Service 层。</p>
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

    /** 启动 codex app-server 子进程，并完成协议初始化。 */
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

    /** 根据当前操作系统构建 codex app-server 启动命令。 */
    private ProcessBuilder createProcessBuilder() {
        String executable = properties.executable();
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");

        if (windows) {
            return new ProcessBuilder("cmd.exe", "/c", executable, "app-server");
        }
        return new ProcessBuilder(executable, "app-server");
    }

    /** 完成 App Server initialize / initialized 握手。 */
    private void initialize(Duration timeout) throws Exception {
        ObjectNode clientInfo = mapper.createObjectNode();
        clientInfo.put("name", "spring-boot-agent-runtime");
        clientInfo.put("title", "Spring Boot Agent Runtime");
        clientInfo.put("version", "0.1.0");

        ObjectNode params = mapper.createObjectNode();
        params.set("clientInfo", clientInfo);

        request("initialize", params).get(timeout.toMillis(), TimeUnit.MILLISECONDS);
        notify("initialized", mapper.createObjectNode());
        log.info("Codex App Server 初始化完成");
    }

    /**
     * 创建一个新的 Codex Thread。
     * workspace 会被写入 thread/start.cwd，Codex 会基于这个工作目录发现项目级 Skill。
     */
    public CompletableFuture<String> startThread(String workspace) {
        ObjectNode params = mapper.createObjectNode();
        params.put("cwd", workspace);

        return request("thread/start", params)
                .thenApply(result -> result.path("thread").path("id").asText());
    }

    /**
     * 查询指定 workspace 下 Codex 当前能够发现的 Skill。
     * 该接口主要用于启动健康检查、运维展示和问题排查，不是每轮 Turn 的 Skill 注册步骤。
     */
    public CompletableFuture<JsonNode> listSkills(String workspace, boolean forceReload) {
        ObjectNode params = mapper.createObjectNode();
        params.putArray("cwds").add(workspace);
        params.put("forceReload", forceReload);
        return request("skills/list", params);
    }

    /**
     * 启动一个普通 Turn，不显式指定 Skill，由 Codex 根据已发现的 Skill 和用户输入自动选择。
     */
    public CompletableFuture<String> startTurn(String threadId, String message) {
        return startTurnInternal(threadId, message, null, null);
    }

    /**
     * 启动一个显式指定 Skill 的 Turn。
     * 适合确定性业务流程，例如业务系统已经知道当前操作就是“订单异常分析”。
     */
    public CompletableFuture<String> startTurnWithSkill(
            String threadId,
            String message,
            String skillName,
            String skillPath
    ) {
        return startTurnInternal(threadId, message, skillName, skillPath);
    }

    /** 统一构造 turn/start 请求。 */
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

    /**
     * 发送带 request id 的 JSON-RPC 请求，并通过 CompletableFuture 等待对应响应。
     */
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

    /** 发送没有 request id 的 JSON-RPC Notification。 */
    private void notify(String method, JsonNode params) throws Exception {
        ensureRunning();
        ObjectNode message = mapper.createObjectNode();
        message.put("method", method);
        message.set("params", params);
        write(message);
    }

    /**
     * 向 App Server stdin 写一行 JSONL。
     * writeLock 保证多个调用线程不会把 JSON 写串。
     */
    private void write(JsonNode message) throws Exception {
        synchronized (writeLock) {
            writer.write(mapper.writeValueAsString(message));
            writer.newLine();
            writer.flush();
        }
    }

    /**
     * 启动唯一的 stdout Reader Loop。
     * 所有 response、notification、server request 都由这个线程统一读取后再分发。
     */
    private void startStdoutReader() {
        Thread readerThread = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while (running && (line = reader.readLine()) != null) {
                    dispatch(mapper.readTree(line));
                }
                if (running) {
                    failAll(new IllegalStateException("Codex App Server stdout 意外关闭"));
                }
            } catch (Exception e) {
                if (running) {
                    failAll(e);
                    log.error("Codex App Server 读取线程异常", e);
                }
            }
        }, "codex-app-server-reader");
        readerThread.setDaemon(true);
        readerThread.start();
    }

    /**
     * 根据 JSON-RPC 消息形态做统一分发：
     * 1. 有 id、无 method：客户端请求的响应；
     * 2. 有 id、有 method：App Server 主动发给客户端的 Server Request；
     * 3. 有 method、无 id：普通 Notification/Event。
     */
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

    /** 根据 request id 找到等待中的 CompletableFuture 并完成它。 */
    private void handleResponse(JsonNode message) {
        long id = message.path("id").asLong();
        CompletableFuture<JsonNode> future = pendingRequests.remove(id);
        if (future == null) {
            log.warn("收到未知 request id={} 的响应", id);
            return;
        }

        if (message.has("error")) {
            future.completeExceptionally(new IllegalStateException(message.get("error").toString()));
        } else {
            future.complete(message.get("result"));
        }
    }

    /**
     * 处理 App Server -> Java 的反向请求。
     * 后续学习 Approval 时会在这里接入真正的审批路由。
     * 当前对未知 Server Request 立即返回错误，避免 Turn 因一直等不到响应而永久挂起。
     */
    private void handleServerRequest(JsonNode request) throws Exception {
        ObjectNode response = mapper.createObjectNode();
        response.set("id", request.get("id"));

        ObjectNode error = response.putObject("error");
        error.put("code", -32601);
        error.put("message", "暂不支持的 Server Request: " + request.path("method").asText());
        write(response);
    }

    /**
     * 处理 App Server 推送的事件。
     * 当前示例只展示 Agent 文本增量、Turn 完成和 Skill 变化事件；后续会扩展为统一 AgentEvent。
     */
    private void handleNotification(JsonNode event) {
        String method = event.path("method").asText();

        if ("item/agentMessage/delta".equals(method)) {
            System.out.print(event.path("params").path("delta").asText());
            return;
        }

        if ("turn/completed".equals(method)) {
            System.out.println();
            log.info("Turn 执行完成");
            return;
        }

        if ("skills/changed".equals(method)) {
            log.info("Codex 检测到本地 Skill 发生变化；下一次健康校验前应重新执行 skills/list");
        }
    }

    /**
     * 单独消费 stderr，避免日志污染 stdout 的 JSON-RPC 数据，也防止 stderr 缓冲区写满导致子进程阻塞。
     */
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
                    log.debug("Codex stderr 读取线程已停止", e);
                }
            }
        }, "codex-app-server-stderr");
        stderrThread.setDaemon(true);
        stderrThread.start();
    }

    /** 确保请求只在 App Server 已启动后发送。 */
    private void ensureRunning() {
        if (!running) {
            throw new IllegalStateException("Codex App Server 尚未启动");
        }
    }

    /** 当 App Server 异常退出时，让所有等待中的请求立即失败。 */
    private void failAll(Throwable error) {
        pendingRequests.forEach((id, future) -> future.completeExceptionally(error));
        pendingRequests.clear();
    }

    /** Spring 容器关闭时同步结束 App Server 子进程并释放等待中的请求。 */
    @PreDestroy
    public synchronized void close() {
        running = false;
        failAll(new IllegalStateException("Codex App Server Client 已关闭"));

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

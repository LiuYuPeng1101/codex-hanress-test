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
 * Codex App Server 的底层客户端。
 *
 * <p>这个类只负责“如何和 codex app-server 通信”，不负责具体业务 Agent 的定义。</p>
 *
 * <p>它主要承担以下职责：</p>
 * <ul>
 *     <li>启动和关闭 {@code codex app-server} 子进程</li>
 *     <li>通过 stdin/stdout 与 App Server 进行 JSON-RPC 通信</li>
 *     <li>维护请求 ID 与异步响应之间的对应关系</li>
 *     <li>创建 Thread（Agent 会话）</li>
 *     <li>启动 Turn（一次完整的 Agent 执行）</li>
 *     <li>查询 Codex 当前能发现的 Skills</li>
 *     <li>接收 App Server 推送的事件</li>
 *     <li>接收 App Server 主动发给宿主应用的 Server Request，例如未来的 Approval</li>
 * </ul>
 *
 * <p>注意：这个类不应该知道 order-agent、finance-agent、contract-agent 等业务概念。
 * Agent 的 workspace、skills、模型、策略等信息应该由更上层的 Runtime/Agent Definition 管理。</p>
 */
@Component
public class CodexAppServerClient {

    private static final Logger log = LoggerFactory.getLogger(CodexAppServerClient.class);

    /** JSON 序列化/反序列化工具，用于构造和解析 App Server 的 JSON-RPC 消息。 */
    private final ObjectMapper mapper = new ObjectMapper();

    /** Codex Runtime 配置，例如 codex 可执行文件路径、启动超时时间。 */
    private final CodexRuntimeProperties properties;

    /**
     * JSON-RPC 请求 ID 生成器。
     * 每个 request 都必须有唯一 ID，App Server 返回 response 时会携带同一个 ID。
     */
    private final AtomicLong requestId = new AtomicLong(1);

    /**
     * 保存“requestId -> 等待该响应的 CompletableFuture”。
     * App Server 的响应顺序不一定和请求发送顺序一致，所以通过 requestId 做请求/响应关联。
     */
    private final Map<Long, CompletableFuture<JsonNode>> pendingRequests = new ConcurrentHashMap<>();

    /** stdin 写锁，避免多个线程同时发送 JSON 时把消息写串。 */
    private final Object writeLock = new Object();

    /** App Server 子进程。 */
    private Process process;

    /** 向 App Server stdin 写入 JSON-RPC 消息。 */
    private BufferedWriter writer;

    /** 标记当前 Client 是否正在运行。 */
    private volatile boolean running;

    public CodexAppServerClient(CodexRuntimeProperties properties) {
        this.properties = properties;
    }

    /**
     * 启动 Codex App Server，并完成协议初始化。
     *
     * <p>执行顺序：</p>
     * <ol>
     *     <li>启动 {@code codex app-server} 子进程</li>
     *     <li>创建 stdin writer</li>
     *     <li>启动 stdout Reader Loop</li>
     *     <li>启动 stderr 日志读取线程</li>
     *     <li>发送 initialize / initialized 完成握手</li>
     * </ol>
     */
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

    /**
     * 根据当前操作系统构建 App Server 启动命令。
     * Windows 使用 cmd.exe；Linux / Docker 直接执行 codex 二进制。
     */
    private ProcessBuilder createProcessBuilder() {
        String executable = properties.executable();
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");

        if (windows) {
            return new ProcessBuilder("cmd.exe", "/c", executable, "app-server");
        }
        return new ProcessBuilder(executable, "app-server");
    }

    /**
     * 完成 App Server 的 initialize / initialized 握手。
     * 一条连接只有初始化成功后，后续才能调用 thread/start、turn/start、skills/list 等方法。
     */
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
     *
     * <p>Thread 可以理解成“一个持续存在的 Agent 聊天窗口 / Agent 会话”。
     * 同一个 Thread 中可以连续运行多个 Turn，并共享这个 Thread 的上下文。</p>
     *
     * @param workspace Agent 的工作目录，同时作为 thread/start 的 cwd。
     *                  Codex 会基于这个目录发现项目级 Skill，例如：
     *                  {@code <workspace>/.agents/skills}
     * @return 新创建的 threadId
     */
    public CompletableFuture<String> startThread(String workspace) {
        ObjectNode params = mapper.createObjectNode();
        params.put("cwd", workspace);

        return request("thread/start", params)
                .thenApply(result -> result.path("thread").path("id").asText());
    }

    /**
     * 查询指定 workspace 下 Codex 当前能够发现的 Skills。
     *
     * <p>这个方法主要用于启动健康检查、Agent Console 展示和问题排查。
     * 它不是 Skill 注册接口，也不需要每个 Turn 都调用。</p>
     */
    public CompletableFuture<JsonNode> listSkills(String workspace, boolean forceReload) {
        ObjectNode params = mapper.createObjectNode();
        params.putArray("cwds").add(workspace);
        params.put("forceReload", forceReload);
        return request("skills/list", params);
    }

    /**
     * 启动一次普通 Turn。
     *
     * <p>Turn 可以理解成“聊天窗口中的一轮完整执行”：用户输入一次消息，
     * Codex Harness 可能经历模型推理、Skill 选择、MCP / Tool 调用等步骤，直到本轮完成。</p>
     *
     * <p>这里不显式指定 Skill，因此 Codex 可以根据当前 Thread 已发现的 Skill metadata
     * 和用户请求自动决定是否使用某个 Skill。</p>
     */
    public CompletableFuture<String> startTurn(String threadId, String message) {
        return startTurnInternal(threadId, message, null, null);
    }

    /**
     * 启动一次显式指定 Skill 的 Turn。
     * 适合业务系统已经明确知道应该使用哪个 Skill 的场景。
     */
    public CompletableFuture<String> startTurnWithSkill(
            String threadId,
            String message,
            String skillName,
            String skillPath
    ) {
        return startTurnInternal(threadId, message, skillName, skillPath);
    }

    /**
     * 统一构造 turn/start 请求。
     * 普通模式只加入 text input；显式 Skill 模式会额外加入 skill input item。
     */
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
     * 发送一条需要响应的 JSON-RPC Request。
     *
     * <p>方法会生成唯一 requestId，并创建 CompletableFuture 放入 pendingRequests。
     * 真正响应由 stdout Reader Loop 异步读取，再通过相同 ID 完成对应 Future。</p>
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

    /**
     * 发送 JSON-RPC Notification。
     * Notification 没有 requestId，因此不会等待 Response。
     */
    private void notify(String method, JsonNode params) throws Exception {
        ensureRunning();
        ObjectNode message = mapper.createObjectNode();
        message.put("method", method);
        message.set("params", params);
        write(message);
    }

    /**
     * 将一条 JSON 消息写入 App Server stdin。
     * stdio transport 使用一行一条 JSON 消息，所以每次写完都需要换行并 flush。
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
     *
     * <p>不能让多个业务线程分别 readLine()，否则 Response、Notification、Server Request 会互相抢消息。
     * 所有 stdout 消息统一由这个线程读取，再交给 dispatch() 分类处理。</p>
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
                    log.error("Codex App Server Reader Loop 异常", e);
                }
            }
        }, "codex-app-server-reader");
        readerThread.setDaemon(true);
        readerThread.start();
    }

    /**
     * 对 App Server stdout 中的消息进行分类路由。
     *
     * <ul>
     *     <li>有 id、无 method：我们之前发送的 Request 对应的 Response</li>
     *     <li>有 id、有 method：App Server 主动发给 Java 的 Server Request，例如 Approval</li>
     *     <li>有 method、无 id：Notification / Event，例如 turn/completed、item/agentMessage/delta</li>
     * </ul>
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

    /**
     * 处理普通 JSON-RPC Response，并通过 requestId 找到对应的 CompletableFuture。
     */
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
     * 处理 App Server 主动发给 Java 宿主应用的 Server Request。
     *
     * <p>未来学习 Approval / Human-in-the-loop 时，这里会成为关键入口。</p>
     *
     * <p>当前 Demo 还没有实现 Approval，因此对未知 Server Request 立即返回 Method Not Found，
     * 避免 App Server 一直等待响应导致当前 Turn 永久挂起。</p>
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
     * 处理 App Server 推送的 Notification / Event。
     *
     * <p>当前 Demo 只处理少量事件：</p>
     * <ul>
     *     <li>item/agentMessage/delta：Agent 最终回答的流式文本</li>
     *     <li>turn/completed：当前 Turn 已完成</li>
     *     <li>skills/changed：本地 Skill 发生变化</li>
     * </ul>
     *
     * <p>以后做 Agent Gateway 时，这里应该进一步抽象成统一 AgentEvent，并通过 SSE / WebSocket 推给前端。</p>
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
     * 单独消费 App Server stderr。
     * stdout 是 JSON-RPC 协议流，stderr 是日志流，二者不能合并。
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

    /** App Server 异常退出或 Client 关闭时，让所有等待中的请求立即失败。 */
    private void failAll(Throwable error) {
        pendingRequests.forEach((id, future) -> future.completeExceptionally(error));
        pendingRequests.clear();
    }

    /**
     * Spring Bean 销毁时关闭 App Server 子进程。
     * 先尝试正常结束；5 秒内未退出则强制结束。
     */
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

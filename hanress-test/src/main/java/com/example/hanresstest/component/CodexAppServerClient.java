package com.example.hanresstest.component;

import com.example.hanresstest.config.CodexRuntimeProperties;
import com.example.hanresstest.service.ApprovalDecisionService;
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
 * <p>主要职责：</p>
 * <ul>
 *     <li>启动和关闭 {@code codex app-server} 子进程</li>
 *     <li>通过 stdin/stdout 与 App Server 进行 JSON-RPC 通信</li>
 *     <li>维护请求 ID 与异步响应之间的对应关系</li>
 *     <li>创建 Thread（Agent 会话）和启动 Turn（一次完整执行）</li>
 *     <li>查询 Codex 当前能发现的 Skills</li>
 *     <li>接收 Notification / Event</li>
 *     <li>处理 App Server 主动发给 Java 的 Server Request，例如 MCP Tool Approval</li>
 * </ul>
 *
 * <p>注意：这个类不应该知道 order-agent、finance-agent、contract-agent 等业务概念。
 * Agent 的 workspace、skills、模型和业务策略应该由更上层的 Runtime / Agent Definition 管理。</p>
 */
@Component
public class CodexAppServerClient {

    private static final Logger log = LoggerFactory.getLogger(CodexAppServerClient.class);
    private static final String MCP_ELICITATION_REQUEST = "mcpServer/elicitation/request";
    private static final String MCP_TOOL_APPROVAL_KIND = "mcp_tool_call";

    /** JSON 序列化/反序列化工具。 */
    private final ObjectMapper mapper = new ObjectMapper();

    /** Codex Runtime 配置，例如 codex 可执行文件路径、启动超时时间。 */
    private final CodexRuntimeProperties properties;

    /** 审批决策独立放在 Service 中，底层 Client 只负责协议转发。 */
    private final ApprovalDecisionService approvalDecisionService;

    /** JSON-RPC requestId 生成器。 */
    private final AtomicLong requestId = new AtomicLong(1);

    /** requestId -> 等待对应 Response 的 Future。 */
    private final Map<Long, CompletableFuture<JsonNode>> pendingRequests = new ConcurrentHashMap<>();

    /** 防止多个线程同时写 stdin 导致 JSON 消息互相穿插。 */
    private final Object writeLock = new Object();

    private Process process;
    private BufferedWriter writer;
    private volatile boolean running;

    public CodexAppServerClient(
            CodexRuntimeProperties properties,
            ApprovalDecisionService approvalDecisionService
    ) {
        this.properties = properties;
        this.approvalDecisionService = approvalDecisionService;
    }

    /**
     * 启动 Codex App Server，并完成 initialize / initialized 协议握手。
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

    /** Windows 通过 cmd.exe 启动；Linux / Docker 直接执行 codex 二进制。 */
    private ProcessBuilder createProcessBuilder() {
        String executable = properties.executable();
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");
        if (windows) {
            return new ProcessBuilder("cmd.exe", "/c", executable, "app-server");
        }
        return new ProcessBuilder(executable, "app-server");
    }

    /** App Server 连接初始化。 */
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
     * 创建 Thread。
     * Thread 可以理解成一个持续存在的 Agent 聊天窗口；workspace 会作为 thread/start.cwd。
     */
    public CompletableFuture<String> startThread(String workspace) {
        ObjectNode params = mapper.createObjectNode();
        params.put("cwd", workspace);
        return request("thread/start", params)
                .thenApply(result -> result.path("thread").path("id").asText());
    }

    /** 查询某个 workspace 下 Codex 当前能发现的 Skills，主要用于健康检查。 */
    public CompletableFuture<JsonNode> listSkills(String workspace, boolean forceReload) {
        ObjectNode params = mapper.createObjectNode();
        params.putArray("cwds").add(workspace);
        params.put("forceReload", forceReload);
        return request("skills/list", params);
    }

    /**
     * 启动普通 Turn，不显式指定 Skill，由 Codex 自己做 Skill Selection。
     */
    public CompletableFuture<String> startTurn(String threadId, String message) {
        return startTurnInternal(threadId, message, null, null);
    }

    /** 启动显式指定 Skill 的 Turn。 */
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
     * 发送需要 Response 的 JSON-RPC Request。
     * 使用 requestId + CompletableFuture 解决并发请求响应乱序问题。
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

    /** 发送无需 Response 的 JSON-RPC Notification。 */
    private void notify(String method, JsonNode params) throws Exception {
        ensureRunning();
        ObjectNode message = mapper.createObjectNode();
        message.put("method", method);
        message.set("params", params);
        write(message);
    }

    /** stdio transport 一行一条 JSON 消息。 */
    private void write(JsonNode message) throws Exception {
        synchronized (writeLock) {
            writer.write(mapper.writeValueAsString(message));
            writer.newLine();
            writer.flush();
        }
    }

    /**
     * 唯一 stdout Reader Loop。
     * 所有 Response、Notification、Server Request 都由这个线程统一读取后再分发。
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
     * JSON-RPC 消息分类：
     * 1. 有 id、无 method = Response；
     * 2. 有 id、有 method = App Server -> Java 的 Server Request；
     * 3. 有 method、无 id = Notification / Event。
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

    /** 将普通 Response 分发给对应的 CompletableFuture。 */
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
     * 处理 App Server 主动发给 Java 的 Server Request。
     *
     * <p>Codex 当前把 MCP Tool Approval 通过 {@code mcpServer/elicitation/request} 发送给宿主应用，
     * 并在 meta 中使用 {@code codex_approval_kind=mcp_tool_call} 标识“这是一次 MCP Tool 审批”。</p>
     */
    private void handleServerRequest(JsonNode request) throws Exception {
        String method = request.path("method").asText();
        if (MCP_ELICITATION_REQUEST.equals(method) && isMcpToolApproval(request)) {
            handleMcpToolApproval(request);
            return;
        }

        // 对暂未支持的 Server Request 立即返回错误，不能一直不回复，否则 Turn 会挂住。
        ObjectNode response = mapper.createObjectNode();
        response.set("id", request.get("id"));
        ObjectNode error = response.putObject("error");
        error.put("code", -32601);
        error.put("message", "暂不支持的 Server Request: " + method);
        write(response);
    }

    /** 判断一次 elicitation 是否是 Codex 发起的 MCP Tool Approval。 */
    private boolean isMcpToolApproval(JsonNode request) {
        JsonNode params = request.path("params");
        JsonNode meta = params.path("meta");
        if (meta.isMissingNode() || meta.isNull()) {
            // 兼容底层 MCP wire payload 可能使用 _meta 的情况。
            meta = params.path("_meta");
        }
        return MCP_TOOL_APPROVAL_KIND.equals(meta.path("codex_approval_kind").asText());
    }

    /**
     * 完成一次 MCP Tool Approval 的 Request -> Decision -> Response。
     *
     * <p>当前 ApprovalDecisionService 用配置模拟人工决策；生产环境应由审批中心异步决定。</p>
     */
    private void handleMcpToolApproval(JsonNode request) throws Exception {
        ApprovalDecisionService.ApprovalDecision decision = approvalDecisionService.decide(request);

        ObjectNode response = mapper.createObjectNode();
        response.set("id", request.get("id"));
        ObjectNode result = response.putObject("result");
        result.put("action", decision.wireValue());

        // MCP elicitation 的 accept 响应允许携带 content。
        // Tool Approval 本身不需要额外表单数据，因此返回空对象即可。
        if (decision == ApprovalDecisionService.ApprovalDecision.ACCEPT) {
            result.putObject("content");
        }

        write(response);
        log.info("已回复 MCP Tool 审批，decision={}", decision.wireValue());
    }

    /** 处理 App Server 推送的 Notification / Event。 */
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

    /** stderr 单独消费，避免污染 stdout JSON-RPC 协议流。 */
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

    private void ensureRunning() {
        if (!running) {
            throw new IllegalStateException("Codex App Server 尚未启动");
        }
    }

    private void failAll(Throwable error) {
        pendingRequests.forEach((id, future) -> future.completeExceptionally(error));
        pendingRequests.clear();
    }

    /** Spring Bean 销毁时关闭 App Server 子进程。 */
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

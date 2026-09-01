package com.example.hanresstest.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

/**
 * 审批决策服务。
 *
 * <p>当前项目为了学习审批协议，先通过配置项决定统一返回 accept / decline / cancel。
 * 正式生产环境不要把审批结果写死在这里，而应替换为：审批单入库 -> 前端审批中心 -> 人工确认 -> 返回结果。</p>
 *
 * <p>把审批逻辑单独抽成 Service 的原因是：CodexAppServerClient 只负责协议通信，
 * 不应该决定某个业务动作究竟能不能执行。</p>
 */
@Service
public class ApprovalDecisionService {

    private static final Logger log = LoggerFactory.getLogger(ApprovalDecisionService.class);

    private final ApprovalDecision defaultDecision;

    public ApprovalDecisionService(
            @Value("${agent.approval.default-decision:decline}") String defaultDecision
    ) {
        this.defaultDecision = ApprovalDecision.from(defaultDecision);
    }

    /**
     * 对一次 MCP Tool Approval 请求做决策。
     *
     * @param request App Server 发来的完整 mcpServer/elicitation/request
     * @return 本次审批结果
     */
    public ApprovalDecision decide(JsonNode request) {
        JsonNode params = request.path("params");

        log.info(
                "收到 MCP Tool 审批请求，serverName={}, threadId={}, turnId={}, message={}",
                params.path("serverName").asText(),
                params.path("threadId").asText(),
                params.path("turnId").asText(),
                params.path("message").asText()
        );
        log.info("当前 Demo 审批结果：{}", defaultDecision.wireValue());

        return defaultDecision;
    }

    public enum ApprovalDecision {
        ACCEPT("accept"),
        DECLINE("decline"),
        CANCEL("cancel");

        private final String wireValue;

        ApprovalDecision(String wireValue) {
            this.wireValue = wireValue;
        }

        public String wireValue() {
            return wireValue;
        }

        public static ApprovalDecision from(String value) {
            if (value == null) {
                return DECLINE;
            }
            return switch (value.trim().toLowerCase()) {
                case "accept" -> ACCEPT;
                case "cancel" -> CANCEL;
                default -> DECLINE;
            };
        }
    }
}

package com.example.hanresstest.service;

import com.example.hanresstest.component.CodexAppServerClient;
import com.example.hanresstest.config.AgentCatalogProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * 面向业务 Agent 的 Codex Runtime 适配层。
 *
 * <p>业务层只需要通过 agentId 调用本类，不需要了解 App Server 的 JSON-RPC 协议细节。
 * 本类负责把 Agent 定义转换成 Codex 的 Thread / Turn 调用，同时保证底层
 * {@link CodexAppServerClient} 与具体的订单、财务、合同等业务 Agent 解耦。</p>
 */
@Service
public class CodexAgentRuntime implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(CodexAgentRuntime.class);
    private static final Duration SKILL_VALIDATION_TIMEOUT = Duration.ofSeconds(15);

    private final CodexAppServerClient client;
    private final AgentCatalogProperties catalog;

    public CodexAgentRuntime(CodexAppServerClient client, AgentCatalogProperties catalog) {
        this.client = client;
        this.catalog = catalog;
    }

    /**
     * 应用启动流程：只启动一次 Codex App Server，然后校验所有已配置 Agent 的必需 Skill。
     *
     * <p>这里调用 skills/list 的目的只是做启动期健康检查和快速失败，
     * 不是用来“注册” Skill。Skill 的真正发现由 Codex Harness 根据 Agent workspace 自动完成。</p>
     */
    @Override
    public void run(ApplicationArguments args) throws Exception {
        client.start();

        for (Map.Entry<String, AgentCatalogProperties.AgentDefinition> entry : catalog.definitions().entrySet()) {
            validateRequiredSkills(entry.getKey(), entry.getValue());
        }
    }

    /**
     * 为指定 Agent 创建一段新的 Codex 会话。
     *
     * <p>这里会先根据 agentId 找到 Agent 定义，再把 Agent 的 workspace 转换成
     * thread/start 的 cwd 参数。Codex 会基于这个 cwd 发现项目级 Skill。</p>
     */
    public CompletableFuture<String> startConversation(String agentId) {
        AgentCatalogProperties.AgentDefinition definition = catalog.require(agentId);
        return client.startThread(resolveWorkspace(definition).toString());
    }

    /**
     * 自动 Skill 选择模式。
     *
     * <p>这一轮不会强制指定某个 Skill。Codex 会根据当前 Thread 已发现的 Skill 元数据
     * 以及用户输入，自主判断是否需要使用某个 Skill。</p>
     */
    public CompletableFuture<String> startTurnAuto(String threadId, String message) {
        return client.startTurn(threadId, message);
    }

    /**
     * 显式 Skill 模式。
     *
     * <p>适用于业务系统已经明确知道应该使用哪个 Skill 的确定性场景，例如用户点击
     * “订单异常分析”按钮。此时无需再让模型猜测应该选择哪个 Skill。</p>
     */
    public CompletableFuture<String> startTurnWithSkill(
            String agentId,
            String threadId,
            String skillName,
            String message
    ) {
        AgentCatalogProperties.AgentDefinition definition = catalog.require(agentId);
        Path workspace = resolveWorkspace(definition);
        Path skillFile = workspace
                .resolve(".agents")
                .resolve("skills")
                .resolve(skillName)
                .resolve("SKILL.md")
                .normalize();

        Path skillsRoot = workspace.resolve(".agents").resolve("skills").normalize();
        if (!skillFile.startsWith(skillsRoot)) {
            throw new IllegalArgumentException("非法的 Skill 名称: " + skillName);
        }
        if (!Files.isRegularFile(skillFile)) {
            throw new IllegalStateException("Skill 文件不存在: " + skillFile);
        }

        return client.startTurnWithSkill(threadId, message, skillName, skillFile.toString());
    }

    /**
     * 手动重新校验某个 Agent 的必需 Skill，主要用于健康检查、运维或 Skill 变更后的重新验证。
     */
    public Set<String> validateRequiredSkills(String agentId) throws Exception {
        return validateRequiredSkills(agentId, catalog.require(agentId));
    }

    /**
     * 查询 Codex 当前从指定 workspace 发现的 Skill，并与 Agent 配置中的 required-skills 对比。
     * 如果缺少必需 Skill，则直接抛出异常，避免服务处于“能启动但不能正确工作”的半可用状态。
     */
    private Set<String> validateRequiredSkills(
            String agentId,
            AgentCatalogProperties.AgentDefinition definition
    ) throws Exception {
        Path workspace = resolveWorkspace(definition);
        if (!Files.isDirectory(workspace)) {
            throw new IllegalStateException("Agent workspace 不存在: " + workspace);
        }

        JsonNode response = client
                .listSkills(workspace.toString(), true)
                .get(SKILL_VALIDATION_TIMEOUT.toMillis(), TimeUnit.MILLISECONDS);

        Set<String> discovered = new HashSet<>();
        for (JsonNode cwdEntry : response.path("data")) {
            for (JsonNode skill : cwdEntry.path("skills")) {
                if (skill.path("enabled").asBoolean(true)) {
                    String name = skill.path("name").asText();
                    if (!name.isBlank()) {
                        discovered.add(name);
                    }
                }
            }
        }

        Set<String> missing = new HashSet<>(definition.requiredSkills());
        missing.removeAll(discovered);
        if (!missing.isEmpty()) {
            throw new IllegalStateException(
                    "Agent '" + agentId + "' 未就绪。Codex 未能从 workspace " + workspace
                            + " 发现必需 Skill: " + missing
            );
        }

        log.info("Agent '{}' 已就绪，Codex 已发现 Skills: {}", agentId, discovered);
        return Set.copyOf(discovered);
    }

    /**
     * 把 Agent 配置中的 workspace 解析成绝对路径，确保本地、Docker、Linux 等环境使用同一套代码。
     */
    private Path resolveWorkspace(AgentCatalogProperties.AgentDefinition definition) {
        if (definition.workspace() == null || definition.workspace().isBlank()) {
            throw new IllegalStateException("必须配置 Agent workspace");
        }
        return Path.of(definition.workspace()).toAbsolutePath().normalize();
    }
}

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
 * Agent-facing Codex runtime adapter.
 *
 * <p>Business code talks to this service by agentId. It translates an Agent definition into
 * Codex thread/turn calls while the low-level client remains completely agent-neutral.</p>
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
     * Production startup flow: start App Server once, then validate every configured Agent's
     * required skills. skills/list is a readiness check; it is not how skills are registered.
     */
    @Override
    public void run(ApplicationArguments args) throws Exception {
        client.start();

        for (Map.Entry<String, AgentCatalogProperties.AgentDefinition> entry : catalog.definitions().entrySet()) {
            validateRequiredSkills(entry.getKey(), entry.getValue());
        }
    }

    public CompletableFuture<String> startConversation(String agentId) {
        AgentCatalogProperties.AgentDefinition definition = catalog.require(agentId);
        return client.startThread(resolveWorkspace(definition).toString());
    }

    /**
     * No skill is forced into the turn. Codex sees skills discovered from the thread cwd and
     * may select one based on its name/description and the user's request.
     */
    public CompletableFuture<String> startTurnAuto(String threadId, String message) {
        return client.startTurn(threadId, message);
    }

    /**
     * Deterministic mode for a business action that already knows the desired skill.
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
            throw new IllegalArgumentException("Invalid skill name: " + skillName);
        }
        if (!Files.isRegularFile(skillFile)) {
            throw new IllegalStateException("Skill file does not exist: " + skillFile);
        }

        return client.startTurnWithSkill(threadId, message, skillName, skillFile.toString());
    }

    public Set<String> validateRequiredSkills(String agentId) throws Exception {
        return validateRequiredSkills(agentId, catalog.require(agentId));
    }

    private Set<String> validateRequiredSkills(
            String agentId,
            AgentCatalogProperties.AgentDefinition definition
    ) throws Exception {
        Path workspace = resolveWorkspace(definition);
        if (!Files.isDirectory(workspace)) {
            throw new IllegalStateException("Agent workspace does not exist: " + workspace);
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
                    "Agent '" + agentId + "' is not ready. Codex did not discover required skills "
                            + missing + " from workspace " + workspace
            );
        }

        log.info("Agent '{}' ready. Codex discovered skills: {}", agentId, discovered);
        return Set.copyOf(discovered);
    }

    private Path resolveWorkspace(AgentCatalogProperties.AgentDefinition definition) {
        if (definition.workspace() == null || definition.workspace().isBlank()) {
            throw new IllegalStateException("Agent workspace must be configured");
        }
        return Path.of(definition.workspace()).toAbsolutePath().normalize();
    }
}

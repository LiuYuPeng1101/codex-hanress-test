package com.example.hanresstest.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;
import java.util.Map;

@ConfigurationProperties(prefix = "agent")
public record AgentCatalogProperties(
        Map<String, AgentDefinition> definitions
) {
    public AgentCatalogProperties {
        definitions = definitions == null ? Map.of() : Map.copyOf(definitions);
    }

    public AgentDefinition require(String agentId) {
        AgentDefinition definition = definitions.get(agentId);
        if (definition == null) {
            throw new IllegalArgumentException("Unknown agent: " + agentId);
        }
        return definition;
    }

    public record AgentDefinition(
            String workspace,
            List<String> requiredSkills
    ) {
        public AgentDefinition {
            requiredSkills = requiredSkills == null ? List.of() : List.copyOf(requiredSkills);
        }
    }
}

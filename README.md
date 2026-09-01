# codex-hanress-test

Spring Boot + Codex App Server / Codex Harness 学习项目。

完整示例与生产级 Skill Discovery / Skill Selection 说明见：

- `hanress-test/README.md`

当前重点：

- Java 如何通过 App Server 控制 Codex Harness
- Spring Boot 如何通过 MCP 暴露业务 Tool / Resource / Prompt
- `.agents/skills` 如何被 Codex 按 Agent workspace 自动发现
- 如何区分自动 Skill Selection 与显式 Skill Selection
- 如何避免每个 Agent 重复实现 `CodexAppServerClient`

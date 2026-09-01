# codex-hanress-test

这个仓库现在包含两个互补的学习项目：

- `hanress-test/`：Java / Spring Boot 直接通过 Codex App Server 学习 Codex Harness 底层协议、Thread / Turn、MCP、Skill、Approval。
- `codex-agent-python/`：标准 FastAPI Agent Service，使用官方 `openai-codex` Python SDK，作为以后真实企业 Agent Service 的雏形。

## Java 版本

完整说明：

- `hanress-test/README.md`

重点：

- Java 如何通过 App Server 控制 Codex Harness
- Spring Boot 如何通过 MCP 暴露业务 Tool / Resource / Prompt
- `.agents/skills` 如何被 Codex 按 Agent workspace 自动发现
- Approval / Server Request 如何工作

## Python 版本

完整说明：

- `codex-agent-python/README.md`

重点：

- 标准 FastAPI 项目结构
- 官方 `openai-codex` Python SDK
- FastAPI lifespan 管理一份 `AsyncCodex` Runtime
- HTTP API 创建 Thread、执行 Turn
- `.agents/skills` 随 Agent Service 一起部署
- 后续通过 MCP 调用现有 Java 业务系统

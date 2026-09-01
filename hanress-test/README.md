# Codex Harness + Spring Boot Demo

这个模块用于学习如何把现有 Java / Spring Boot 业务能力接入 Codex Harness，并把学习阶段的 Demo 写法逐步重构成可用于正式项目的结构。

当前示例包含：

- Codex App Server：Spring Boot 通过 JSON-RPC 控制 Codex Runtime
- MCP Server：Spring AI Streamable HTTP MCP
- Tool：`get_order_status`
- Resource：`order://status/guide`
- Prompt：`order_analysis`
- Skill：`.agents/skills/order-analysis/SKILL.md`

---

# 1. 当前项目目录结构

```text
hanress-test/
├── .agents/
│   └── skills/
│       └── order-analysis/
│           ├── SKILL.md
│           └── references/
│               └── status-rules.md
│
├── src/main/java/com/example/hanresstest/
│   ├── HanressTestApplication.java
│   │
│   ├── component/
│   │   ├── CodexAppServerClient.java
│   │   ├── OrderPrompts.java
│   │   └── OrderResources.java
│   │
│   ├── config/
│   │   ├── AgentCatalogProperties.java
│   │   ├── CodexRuntimeProperties.java
│   │   └── McpToolConfig.java
│   │
│   └── service/
│       ├── CodexAgentRuntime.java
│       └── OrderService.java
│
├── src/main/resources/
│   └── application.yml
│
├── pom.xml
├── .gitignore
└── README.md
```

`target/`、`.idea/` 等生成物不应该提交到 Git，已经通过 `.gitignore` 排除。

---

# 2. 项目架构

```text
业务系统 / 未来的 Agent Gateway
              |
              v
       CodexAgentRuntime
       - 根据 agentId 找 Agent Definition
       - 决定 workspace
       - 创建 Conversation / Turn
       - 校验 required skills
              |
              v
     CodexAppServerClient
       - 启动 codex app-server
       - initialize
       - JSON-RPC request/response
       - thread/start
       - turn/start
       - skills/list
       - event / server request
              |
              v
        codex app-server
              |
              v
         Codex Harness
          /         \
         /           \
      Skills          MCP
                        |
                        v
             Spring Boot MCP Server
                /       |       \
               /        |        \
            Tool     Resource   Prompt
              |
              v
         OrderService
```

最重要的职责边界：

```text
CodexAppServerClient
= Codex Runtime 通信基础设施
= 不应该知道 order / finance / contract 等业务概念

CodexAgentRuntime
= Agent Runtime Adapter
= 根据 agentId 决定 workspace、required skills 等 Agent 配置

Skill
= Agent 完成专业任务的方法/SOP

MCP Tool
= Agent 可以调用的真实业务能力
```

以后新增 Finance Agent、Contract Agent 时，不复制 `CodexAppServerClient`。

---

# 3. cwd 到底是什么？

`cwd` 是 **current working directory，当前工作目录**。

它不是 Skill 的路径，也不是 `SKILL.md` 的路径。

它表示：

> “这个 Codex Thread 当前在哪个 Agent 工作空间里运行？”

例如本地项目：

```text
D:/daima/codex-agent/hanress-test
```

这个目录就是 order Agent 的 workspace。

创建 Thread 时 Java 最终发送：

```json
{
  "method": "thread/start",
  "params": {
    "cwd": "D:/daima/codex-agent/hanress-test"
  }
}
```

然后 Codex 以这个目录作为当前项目上下文。

因此可以理解为：

```text
cwd
 |
 v
Agent Workspace
 |
 +-- .agents/skills
 +-- 项目文件
 +-- 其他 Codex 可以在当前上下文感知的内容
```

---

# 4. Skill 到底是怎么让 Codex 知道的？

不是 Java 调用 `registerSkill()`。

生产级思路是：

```text
1. Skill 跟 Agent 一起部署到 workspace

2. 创建 Codex Thread 时传 cwd = workspace

3. Codex Harness 根据 workspace 发现 .agents/skills 下的 Skill

4. skills/list 只负责校验是否发现成功
```

例如：

```text
/app
└── .agents
    └── skills
        └── order-analysis
            └── SKILL.md
```

Thread：

```json
{
  "method": "thread/start",
  "params": {
    "cwd": "/app"
  }
}
```

于是关系就是：

```text
cwd = /app
   |
   v
/app/.agents/skills
   |
   v
order-analysis/SKILL.md
   |
   v
Codex Harness 发现 order-analysis
```

所以你的理解是对的：

> Docker 部署时，把 `.agents/skills` 一起打进 Agent Service 镜像，然后把容器中的 Agent workspace（例如 `/app`）作为 `cwd` 传给 Codex，Codex 就能从这个 workspace 发现 Skills。

不过要注意：**Skill 发现不是 Docker 专属机制。** 本地 Windows、Linux、Docker 都一样，核心都是：

```text
正确的 workspace + 正确的 cwd + .agents/skills
```

---

# 5. 本项目如何配置 workspace

```yaml
codex:
  runtime:
    executable: ${CODEX_EXECUTABLE:codex}
    startup-timeout: 30s

agent:
  definitions:
    order:
      workspace: ${AGENT_ORDER_WORKSPACE:.}
      required-skills:
        - order-analysis
```

本地开发：

```text
AGENT_ORDER_WORKSPACE=.
```

表示 Spring Boot 的工作目录就是 Agent workspace。

Docker / Linux 正式环境推荐：

```bash
AGENT_ORDER_WORKSPACE=/app
CODEX_EXECUTABLE=/usr/local/bin/codex
```

Java 源码不应该写死：

```text
D:/daima/...
```

---

# 6. `skills/list` 为什么还存在？

`skills/list` 不是注册 Skill。

它用于：

- 启动健康检查
- readiness / fail-fast
- Agent Console 展示可用 Skills
- Skill 变更后的重新检查
- 排查 Skill Discovery 问题

本项目启动流程：

```text
Spring Boot start
      |
      v
start codex app-server
      |
      v
initialize
      |
      v
skills/list(workspace, forceReload=true)
      |
      v
检查 required-skills
      |
      +-- order-analysis 存在 --> Agent Ready
      |
      +-- 不存在 --> 启动失败
```

这样生产环境不会等真实用户请求进来后才发现 Skill 配置错误。

---

# 7. Codex 如何自动使用 Skill？

“发现 Skill”和“使用 Skill”是两件事。

```text
Discovery
= Codex 知道 order-analysis 存在

Selection
= 当前用户请求是否应该使用 order-analysis
```

自动模式：

```java
codexAgentRuntime.startTurnAuto(
        threadId,
        "帮我分析订单1001为什么还没收到"
);
```

此时没有强制指定 Skill。

Codex 根据已发现 Skill 的 `name`、`description` 和用户请求判断是否使用。

因此 `SKILL.md` front matter 很重要：

```yaml
---
name: order-analysis
description: Analyze order status, delivery delays, and order anomalies. Use this skill when the user asks where an order is, why an order is delayed, whether an order is abnormal, or requests an order status analysis.
---
```

`description` 要写清楚两件事：

1. Skill 能做什么
2. 什么意图下应该使用它

自动选择是模型决策，不是 Java `if/else`，所以不能把它理解成 100% 确定性的路由。

---

# 8. 生产关键流程为什么还要支持显式 Skill？

如果用户是在业务系统里点击：

```text
【订单异常分析】
```

业务系统已经知道当前任务就是 `order-analysis`，没有必要再让模型猜。

本项目支持：

```java
codexAgentRuntime.startTurnWithSkill(
        "order",
        threadId,
        "order-analysis",
        "分析订单1001为什么还没收到"
);
```

Runtime 根据 workspace 自动解析：

```text
<workspace>/.agents/skills/order-analysis/SKILL.md
```

推荐原则：

```text
自由聊天 / Copilot
        -> 自动 Skill Selection

确定性的业务按钮 / Workflow / API
        -> 显式 Skill Selection
```

---

# 9. Skill 与 MCP 的关系

```text
Skill
= 应该怎么完成任务

MCP Tool
= 能执行什么真实业务动作
```

例如 `order-analysis` Skill：

```text
1. 找到 orderId
2. 不允许猜状态
3. 调 get_order_status
4. 根据规则解释
5. 输出结论
```

真实数据：

```text
Codex Harness
      |
      | MCP
      v
Spring Boot MCP Server
      |
      v
get_order_status
      |
      v
OrderService
```

所以 Skill 不负责替代 Tool，Tool 也不负责替代 Skill。

---

# 10. MCP 三类能力

当前 Demo 保留同一订单领域的 MCP 示例：

```text
Tool
get_order_status
-> 执行业务查询

Resource
order://status/guide
-> 提供订单状态说明

Prompt
order_analysis
-> 提供可复用订单分析提示模板
```

MCP Inspector 示例：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/list
```

调用订单 Tool：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/call --tool-name get_order_status --tool-arg orderId=1001
```

读取 Resource：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method resources/read --uri order://status/guide
```

---

# 11. Docker 部署时 Skill 如何被发现

推荐镜像：

```text
/app/
├── app.jar
└── .agents/
    └── skills/
        └── order-analysis/
            ├── SKILL.md
            └── references/
```

环境变量：

```bash
AGENT_ORDER_WORKSPACE=/app
CODEX_EXECUTABLE=/usr/local/bin/codex
```

运行链：

```text
Container start
      |
      v
Spring Boot
      |
      v
CodexAgentRuntime
      |
      v
thread/start cwd=/app
      |
      v
Codex Harness
      |
      v
发现 /app/.agents/skills/order-analysis
```

这就是 Skill 随 Agent Service 一起版本化和部署的方式。

---

# 12. 新增第二个 Agent

例如 Finance Agent：

```yaml
agent:
  definitions:
    order:
      workspace: ${AGENT_ORDER_WORKSPACE:.}
      required-skills:
        - order-analysis

    finance:
      workspace: ${AGENT_FINANCE_WORKSPACE:/app/finance}
      required-skills:
        - monthly-financial-analysis
        - cashflow-analysis
```

对应：

```text
/app/finance/.agents/skills/
├── monthly-financial-analysis/SKILL.md
└── cashflow-analysis/SKILL.md
```

仍然复用：

```text
CodexAgentRuntime
CodexAppServerClient
```

不要创建：

```text
OrderCodexClient
FinanceCodexClient
ContractCodexClient
```

Runtime 是公共能力，Agent Definition / Skill / MCP 才是业务差异。

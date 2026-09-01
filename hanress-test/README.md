# Codex Harness + Spring Boot Demo

这个模块用于学习如何把现有 Java / Spring Boot 业务能力接入 Codex Harness。

当前示例包含：

- Codex App Server：Spring Boot 通过 JSON-RPC 控制 Codex Runtime
- MCP Server：Spring AI Streamable HTTP MCP
- Tool：`get_order_status`
- Resource：订单状态说明
- Prompt：MCP Prompt 示例
- Skill：`.agents/skills/order-analysis/SKILL.md`

## 1. 生产级职责边界

不要为每一个 Agent 复制一份 `CodexAppServerClient`。

推荐分层：

```text
Business / Agent Gateway
        |
        v
CodexAgentRuntime             <-- 按 agentId 管 workspace / skill
        |
        v
CodexAppServerClient          <-- 只负责 App Server 进程和 JSON-RPC
        |
        v
codex app-server
        |
        v
Codex Harness
```

`CodexAppServerClient` 不应该知道 `order-agent`、`finance-agent`、`contract-agent` 等业务概念。
不同 Agent 的 workspace、必需 Skill 等信息放到 Agent Definition 配置中。

当前示例配置：

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

本地开发可使用 `.`；Docker / Linux 中推荐显式设置：

```bash
AGENT_ORDER_WORKSPACE=/app
CODEX_EXECUTABLE=/usr/local/bin/codex
```

---

# 2. 如何让 Codex 发现 Skill

## 2.1 目录约定

项目级 Skill 放在 Agent workspace 下的 `.agents/skills`：

```text
<workspace>/
└── .agents/
    └── skills/
        └── order-analysis/
            ├── SKILL.md
            └── references/
                └── status-rules.md
```

本项目：

```text
hanress-test/
└── .agents/skills/order-analysis/SKILL.md
```

## 2.2 `thread/start.cwd` 是发现 Skill 的关键

创建 Codex Thread 时必须把该 Agent 的 workspace 传给 App Server：

```json
{
  "method": "thread/start",
  "params": {
    "cwd": "/app"
  }
}
```

Codex 会以该 `cwd` 为项目上下文发现可用的项目级 Skills。

在本项目中，业务代码不直接调用 `CodexAppServerClient.startThread()` 拼业务参数，而是：

```java
String threadId = codexAgentRuntime
        .startConversation("order")
        .get();
```

`CodexAgentRuntime` 从 `AgentCatalogProperties` 读取 order Agent 的 workspace，再转换成 `thread/start`。

## 2.3 不需要 `registerSkill()`

正常运行时不要：

- 手工读取 `SKILL.md` 再拼进 system prompt
- 每个 Turn 都调用 `skills/list`
- 在 `CodexAppServerClient` 中硬编码 Windows 绝对路径
- 给每个 Agent 复制一个 App Server Client

Skill Discovery 是 Codex Harness 的职责。

---

# 3. `skills/list` 的正确用途

`skills/list` 不是注册 Skill 的步骤，它应该主要用于：

- Agent Service 启动健康检查
- Agent Console 展示当前可用 Skill
- Skill 文件变化后的重新校验
- 排查 Skill 为什么没有被发现

本项目在 Spring Boot 启动时：

```text
start App Server
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
      v
Agent Ready / 启动失败
```

`CodexAgentRuntime` 会检查：

```yaml
required-skills:
  - order-analysis
```

如果 Codex 没有发现 `order-analysis`，应用会直接启动失败，而不是等真实用户请求进来后才发现 Agent 配置错误。

这是 readiness / fail-fast 机制，不是每轮 Turn 的业务流程。

---

# 4. Codex 如何自动使用 Skill

发现 Skill 和使用 Skill 是两件事。

```text
Discovery
Codex 知道有哪些 Skills

Selection
当前 Turn 是否应该使用某个 Skill
```

## 4.1 自动选择模式

普通对话直接发送文本：

```java
codexAgentRuntime.startTurnAuto(
        threadId,
        "帮我分析订单1001为什么还没收到"
);
```

此时没有强制指定 Skill。
Codex 会根据已发现 Skill 的元数据和当前请求判断是否应该使用它。

因此 `SKILL.md` 顶部的 front matter 非常重要：

```yaml
---
name: order-analysis
description: Analyze order status, delivery delays, and order anomalies. Use this skill when the user asks where an order is, why an order is delayed, whether an order is abnormal, or requests an order status analysis.
---
```

`description` 应写清楚：

1. 这个 Skill 做什么
2. 什么用户意图下应该使用它

不要只写：

```yaml
description: Order skill
```

这种描述很难让模型稳定完成 Skill routing。

> 自动选择是模型决策，不应该把它理解成确定性的 Java `if/else`。

---

# 5. 生产关键流程：显式指定 Skill

如果业务系统本来已经知道用户点的是“订单异常分析”，没有必要再让模型猜应该使用哪个 Skill。

本项目提供：

```java
codexAgentRuntime.startTurnWithSkill(
        "order",
        threadId,
        "order-analysis",
        "分析订单1001为什么还没收到"
);
```

Runtime 会基于 Agent workspace 解析：

```text
<workspace>/.agents/skills/order-analysis/SKILL.md
```

然后在 `turn/start.input` 中加入 Skill item：

```json
[
  {
    "type": "text",
    "text": "分析订单1001为什么还没收到"
  },
  {
    "type": "skill",
    "name": "order-analysis",
    "path": "/app/.agents/skills/order-analysis/SKILL.md"
  }
]
```

推荐原则：

```text
开放式 Copilot / 用户自由聊天
        -> 自动 Skill Selection

确定性的业务按钮 / Workflow / API
        -> 显式 Skill Selection
```

---

# 6. Skill 与 MCP 的关系

不要把 Skill 当 Tool。

```text
Skill
= Agent 应该如何完成某类专业任务

MCP Tool
= Agent 可以执行什么业务动作
```

本项目的 `order-analysis` Skill 会告诉 Agent：

1. 识别 orderId
2. 不允许猜订单实时状态
3. 调用 `get_order_status`
4. 根据业务规则解释状态
5. 输出结论

真正订单数据由 MCP Tool 提供：

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

所以一个业务 Agent 通常是：

```text
Agent = Instructions + Skills + MCP/Tools + Policies + Evals
```

Harness 负责 Agent Loop、Context、Tool orchestration 等运行时能力。

---

# 7. MCP 三类能力

当前 Demo 同时用于理解 MCP：

```text
Tools
-> 我能做什么

Resources
-> 我有哪些内容可以读取

Prompts
-> 我有哪些可复用 Prompt 模板
```

使用 MCP Inspector 测试：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/list
```

调用订单 Tool：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/call --tool-name get_order_status --tool-arg orderId=1001
```

资源列表：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method resources/list
```

读取资源：

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method resources/read --uri order://status/guide
```

---

# 8. Docker / 多环境部署

不要在 Java 源码里写：

```text
D:/daima/...
```

镜像推荐结构：

```text
/app/
├── app.jar
└── .agents/
    └── skills/
        └── order-analysis/
            └── SKILL.md
```

Docker 环境：

```bash
AGENT_ORDER_WORKSPACE=/app
CODEX_EXECUTABLE=/usr/local/bin/codex
```

这样 Skill 与 Agent Service 版本一起发布，Java 代码不依赖开发机目录。

---

# 9. 新增第二个 Agent 时怎么做

例如新增 finance Agent，不要复制 `CodexAppServerClient`。

增加定义：

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

再提供：

```text
/app/finance/.agents/skills/
├── monthly-financial-analysis/SKILL.md
└── cashflow-analysis/SKILL.md
```

所有 Agent 仍然共用同一套：

```text
CodexAgentRuntime
CodexAppServerClient
```

这就是 Runtime 与业务 Agent 解耦的核心。

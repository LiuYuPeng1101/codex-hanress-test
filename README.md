# Codex Single Agent Project

这个仓库现在只做 **一个生产级业务 Agent**。

核心边界固定为：

```text
内容层
Skill / Tool / MCP / Policy
        ↓
容器层
Codex Harness
Agent Loop / Thread / Turn / Context / Compaction / Sandbox
        ↓
最小治理层
Auth / Approval / Audit / OTel / Business Authorization
```

不再把目标设成 Agent Platform、Agent Control Plane、Agent Registry、Runtime Scheduler 或多 Runtime Router。

## 运行链路

```text
Business System
      ↓
codex-agent-python
Single Agent Service
      ↓
Codex Harness
      ↓
Skill + MCP + Tool Policy
      ↓
hanress-test
Order MCP Adapter
      ↓
Real OMS / Business System
```

## `codex-agent-python/`

负责当前唯一 Agent 的：

```text
AgentDefinition
Skill workspace
MCP / Tool Policy
Codex Thread / Turn / Resume
Conversation → Codex Thread 映射
Approval
Sandbox
Event / SSE
OpenTelemetry
Context / Compaction 运维入口
API Auth
```

它不是新的 Harness。Agent Loop、Context 管理、Compaction、Tool Dispatch 等容器能力继续交给 Codex Harness。

详细的“为什么这样开发、代码怎么解决”见 `codex-agent-python/README.md`。

## `hanress-test/`

当前只作为 **Order MCP Adapter**：

```text
MCP Tool
→ OrderService
→ OrderGateway
→ Real OMS
```

Java 不运行第二套 Codex Runtime，也不维护虚假订单状态。

## 当前明确不做

```text
Agent Registry
多 Agent Control Plane
Runtime Scheduler
Runtime Lease
Runtime Router
Agent Marketplace
统一 Agent Gateway
自研 Agent Loop
自研 Context Manager
自研 Observability Platform
```

等真正出现多个 Agent、多个团队、统一 MCP/LLM 治理等需求时，再从真实重复能力中抽平台层。

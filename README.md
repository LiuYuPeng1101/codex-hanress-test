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

## 如果以后开发第二个 Agent，哪些可以直接复用？

例如现在是订单 / 售后 Agent，以后再开发合同 Agent、财务 Agent 或客服 Agent，下面这些工程能力原则上可以直接复用：

```text
FastAPI Service 结构
app/runtime/codex_runtime.py
Conversation → Codex Thread 映射
Service Auth
Approval Framework
Codex Event Mapper
SSE API
OpenTelemetry
Dockerfile / 部署骨架
PostgreSQL 基础能力
Eval Runner
```

其中最核心的是：

```text
CodexRuntime
= 把当前 Agent 的 MCP / Tool Policy / Sandbox 接到 Codex Harness

Conversation
= 业务 conversation_id ↔ Codex thread_id

Approval / Auth / Event / OTel
= 单 Agent 的最小生产治理
```

这些能力和“订单”本身没有强业务绑定，所以第二个 Agent 不应该重新实现一遍。

## 第二个 Agent 必须自己开发什么？

真正需要重新开发的是内容层和对应的业务能力：

```text
Skill
MCP / Tool
Tool Contract
Tool Policy
Sandbox Policy
业务授权契约
Eval Cases
```

例如：

```text
订单 Agent
├── Skill: order-analysis
├── Tool: get_order_status / cancel_order
└── Policy: cancel_order → approval

合同 Agent
├── Skill: contract-review
├── Tool: get_contract / search_clause / submit_review
└── Policy: submit_review → approval
```

所以以后开发第二个 Agent 的正确方式不是复制整套 Runtime，而是：

```text
复用工程壳
        +
重新开发 Skill / MCP / Tool / Policy / Eval
```

如果未来多个 Agent 真的产生大量重复代码，再从真实重复中抽共享库或平台能力；现在不提前做 Agent Platform。

## 单 Agent 很多人使用时，先解决“扩容”，不是“多 Agent 平台”

一个 Agent 可以同时服务很多用户：

```text
用户 A → conversation A → Codex thread A
用户 B → conversation B → Codex thread B
用户 C → conversation C → Codex thread C
```

“单 Agent”表示只有一种 Agent 能力定义，不表示只能有一个用户或一个 Thread。

当前扩容原则：

```text
第一阶段：单实例生产化
→ 一个 Agent Service 实例
→ 多 Conversation / 多 Thread
→ PostgreSQL
→ 持久化 CODEX_HOME
→ 连接池 / 并发限制 / 超时 / OTel

第二阶段：流量明显增长后
→ API 层与 Codex Runtime Worker 分离
→ 多 Runtime Worker
→ conversation 路由到可恢复的 Thread 状态
→ 独立持久存储
→ 负载均衡 / 队列 / 背压

第三阶段：只有真正出现多个 Agent / 多团队后
→ 再考虑 Agent Registry / Gateway / Control Plane
```

也就是说：

> **高并发是部署和运行时扩容问题，不应该因为用户多就立刻把单 Agent 改造成多 Agent 平台。**

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

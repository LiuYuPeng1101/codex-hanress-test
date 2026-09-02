# Codex Enterprise Agent Runtime Reference Architecture

这个仓库是一个以 Codex Harness 为执行内核的企业 Agent Runtime 参考架构。

它不是通用 Agent 平台成品，也不是订单 Agent 产品。当前订单场景用于验证企业 Agent 的核心运行链路，通用 Runtime 能力与具体业务能力严格分层。

## 模块

### `codex-agent-python/`

生产主路径中的 Agent Runtime / Agent Service：

```text
FastAPI
→ official openai-codex Python SDK
→ Codex Harness
→ Skill / MCP / Approval / Sandbox / Event / Context / Compaction
```

同时负责：

```text
SSE Streaming
OpenTelemetry
PostgreSQL Approval Persistence
Thread Read / Compact API
```

完整说明：`codex-agent-python/README.md`

### `hanress-test/`

目录名保留历史名称，但模块职责已经收敛为 **Order MCP Adapter**：

```text
MCP Tool
→ OrderService
→ OrderGateway
→ 真实订单系统
```

Java 模块不再运行 Codex、不再模拟审批、不再维护内存订单数据。

完整说明：`hanress-test/README.md`

## 当前定位

```text
Codex Harness
= 通用 Agent 执行内核

codex-agent-python
= 企业 Runtime 参考实现

order Skill + order MCP
= 一个具体业务 Agent Definition

未来 Agent Gateway
= 真正的平台控制面
```

下一阶段重点：

```text
Business Conversation ID
Trusted User / Tenant Context
Runtime Routing
多实例 Thread Persistence / Resume
Agent Registry / Gateway
```

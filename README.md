# Codex Enterprise Agent Runtime Reference Architecture

这个仓库以 **Codex Harness** 为执行内核，构建企业 Agent Runtime 的生产级架构基线。

当前不是“万能 Agent 平台成品”，而是已经把企业 Runtime 最关键的边界落进代码：Business Conversation、可信身份、MCP 业务能力、Human Approval、多租户、Sandbox、Event、Context/Compaction、Runtime 持久化与实例路由。

## 模块职责

```text
Enterprise Gateway
       │
       │ trusted user / tenant / roles
       ▼
codex-agent-python
Enterprise Agent Runtime
       │
       │ AgentDefinition → Codex
       ▼
Codex Harness
       │
       │ MCP + trusted headers
       ▼
hanress-test
Order MCP Adapter
       │
       ▼
Real OMS / Business System
```

### `codex-agent-python/`

生产主路径 Runtime，负责：

```text
AgentDefinition
Business conversation_id
Conversation → Codex thread mapping
Trusted Gateway identity
Runtime instance ownership / sticky routing
Codex Thread / Turn / Resume
MCP Tool allow-list / Approval Policy
Identity → MCP HTTP Headers
PostgreSQL Approval Center
Sandbox
Event Mapper / SSE
OpenTelemetry
Context / Compaction
CODEX_HOME persistent storage
```

完整架构问答与真实售后案例见：`codex-agent-python/README.md`。

### `hanress-test/`

目录名为历史名称，当前职责已经严格收敛为 **Order MCP Adapter**：

```text
MCP service authentication
→ Trusted BusinessIdentity
→ OrderMcpTools
→ OrderService
→ OrderGateway
→ HttpOrderGateway
→ Real OMS
```

Java 不运行 Codex、不保存 Agent Thread、不做模拟审批、不维护虚假订单。

完整说明见：`hanress-test/README.md`。

## 当前定位

```text
Codex Harness
= Agent execution engine

codex-agent-python
= enterprise runtime boundary / reference implementation

AgentDefinition
= 某个具体 Agent 的 workspace + sandbox + MCP + tool policy

Java MCP Adapter
= governed bridge to the system of record
```

当前已经形成 Agent Gateway 的早期控制面能力，但独立 Gateway / Registry / Router 仍是下一阶段工程。

## 生产原则

```text
不伪造业务数据
不把内存当审批事实源
不让模型声明身份
不暴露 Codex thread_id 作为业务主键
不让 Approval 绕过业务授权
不直接透传 Codex Raw Event
不在 Java/Python 运行两套 Codex Runtime
不依赖容器临时磁盘保存 Thread
```

CI：`.github/workflows/ci.yml` 会验证 Python + PostgreSQL Runtime 路径和 Java MCP Adapter 构建测试。

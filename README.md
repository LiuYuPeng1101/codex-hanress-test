# Enterprise Agent Runtime with Codex Harness

这个仓库实现一套生产导向的企业 Agent Runtime Kernel，并使用 **Order Agent** 作为第一套 Agent Definition。

```text
codex-agent-python/
→ Agent Runtime Service
→ Agent Definition / Conversation / Approval / Event / OTel
→ CodexRuntime Adapter
→ OpenAI Codex Harness

hanress-test/
→ Order MCP Adapter
→ 把受治理的 MCP Tool 转换成真实订单后端调用
```

整体架构：

```text
Business Client
      ↓
Agent Runtime Service
      ↓
Codex Harness
      ↓ MCP
Order MCP Adapter
      ↓
Real Order Backend
```

`codex-agent-python` 不重新实现 Agent Loop，而是把 Codex Harness 的 Thread、Skill、MCP、Approval、Sandbox、Event、Context 和 Compaction 转成稳定的企业 Runtime 契约。

`hanress-test` 已不再启动 Codex，也不保存固定订单或内存业务状态；它只承担 Business MCP Adapter 职责。

详细架构、Codex 内部机制映射、真实订单执行链和生产边界见：

- `codex-agent-python/README.md`
- `hanress-test/README.md`

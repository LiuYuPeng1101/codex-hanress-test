# Order MCP Adapter

这是订单业务系统面向企业 Agent Runtime 的 MCP Adapter。它不是 Agent Runtime，也不启动 Codex。

职责边界：

```text
Codex Agent Runtime
        ↓ MCP
Order MCP Adapter
        ↓
OrderApplicationService
        ↓
OrderBackendClient
        ↓ HTTP
Real Order Backend
```

## 为什么单独做 MCP Adapter

Agent 不应该直接连接数据库，也不应该把业务系统里的所有 Service/CRUD 暴露给模型。MCP Adapter 只暴露经过治理的、语义明确的业务能力，并把请求转给真实业务系统。

当前 Tool：

```text
get_order_status(orderId)
→ 只读查询

cancel_order(orderId)
→ 修改真实订单状态
→ Agent Runtime 侧要求 Human Approval
→ 真实 Order Backend 仍必须执行最终 RBAC / ABAC / tenant / order-state 校验
```

因此：

```text
Codex Approval
≠ Business Authorization
```

Approval 控制 Agent 是否获准尝试这次 Tool Call；真正的业务系统仍是最终授权边界。

## 生产结构

```text
src/main/java/com/example/hanresstest/
├── config/
│   ├── McpToolConfig.java
│   └── OrderBackendProperties.java
├── integration/
│   └── OrderBackendClient.java
├── mcp/
│   └── OrderMcpTools.java
└── service/
    └── OrderApplicationService.java
```

`OrderMcpTools` 是 Agent Adapter 层，`OrderApplicationService` 是应用服务，`OrderBackendClient` 是对真实订单后端的集成端口。

## 配置

必须配置真实订单后端：

```bash
export ORDER_BACKEND_BASE_URL=https://order.internal.example.com
```

MCP Endpoint：

```text
POST /mcp
```

默认 Spring AI Streamable HTTP MCP Server 名称：

```text
order-mcp-server
```

## 上游订单 API 契约

当前 Adapter 依赖：

```http
GET /api/orders/{orderId}
POST /api/orders/{orderId}/cancel
```

实际企业接入时，如果原有订单系统接口不同，只替换 `OrderBackendClient`，不需要修改 Codex Runtime 或 MCP Tool 的平台契约。

## 身份与授权

生产环境不能让模型把 `userId` / `tenantId` 当普通 Tool 参数传入，因为这些字段是模型可控输入，不能作为可信身份。

正确架构应由 Agent Gateway / Runtime 通过受信任的调用上下文把 actor、tenant、service identity 传给 MCP/业务系统，业务系统再做最终权限校验。本模块当前已经移除所有固定订单和内存状态，但完整的 per-conversation actor propagation 会在 Agent Gateway 层实现。

# Order MCP Adapter

这个模块是企业订单系统的 **Spring Boot MCP Adapter**。

它不运行 Codex，不维护 Agent Thread，不保存审批状态，也不拥有订单业务数据。

职责只有一个：

> 把现有订单系统中的受治理业务能力，以语义明确的 MCP Tool 暴露给 Agent Runtime。

## 架构

```text
Codex Harness
    │
    │ MCP
    ▼
OrderMcpTools
    │
    ▼
OrderService
    │
    ▼
OrderGateway
    │
    ▼
HttpOrderGateway
    │
    ▼
真实订单系统 / OMS
```

## 为什么这样拆

`OrderMcpTools` 是 Agent 协议适配层，只负责：

```text
Tool 名称
Tool 描述
Tool 参数 Schema
```

`OrderService` 是应用服务，不依赖 Codex / MCP。

`OrderGateway` 是业务系统访问端口。

`HttpOrderGateway` 是当前 HTTP 基础设施实现。未来如果订单系统使用 RPC、Dubbo、gRPC、SDK 或其他协议，只替换 Gateway 实现，不修改 Agent Tool 定义。

## 当前 Tool

```text
get_order_status(orderId)
cancel_order(orderId)
```

`cancel_order` 是否需要 Human Approval 由上游 Codex Runtime 的 Tool Policy 管理；Java 业务系统仍然必须执行最终授权和业务规则校验。

## 真实业务依赖

部署时必须配置：

```text
ORDER_SERVICE_BASE_URL
ORDER_SERVICE_TOKEN
```

默认契约路径：

```text
GET  /api/orders/{orderId}/status
POST /api/orders/{orderId}/cancel
```

可以通过：

```text
ORDER_STATUS_PATH
ORDER_CANCEL_PATH
```

覆盖。

模块中不包含内存订单、固定订单 ID 或虚假业务结果。上游订单系统不可用时调用应明确失败，由调用方和 Observability 系统处理。

## 身份与授权边界

不要让模型通过 Tool 参数声明：

```text
userId
tenantId
roles
```

这些身份信息必须来自可信 Gateway / Authentication Context，并由业务系统验证。

当前模块使用服务间 `ORDER_SERVICE_TOKEN` 连接订单系统；用户/租户级可信上下文会在 Agent Gateway / Identity Context 阶段继续接入。

## 启动

```bash
export ORDER_SERVICE_BASE_URL=https://oms.internal.example
export ORDER_SERVICE_TOKEN=***

mvn spring-boot:run
```

MCP Endpoint：

```text
/mcp
```

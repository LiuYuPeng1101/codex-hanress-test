# Order MCP Adapter

这个模块是企业订单系统的 **Spring Boot MCP Adapter**。它不是 Agent Runtime，也不拥有订单事实。

生产职责：

```text
Codex Runtime
  │
  │ Authorization: MCP service credential
  │ X-User-Id / X-Tenant-Id / X-Roles
  ▼
McpServiceAuthenticationFilter
  ↓
TrustedMcpRequestContext
  ↓
BusinessIdentity
  ↓
OrderMcpTools
  ↓
OrderService
  ↓
OrderGateway
  ↓
HttpOrderGateway
  ↓
真实 OMS / System of Record
```

## 为什么 Java 只保留 MCP Adapter？

Codex Runtime 已统一放在 Python。如果 Java 再启动一份 Codex，会形成两套 Thread、Approval、Event 和 Context 生命周期，因此生产主路径已经删除 Java Codex Runtime。

Java 应负责它最擅长的事情：**把已有企业业务能力以受治理的 MCP Tool 暴露出去。**

## 为什么 Tool 只有 orderId，没有 userId / tenantId？

当前 Tool：

```text
get_order_status(orderId)
cancel_order(orderId)
```

身份不能设计成模型参数：

```text
cancel_order(orderId, userId, tenantId, role)  # 错误
```

因为模型输出不是身份凭证。

可信身份来自上游 Runtime 的控制面 Header。MCP Adapter 先通过 `McpServiceAuthenticationFilter` 验证 Runtime 的服务凭据，只有验证成功后才由 `TrustedMcpRequestContext` 读取：

```text
X-User-Id
X-Tenant-Id
X-Roles
```

并构造 `BusinessIdentity`。

## 为什么身份还要继续传给 OMS？

Codex Approval 只代表“允许 Agent 尝试这次 Tool Call”。最终业务操作仍必须由真实订单系统判断：

```text
当前用户是否有权限？
订单是否属于当前 tenant？
用户是否能访问这个订单？
当前订单状态是否允许取消？
金额或风控规则是否允许？
```

因此 `HttpOrderGateway` 同时传递：

```text
ORDER_SERVICE_TOKEN       # MCP Adapter → OMS 服务认证
X-User-Id                 # 当前业务用户
X-Tenant-Id               # 当前企业租户
X-Roles                   # 当前实时角色
```

真正的 RBAC / ABAC / Tenant / Resource Ownership 必须由 OMS 再执行一次。

## 为什么要拆 OrderMcpTools / OrderService / OrderGateway？

```text
OrderMcpTools
= Agent 协议适配，只定义模型可见业务能力

OrderService
= 应用用例，不依赖 Codex / MCP

OrderGateway
= 访问订单系统的端口

HttpOrderGateway
= 当前 HTTP 基础设施实现
```

如果企业订单系统以后从 REST 换成 Dubbo / gRPC / SDK，只替换 Gateway 实现，不改变 Agent Tool 语义。

## 生产依赖

必须配置：

```text
MCP_SERVICE_TOKEN
ORDER_SERVICE_BASE_URL
ORDER_SERVICE_TOKEN
```

可覆盖：

```text
ORDER_STATUS_PATH
ORDER_CANCEL_PATH
```

服务不会使用固定订单、内存状态或测试结果兜底。依赖不可用时明确失败。

## 启动示意

```bash
export MCP_SERVICE_TOKEN='replace-with-strong-runtime-service-secret'
export ORDER_SERVICE_BASE_URL='https://oms.internal.example'
export ORDER_SERVICE_TOKEN='replace-with-order-service-credential'

./mvnw spring-boot:run
```

MCP Endpoint：

```text
/mcp
```

生产部署还应在网络层叠加 mTLS / Service Mesh / NetworkPolicy，并由 Secret Manager 管理和轮换服务凭据。

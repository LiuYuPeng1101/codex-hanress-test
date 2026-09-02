# Python Codex 人工审批实验

这一阶段演示：查询类 MCP Tool 自动执行，写操作 MCP Tool 必须等待人工审批。

## 当前策略

```text
get_order_status
→ approval_mode = approve
→ 自动执行

cancel_order
→ approval_mode = prompt
→ 产生 MCP Tool Approval
→ 等待人工 approve / reject
```

## 执行链

```text
用户：取消订单1001
        ↓
Codex Harness
        ↓
cancel_order
        ↓
approval_mode=prompt
        ↓
mcpServer/elicitation/request
        ↓
ApprovalService
        ↓
ApprovalStore 创建 PENDING
        ↓
原 Turn 等待
```

此时另一个 HTTP 请求仍可访问：

```http
GET /api/v1/approvals
```

找到 `status=PENDING` 的审批 ID 后，可以批准：

```http
POST /api/v1/approvals/{approval_id}/approve
```

或者拒绝：

```http
POST /api/v1/approvals/{approval_id}/reject
```

批准后：

```text
ApprovalStore
→ 唤醒 approval handler
→ {action: accept, content: {}}
→ Codex Harness
→ 真正调用 Java MCP cancel_order
→ Turn 继续完成
```

拒绝后：

```text
ApprovalStore
→ {action: decline, content: null}
→ cancel_order 不执行
→ Agent 根据拒绝结果继续生成回答
```

## 为什么当前使用内存 Store

这是学习版本，重点是理解 Human-in-the-loop 的运行机制。

生产环境应该把 ApprovalStore 替换为数据库/Redis，并增加：

- userId / tenantId
- agentId / conversationId / threadId / turnId
- toolName / toolArguments
- 风险等级
- 审批人
- 审批理由
- 超时
- 审计日志
- 多实例消息通知

## 重要安全边界

Codex Approval 不是业务授权。

即使 Agent Approval 已批准，Java 业务系统仍然必须独立校验：

- 当前用户身份
- RBAC / ABAC
- tenant
- 是否拥有该订单
- 当前订单状态是否允许取消
- 金额/风险阈值

最终推荐链路：

```text
Agent
→ Codex Permission / Approval
→ MCP
→ Java Business Authorization
→ Business Service
```

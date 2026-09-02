# Codex MCP Tool Approval

当前策略：

```text
get_order_status
→ approval_mode=approve
→ 自动执行

cancel_order
→ approval_mode=prompt
→ Human-in-the-loop
```

## Codex 侧执行链

```text
Codex Harness
 ↓
cancel_order
 ↓
approval_mode=prompt
 ↓
mcpServer/elicitation/request
 ↓
meta.codex_approval_kind=mcp_tool_call
 ↓
ApprovalService
 ↓
PostgreSQL approval_requests
 ↓
PENDING
 ↓
人工 approve / reject
 ↓
accept / decline
 ↓
Codex 决定是否真正调用 MCP Tool
```

批准：

```http
POST /api/v1/approvals/{approval_id}/approve
```

拒绝：

```http
POST /api/v1/approvals/{approval_id}/reject
```

## 持久化原则

审批记录使用 PostgreSQL 作为事实来源，不使用进程内 Map / Event 保存业务状态。

数据库迁移：

```text
migrations/001_create_approval_requests.sql
```

决策更新必须满足：

```text
WHERE status = PENDING
```

避免多个实例或重复请求覆盖已经完成的审批。

超过 `APPROVAL_TIMEOUT_SECONDS` 仍未得到决策时，审批转为 `EXPIRED` 并向 Codex 返回 `decline`。

## 多实例边界

数据库持久化可以让多个 Agent Service 实例共享审批记录，但不能单独解决“活跃 Turn 所属 Runtime 实例死亡”的问题。

活跃 Codex Turn 仍然属于运行它的 Runtime / App Server 进程。生产集群还需要：

```text
runtime_instance_id
Thread ownership / lease
Runtime routing
失败实例检测
可恢复 Run 状态
```

这些属于后续 Agent Gateway / 多实例 Runtime 控制面。

## Approval 不是业务授权

即使 Codex Approval 已经通过，真实业务系统仍然必须校验：

```text
认证用户
Tenant
RBAC / ABAC
订单归属
订单状态
金额 / 风险阈值
业务规则
```

推荐链路：

```text
Agent Policy / Approval
 ↓
MCP
 ↓
Trusted Identity Context
 ↓
Business Authorization
 ↓
Business Service
```

# Human-in-the-loop Approval

Order Agent 的写操作使用 Codex MCP Tool Approval，审批状态持久化在 Redis，不依赖单个 Agent Service 进程内存。

```text
get_order_status → approval_mode=approve
cancel_order     → approval_mode=prompt
```

执行链：

```text
Codex Harness 准备调用 cancel_order
        ↓
mcpServer/elicitation/request
        ↓
ApprovalService
        ↓
Redis Approval Repository
        ↓
PENDING
        ↓
人工 approve / reject
        ↓
accept / decline
        ↓
Codex 继续或终止 Tool Call
```

API：

```http
GET  /api/v1/approvals
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

生产部署必须把这些接口放在真实认证授权网关之后，并记录审批人、actor、tenant、风险等级、理由和审计日志。当前 Repository 解决的是审批状态持久化与多实例共享，不替代企业 IAM。

最重要的安全边界：

```text
Codex Approval
≠
Business Authorization
```

即使 Agent Approval 已通过，真实业务后端仍必须校验可信 actor、tenant、RBAC/ABAC、资源归属和业务状态。

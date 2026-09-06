# 业务审批与执行授权

业务写操作的最终审批检查位于 MCP Adapter 的应用服务。SDK elicitation 的描述文本不能可靠标识工具；当前 callback 拒绝此类请求，也拒绝本地命令/文件变更提权。历史 SDK 审批不升级为新授权。

`get_order_status` 和 `cancel_order` 的 Codex 工具策略均为 `approve`，表示允许调用 Adapter。`cancel_order` 在 Adapter 内仍必须取得人工批准的执行 ID，才能向 OMS 发请求。此检查不依赖模型是否遵守提示词。

1. Runtime 将可信用户、租户、角色与 `X-Conversation-Id` 注入 MCP HTTP Header；模型只提供 `orderId`。
2. Adapter 使用独立内部密钥调用执行授权接口。服务校验会话归属，使用注册操作 `order.cancel` 及严格验证的参数生成指纹。
3. PostgreSQL 创建 `PENDING` 记录及固定执行 ID。返回 `PENDING` 和 `approval_id`，不返回执行 ID；Adapter 不访问 OMS。
4. 有 `agent.approver` 角色的业务用户调用现有 approve/reject API，只能处理所属租户、未过期的待审批记录。
5. 批准后再次请求同一会话的相同动作。事务锁定记录，将 `APPROVED` 变为 `CONSUMED`，签发固定执行 ID。后续重试在有效期内返回同一 ID。
6. Adapter 将该 ID 作为 `Idempotency-Key` 传给 OMS。OMS 独立验证业务权限、订单状态并执行原子去重。

| 状态 | 执行授权 API | 能否调用 OMS |
|---|---|---|
| PENDING | PENDING，无执行 ID | 否 |
| APPROVED | 原子签发，返回 AUTHORIZED | 是，使用固定 ID |
| CONSUMED | AUTHORIZED，重放固定 ID | 是，OMS 必须去重 |
| REJECTED | REJECTED，无执行 ID | 否 |
| 任意已过期记录 | EXPIRED，无执行 ID | 否 |

`CONSUMED` **只表示执行 ID 已签发，不表示订单已取消**。终态记录保留在唯一约束内；拒绝、过期、网络超时、进程重启都不会自动生成新 ID。过期是按 `expires_at` 计算的授权结果，不依赖定时任务修改数据库 status；审批页面应展示 expiry 字段。

默认授权期限从申请创建起 24 小时，配置为 `EXECUTION_GRANT_TTL_SECONDS`。数据库时间决定签发和审批的有效性；Adapter 还会拒绝已过期的授权响应，主机应保持时钟同步。超时后先查询 OMS，禁止把新会话当作绕过去重的重试方式。

审批页面使用以下既有接口，Authorization 为公开 API 服务密钥并携带可信业务身份及 `agent.approver` 角色：

- `GET /api/v1/approvals`
- `POST /api/v1/approvals/{approval_id}/approve`
- `POST /api/v1/approvals/{approval_id}/reject`

页面响应增加结构化 `operation`、`operation_arguments`、`expires_at`，不暴露执行 ID 或原始 SDK params。人工批准不会自动启动 Turn；业务客户端按现有会话继续请求。

完整接口、升级次序、复用及 OMS 验收要求见 [执行幂等契约](EXECUTION_CONTRACT.md)。数据库的并发安全不改变 [单 Runtime 部署边界](RELIABILITY.md)。

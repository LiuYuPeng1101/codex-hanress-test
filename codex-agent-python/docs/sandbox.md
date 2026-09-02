# Runtime Sandbox Policy

Order Agent 显式使用：

```python
Sandbox.read_only
```

这是最小权限策略：Agent 可以读取 workspace 中的 Skill 和必要文件，但不能修改本地文件。真实业务写操作必须通过受治理的 MCP Tool，而不是通过本地执行环境绕过业务边界。

```text
Local filesystem
→ Codex Sandbox

Business mutation
→ MCP Tool
→ Approval
→ Business Authorization
→ Real Business System
```

## 与 Approval 的区别

```text
Approval
= 某一次高风险动作是否获准继续

Sandbox
= Runtime 实际执行环境允许访问到哪里
```

二者是叠加控制。

Order Agent 当前策略：

```text
Skill: order-analysis
Sandbox: read_only
get_order_status: approve
cancel_order: prompt
```

Codex Thread 创建和每个 Turn 都显式设置 read-only，避免部署机器默认配置或历史 Thread 状态意外扩大权限。

官方预设：

```text
Sandbox.read_only
→ 可读，不可写

Sandbox.workspace_write
→ 可读写 workspace / configured writable roots

Sandbox.full_access
→ 对应 danger-full-access
```

生产 Agent 应选择完成业务所需的最低权限。Coding Agent 可能需要 `workspace_write`，订单/财务分析 Agent 通常应使用 `read_only`。

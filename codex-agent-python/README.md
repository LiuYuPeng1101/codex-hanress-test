# Codex Enterprise Agent Runtime Reference Architecture

这个模块的定位不是“教你 MCP 是什么”，也不是一个已经封装完所有企业能力的通用 Agent 平台。

它更准确地是：

> **基于 Codex Harness 的企业 Agent Runtime 生产级架构基线与参考实现。**

Codex 已经提供 Thread、Turn、Skill Discovery、MCP、Approval、Sandbox、Event、Context、Compaction、Resume 等 Agent Harness 能力。我们不重新实现这些能力；Runtime 层解决的是：**如何把这些 Codex 原生能力放进企业真实的身份、租户、业务系统、审批、运行路由和可观测性边界中。**

当前 `order-agent` 是第一份 Agent Definition，用来验证这套 Runtime。以后合同、财务、运维 Agent 应复用 Runtime，而不是复制 Runtime 代码。

---

# 1. 截止目前，这个项目到底算什么？

答案：**它已经超过“订单 Agent 示例”，但还不是完整 Agent Gateway 平台。**

当前系统分三层：

```text
企业 Gateway / Control Plane               ← 目前实现了一部分
        │
        │ conversation_id / trusted identity
        ▼
codex-agent-python
Enterprise Agent Runtime                   ← 当前项目核心
        │
        │ AgentDefinition → Codex config
        ▼
Codex Harness                              ← OpenAI 提供
        │
        ├── Thread / Turn
        ├── Skill Discovery
        ├── MCP
        ├── Approval Protocol
        ├── Sandbox
        ├── Event
        └── Context / Compaction
        │
        ▼
Java Order MCP Adapter
        │
        ▼
真实 OMS / Business System
```

因此现在最准确的名字是：

```text
Codex Enterprise Agent Runtime Reference Architecture
```

真正完整的“通用 Agent 底座”还应继续具备独立 Gateway、Agent Registry、集中式 Runtime Router、统一 Policy、配额、Secret Rotation、完整 Evals 等能力。

---

# 2. Codex 已经有这些能力，为什么我们还要开发 Runtime？

因为 **Harness 解决 Agent 怎么执行，企业 Runtime 解决这次执行属于谁、允许接什么、出了问题怎么治理。**

例如 Codex 能恢复：

```text
thread_id = 019xxx
```

但企业真正面对的问题是：

```text
这个 Thread 属于哪个公司？
属于哪个用户？
属于哪个 Agent？
应该落到哪台 Runtime 实例？
当前用户还有没有权限继续它？
这个 Thread 发出的 cancel_order 应该由哪个租户审批？
```

这些不是模型推理问题，也不是 Codex Harness 应替企业决定的问题。

所以 Runtime 层主要负责：

```text
1. AgentDefinition → Codex Runtime 配置
2. business conversation_id → Codex thread_id 映射
3. Trusted Gateway Identity
4. Tenant / User ownership
5. MCP 服务绑定与 Tool allow-list
6. Trusted Identity → MCP HTTP Header
7. Human Approval → 企业审批持久化
8. Sandbox 策略落地
9. Codex Raw Event → 稳定 AgentEvent
10. SSE 与 OpenTelemetry
11. Context / Compaction 管理入口
12. Runtime Instance Ownership / Sticky Routing
13. Codex Thread 持久化目录管理
```

换句话说：

```text
Codex Harness = execution engine
Runtime Layer  = enterprise execution boundary
Gateway        = enterprise control plane / routing entry
```

---

# 3. 一个真实售后 Agent 为什么需要这些层？

假设一家电商公司已经有 OMS、WMS、物流、退款系统和客服后台。

客服员工 `employee-88` 属于 `tenant-A`，输入：

> “订单 A20260903001 一直没到，查一下；如果符合条件就取消。”

完整生产链应该是：

```text
客服后台
  ↓
Enterprise Gateway
  │  已完成 SSO / 用户认证
  │  user=employee-88
  │  tenant=tenant-A
  │  roles=support.agent,order.read
  ↓
Agent Service
  │  验证 Gateway service credential
  ↓
conversation_id = conv-xxx
  │
  ├─ PostgreSQL 保存：
  │    tenant-A / employee-88 / order-agent
  │    runtime_instance=runtime-01
  │    runtime_thread_id=Codex thread id
  │
  ▼
Codex Runtime
  │
  ├─ cwd → 发现 order-analysis Skill
  ├─ Sandbox = read_only
  ├─ MCP Tool allow-list
  └─ Trusted identity 注入 MCP HTTP Headers
  ↓
Codex Harness
  ↓
Skill 要求先查询真实业务数据
  ↓
get_order_status
  ↓
Java Order MCP Adapter
  │  验证 Runtime service token
  │  从可信 Header 读取 user / tenant / roles
  ↓
OrderService → OrderGateway
  ↓
真实 OMS
  │  再做订单归属、Tenant、RBAC/ABAC、订单状态校验
  ↓
返回真实状态
```

如果 Codex 随后决定调用：

```text
cancel_order
```

链路继续：

```text
Codex MCP Policy: prompt
  ↓
mcpServer/elicitation/request
  ↓
ApprovalService
  ↓
根据 runtime_thread_id 找到 business conversation
  ↓
写入 PostgreSQL approval_requests
  │  conversation_id
  │  tenant_id
  │  requester_user_id
  │  runtime thread / turn
  │  MCP server
  ↓
PENDING
  ↓
具有 agent.approver 角色的主管审批
  ↓
approve → accept
  ↓
Codex 才真正执行 cancel_order
  ↓
Java MCP Adapter
  ↓
真实 OMS 再执行最终 Business Authorization
```

这里没有任何一层可以被“Prompt 写得更严谨”替代。

---

# 4. 为什么外部 API 不能直接暴露 Codex thread_id？

因为 `thread_id` 是 Runtime 私有标识，不是企业业务标识。

错误设计：

```text
Frontend
  ↓
/threads/<codex-thread-id>
```

问题是未来如果 Runtime 从 Codex 切换到其他实现，整个业务 API 都跟着 Runtime 变化；更严重的是，只拿到 thread_id 无法表达 tenant、owner 和 Runtime instance。

当前代码改成：

```text
POST /api/v1/agents/conversations
      ↓
conversation_id
```

PostgreSQL：

```text
conversations
├── id                  # 企业 conversation_id
├── agent_id
├── tenant_id
├── user_id
├── runtime_type        # codex
├── runtime_thread_id   # Codex 私有 Thread ID
├── runtime_instance_id
└── created_at
```

代码位置：

```text
app/conversations/conversation_repository.py
app/services/agent_service.py
```

`AgentService` 每次先根据：

```text
conversation_id + tenant_id + user_id
```

找回内部 `runtime_thread_id`，然后才允许调用 `CodexRuntime`。

这一步的意义是：**业务 Conversation 与具体 Agent Runtime 解耦。**

---

# 5. 为什么 Runtime 里不能写死 order MCP？

因为如果 `CodexRuntime` 内部出现：

```text
order
get_order_status
cancel_order
```

它就不是 Runtime，而是 Order Agent 实现。

现在增加：

```text
app/agents/definition.py
```

结构：

```text
AgentDefinition
├── agent_id
├── workspace
├── sandbox
└── mcp_servers
      ├── url
      ├── service_token
      ├── enabled_tools
      └── tool_approval_modes
```

当前订单 Agent 只是一个配置实例：

```text
order-agent
├── sandbox = READ_ONLY
└── MCP order
     ├── get_order_status → approve
     └── cancel_order     → prompt
```

`CodexRuntime` 做的是：

```text
AgentDefinition
      ↓ translate
CodexConfig / ThreadStartParams
      ↓
Codex Harness
```

以后合同 Agent 可以换成：

```text
contract-agent
├── contract-review Skill
├── read_contract
├── search_policy
└── submit_contract → prompt
```

而 `CodexRuntime` 不需要改。

这才是 Runtime 可复用的意义。

---

# 6. 为什么 userId / tenantId 绝不能让模型作为 Tool 参数生成？

错误 Tool：

```text
cancel_order(orderId, userId, tenantId, role)
```

因为模型可以输出任意字符串。模型输出不是身份凭证。

当前生产链将身份放在控制面：

```text
Gateway
  ↓ 验证服务凭据后
X-User-Id
X-Tenant-Id
X-Roles
  ↓
Agent Service GatewayPrincipal
  ↓
Codex ThreadStart / ThreadResume config
  ↓
mcp_servers.<name>.http_headers
  ↓
MCP HTTP Request
```

代码位置：

```text
app/security/gateway_auth.py
app/runtime/codex_runtime.py::_mcp_identity_config()
```

Codex 0.147 的 Thread Start / Resume 支持 `config` override；MCP HTTP transport 支持 `http_headers`。因此身份可以走 Runtime 配置，而不是进入模型数据平面。

Java 再从已通过 MCP 服务认证的请求读取：

```text
X-User-Id
X-Tenant-Id
X-Roles
```

代码位置：

```text
TrustedMcpRequestContext
BusinessIdentity
OrderMcpTools
OrderService
HttpOrderGateway
```

最终真实 OMS 收到：

```text
service credential
+
trusted business identity
```

由 OMS 做最终授权。

---

# 7. 为什么 Approval 已经通过，Java 还必须再授权？

因为两者回答的是不同问题。

真实例子：客服主管批准了 Agent “尝试取消订单”，但订单此时可能已经完成出库，或者这个员工根本没有权限操作该客户的订单。

所以：

```text
Codex Approval
= 允许 Agent 尝试这次高风险 Tool Call

Business Authorization
= 真实业务系统是否允许当前主体真正改变业务状态
```

生产链必须是：

```text
Codex Tool Policy
  ↓
Human Approval
  ↓
MCP
  ↓
Business Authorization
  ↓
Business Mutation
```

绝不能设计成：

```text
Approval approve
→ 绕过 OMS 权限
```

---

# 8. Codex Approval 在企业里为什么还需要我们写 ApprovalService？

Codex 已经知道某个 Tool 应该 `prompt`，也会向 Client 发出 MCP Approval Server Request。

但 Codex 不知道：

```text
审批记录放哪？
属于哪个 tenant？
谁有资格审批？
谁点了批准？
审批超时怎么办？
多实例怎么看到同一审批？
```

因此 Runtime 做桥接：

```text
Codex mcpServer/elicitation/request
  ↓
ApprovalService
  ↓
runtime_thread_id → ConversationRepository
  ↓
确定 conversation / tenant / requester
  ↓
ApprovalRepository → PostgreSQL
```

`approval_requests` 保存：

```text
conversation_id
requester_user_id
tenant_id
runtime thread / turn
server_name
params JSONB
status
decision
decided_by
created_at / decided_at
```

审批 API 必须：

```text
Gateway authentication
+
role = agent.approver
+
tenant isolation
```

未知 Runtime Thread 发起的 Approval 直接 `decline`，这是 fail-closed。

当前等待机制使用 PostgreSQL 轮询，是为了兼容 Codex 当前同步 approval handler；数据库是事实来源。高吞吐版本可把唤醒机制替换成 LISTEN/NOTIFY、Redis Pub/Sub 或消息队列。

---

# 9. 为什么 Java 现在只做 MCP Adapter，而不再启动 Codex？

以前 Java 和 Python 都有 Codex Runtime，是为了学习 App Server 协议。

生产主路径如果继续这样：

```text
Python Codex Runtime
+
Java Codex Runtime
```

会出现两套 Thread、两套 Approval、两套 Event 生命周期，职责完全混乱。

现在 Java 收敛成：

```text
OrderMcpTools
  ↓
OrderService
  ↓
OrderGateway
  ↓
HttpOrderGateway
  ↓
真实订单系统
```

并且删除：

```text
Java CodexAppServerClient
Java CodexAgentRuntime
Java 模拟 Approval
Java 假订单状态
Java 重复 Skill
Java 重复 Prompt / Resource
```

生产职责变成：

```text
Python = Agent Runtime
Java   = Business MCP Adapter
OMS    = System of Record
```

---

# 10. 为什么 Java MCP Adapter 还要自己验证 Runtime？

因为不能仅凭：

```text
X-User-Id: admin
```

就相信调用方。

当前链路：

```text
Codex Runtime
  ↓
Authorization: Bearer <MCP service token>
X-User-Id
X-Tenant-Id
X-Roles
  ↓
McpServiceAuthenticationFilter
  ↓ 验证 service token
TrustedMcpRequestContext
  ↓
BusinessIdentity
```

只有服务认证成功之后，Java 才把这些身份 Header 当成可信控制上下文。

然后 `HttpOrderGateway` 把：

```text
service credential
+
BusinessIdentity
```

继续传给真实 OMS。

因此真正的信任链是连续的，不是“Python 认证完了，Java 就裸奔”。

---

# 11. 为什么 Sandbox.read_only 仍然可以 cancel_order？

因为 Sandbox 限制的是 Codex Runtime 本地执行环境，而 `cancel_order` 是远程受治理业务能力。

当前订单 Agent：

```text
本地 workspace
├── read       ✅
└── write      ❌

MCP
├── get_order_status ✅
└── cancel_order     ✅，但必须 Approval + Business Authorization
```

所以：

```text
Sandbox
≠ Tool Permission
≠ Approval
≠ Business Authorization
```

Runtime 从 `AgentDefinition.sandbox` 翻译到 Codex Sandbox，订单 Agent 当前是 `READ_ONLY`。

---

# 12. 为什么 Event 不能原样透传 Codex Notification？

因为 Runtime 升级会改变内部协议，而且 Raw Notification 可能携带：

```text
reasoning
Tool arguments
Tool result
内部 Runtime IDs
敏感业务数据
```

所以当前设计：

```text
Codex Notification
  ↓
CodexEventMapper
  ↓
AgentEvent
  ↓
SSE
```

外部 AgentEvent 只包含：

```text
conversation_id
event type
允许暴露的 data
created_at
```

**不再暴露 Codex thread_id / turn_id。**

内部 Runtime IDs 仍进入 OpenTelemetry，方便受控排障：

```text
agent.conversation.id
agent.runtime.thread.id
agent.runtime.turn.id
```

因此产品 API 稳定，运维 Trace 又保留足够信息。

---

# 13. 为什么 Context / Compaction 不由我们自己维护 messages 数组？

因为这是 Codex Harness 已经实现的 Runtime 能力。

企业 Runtime 应该区分：

```text
Business Conversation
= 企业控制面会话

Codex Thread History
= Runtime 持久化执行历史

Effective Context
= 当前模型真正使用的工作上下文
```

当历史增长时，Codex 自己负责 Context Window 和自动 Compaction；SDK 也提供：

```text
thread.compact()
```

本项目只提供受控运维入口：

```text
POST /api/v1/agents/conversations/{conversation_id}/compact
```

而且该接口要求：

```text
role = agent.operator
```

原因是手工 Compaction 属于 Runtime 运维动作，不应该成为普通业务用户按钮。

如果我们自己维护一套 messages 压缩，再让 Codex 维护一套，会形成两套 Context Manager，最终不可预测。

---

# 14. 为什么已经有 PostgreSQL Conversation，还必须挂载 CODEX_HOME？

这是非常关键的边界。

PostgreSQL 保存的是**控制平面映射**：

```text
conversation_id
→ runtime_instance_id
→ runtime_thread_id
```

但 Codex Thread 的实际 rollout / persisted runtime state 由 Codex 保存。

因此：

```text
PostgreSQL
知道 Thread 在哪

≠
PostgreSQL 保存了 Thread 本身
```

当前 Runtime 显式设置：

```text
CODEX_HOME=/var/lib/codex
```

Docker 也声明：

```text
VOLUME /var/lib/codex
```

生产部署必须给每个 Runtime 实例配置持久卷。否则：

```text
Pod 重建
→ Postgres 仍知道 runtime_thread_id
→ 但本地 Codex Thread 文件没了
→ thread_resume 无法恢复
```

这就是为什么“控制平面持久化”和“Runtime 状态持久化”是两件事。

---

# 15. 为什么多实例现在需要 Sticky Routing？

假设：

```text
runtime-01 持有 Thread A
runtime-02 持有 Thread B
```

Conversation 表保存：

```text
conv-A → runtime-01 → thread-A
conv-B → runtime-02 → thread-B
```

如果 Gateway 把 `conv-A` 请求发到 `runtime-02`，当前实例不会假装自己能处理。

`AgentService` 会抛出：

```text
RuntimeOwnershipError
```

HTTP 返回：

```json
{
  "code": "RUNTIME_INSTANCE_MISMATCH",
  "expected_runtime_instance_id": "runtime-01"
}
```

上游 Gateway 应重新路由到 `runtime-01`。

这是当前多实例设计：

```text
Conversation Mapping
+
Per-instance persistent CODEX_HOME
+
Sticky Runtime Routing
```

后续如果 Codex Runtime 支持真正共享 Thread Storage，可以再演进成任意实例 Resume；在那之前不能假装“Postgres 一共享就天然多实例”。

---

# 16. Runtime 层代码现在主要做什么？

核心类可以这样看：

```text
GatewayPrincipal
→ 信任入口

AgentDefinition
→ 定义这个 Agent 用什么 Skill workspace、Sandbox、MCP、Tool Policy

AgentService
→ 企业 Conversation 控制面与所有权检查

ConversationRepository
→ conversation_id ↔ runtime_thread_id / runtime_instance_id

CodexRuntime
→ AgentDefinition → Codex Thread/Turn/MCP/Sandbox/Approval/Event/Context

ApprovalService
→ Codex Approval Protocol ↔ 企业审批流程

ApprovalRepository
→ 多租户、可审计审批事实源

CodexEventMapper
→ Codex 内部事件 ↔ 稳定产品事件

OpenTelemetry
→ 受控 Runtime 观测

Java Order MCP Adapter
→ Agent capability ↔ 真实业务系统
```

这就是当前 Runtime 的真正价值，而不是“帮我们调用一下 LLM”。

---

# 17. 当前生产 API

所有业务 API 都需要可信 Gateway 服务认证，并传递：

```text
Authorization: Bearer <gateway service credential>
X-User-Id: <authenticated user>
X-Tenant-Id: <tenant>
X-Roles: role1,role2
```

主要 API：

```text
POST /api/v1/agents/conversations
POST /api/v1/agents/conversations/{conversation_id}/turns
POST /api/v1/agents/conversations/{conversation_id}/turns/stream
```

Runtime 运维：

```text
GET  /api/v1/agents/conversations/{conversation_id}
POST /api/v1/agents/conversations/{conversation_id}/compact
```

要求：

```text
agent.operator
```

Approval：

```text
GET  /api/v1/approvals
POST /api/v1/approvals/{id}/approve
POST /api/v1/approvals/{id}/reject
```

要求：

```text
agent.approver
```

且审批查询和决策均按 tenant 隔离。

---

# 18. 生产依赖与启动原则

生产路径没有假数据 fallback。

Python 必填：

```text
RUNTIME_INSTANCE_ID
CODEX_HOME
ORDER_MCP_URL
ORDER_MCP_SERVICE_TOKEN
DATABASE_URL
GATEWAY_SHARED_SECRET
```

Java MCP Adapter 必填：

```text
MCP_SERVICE_TOKEN
ORDER_SERVICE_BASE_URL
ORDER_SERVICE_TOKEN
```

依赖缺失、数据库 migration 未执行、CODEX_HOME 不可写时，应启动失败，而不是返回测试订单或使用内存数据继续运行。

数据库初始 Schema：

```text
migrations/001_initial_runtime_schema.sql
```

---

# 19. 这次为什么删除所有 Demo 状态？

因为生产架构最危险的不是代码少，而是**系统在依赖失效时偷偷返回假的成功结果**。

已经移除：

```text
写死订单 1001
ConcurrentHashMap 模拟订单状态
Python 内存 ApprovalStore
Java 自动模拟 Approval 决策
Java 第二套 Codex Runtime
Java 重复 Skill
Java 重复 Prompt / Resource 事实源
```

现在：

```text
真实订单系统不可用 → 明确失败
PostgreSQL 不可用       → 启动失败
Migration 不存在        → 启动失败
Codex storage 不可写    → 启动失败
来源不明 Approval       → decline
跨 tenant Approval      → 不可见/不可决策
错误 Runtime instance  → 要求重新路由
```

这是生产代码应该有的 fail-fast / fail-closed 行为。

---

# 20. CI 为什么也是 Runtime 架构的一部分？

`.github/workflows/ci.yml` 现在会：

```text
Python
├── 启动真实 PostgreSQL 16
├── 应用 migration
├── Ruff
├── 应用层单测
└── PostgreSQL 多租户仓储集成测试

Java
├── JDK 21
├── Maven Wrapper
└── mvnw test
```

这里故意不用 SQLite 冒充 PostgreSQL，因为 Approval 使用 JSONB 和条件更新语义，数据库行为必须在真实 PostgreSQL 上验证。

---

# 21. 当前哪些部分仍然不是“完整企业平台”？

当前应称为：

> **production-grade architecture baseline / reference architecture**

而不是“任何企业直接零改动上线”。

接下来仍需要继续完善：

```text
独立 Agent Gateway 服务
真正的 Runtime Router
Agent Definition Registry / Versioning
企业 OIDC / mTLS / Secret Rotation
更完整 RBAC / ABAC Policy
Runtime instance lease / health / failover
Approval LISTEN/NOTIFY 或事件总线
数据库 migration 工具链
MCP 端到端身份传播集成测试
Evals / regression dataset
Load / chaos / security test
Quota / rate limit / cost governance
```

这也是后续学习重点。

---

# 22. 最后用一句话理解我们现在为什么这么开发

如果以后忘记所有细节，只记住：

```text
Codex Harness
负责“Agent 怎么执行”

我们的 Runtime
负责“这次执行属于谁、能接什么、如何受控、如何恢复、如何被企业系统信任”

Java MCP Adapter
负责“把 Agent 的意图转换成受治理的真实业务能力”

真实业务系统
负责“最终业务事实和最终授权”
```

这就是当前代码继续演进成企业 Agent 平台的意义。

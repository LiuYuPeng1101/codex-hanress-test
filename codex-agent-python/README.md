# Enterprise Agent Runtime on OpenAI Codex Harness

这个服务不是一个“通用 Agent 平台成品”，也不是一个把订单逻辑写死在 Prompt 里的业务机器人。

当前最准确的定位是：

> **生产导向的 Agent Runtime Kernel + Codex Runtime Adapter + 一个 Order Agent Definition。**

Codex Harness 是真正的通用执行引擎；本项目负责把 Codex 的 Thread、Skill、MCP、Approval、Sandbox、Event、Context、Compaction 等机制，转换成企业系统可以治理、持久化、观测和逐步平台化的 Runtime 契约。

未来完整 Agent Gateway 会位于它的上层，负责身份、多租户、Agent Registry、统一 Conversation、Runtime Routing、策略、审计和配额。当前项目已经建立这些能力需要的核心边界，但还不是完整 Gateway。

---

# 1. 当前架构

```text
Business UI / API Client
          │
          │ conversation_id
          ▼
   Agent Runtime Service
          │
          ├── Conversation Repository (Redis)
          ├── Approval Repository (Redis)
          ├── Agent Definition
          ├── AgentEvent / SSE
          └── OpenTelemetry
          │
          ▼
   CodexRuntime Adapter
          │
          ▼
     OpenAI Codex SDK
          │
          ▼
       Codex Harness
          │
   ┌──────┼────────┬──────────┬───────────┐
   │      │        │          │           │
 Skill   MCP    Approval   Sandbox   Context/Compaction
   │      │        │          │           │
   └──────┴────────┴──────────┴───────────┘
          │
          ▼
      MCP HTTP
          │
          ▼
    Order MCP Adapter
          │
          ▼
    Real Order Backend
```

Java 模块只承担 **Business MCP Adapter**，不再启动 Codex，也不保存任何模拟订单状态。

---

# 2. 四个层次必须分开

```text
Order Agent Definition
= 订单 Agent 的业务能力与治理配置

CodexRuntime
= 把平台 Agent Definition 翻译成 Codex SDK / App Server 参数

Codex Harness
= 真正执行 Agent Loop 的通用引擎

Order MCP Adapter
= 把受治理的 Agent Tool 映射到真实订单系统
```

因此新增 Finance Agent 或 Contract Agent 时，不应该复制 CodexRuntime；应该新增 Agent Definition、Skill 和对应 MCP Capability。

---

# 3. 为什么我们不是在“重新实现 Codex”

本项目不自己实现 ReAct Loop、Tool 调度、上下文压缩、Sandbox 或 App Server 事件路由。

这些能力由 Codex Harness 提供。我们做的是企业边界适配：

```text
Codex 原生能力
        ↓
CodexRuntime Adapter
        ↓
稳定的企业内部契约
```

这样做有三个价值：

1. 业务系统不依赖 Codex 私有协议；
2. Codex 的能力可以被企业策略治理，而不是让模型直接拥有无限权限；
3. 将来可以新增其他 Runtime Adapter，而业务层继续使用统一 Conversation / Agent / Event 契约。

---

# 4. Skill 在 Codex 里到底是什么

Skill 不是本项目自己做的 Prompt 路由器。

Codex Thread 创建时有一个 `cwd`：

```text
AgentDefinition.workspace
        ↓
thread/start cwd
        ↓
Codex Harness
        ↓
<cwd>/.agents/skills
```

Codex 根据 workspace 发现 Skill，并使用 Skill 的 metadata / instructions 影响 Agent 的任务执行方式。

当前 Order Agent 要求：

```text
required_skills = [order-analysis]
```

Runtime 启动时真实调用 Codex：

```text
skills/list
```

如果 `order-analysis` 不存在或被禁用，服务直接启动失败。`skills/list` 是 readiness 校验，不是注册动作。

生产意义：Skill 是 **版本化业务 SOP**。例如客户问：

```text
“订单 A123 怎么还没到？”
```

Skill 约束 Codex：不得猜实时状态，必须先调用真实订单 Tool，再区分事实和分析。这里不是我们的 Python `if/else` 在强行路由，而是 Codex Harness 在 Agent Loop 中使用 Skill。

---

# 5. MCP 在 Codex 里到底是什么

`CodexRuntime` 不自己用 `httpx` 调订单 API。

Agent Definition 声明：

```text
MCP Server: order
Tools:
- get_order_status
- cancel_order
```

Runtime 将其编译成 Codex `mcp_servers.*` 配置。Codex Harness 会：

```text
发现 MCP Tool Schema
        ↓
把 Tool 暴露给模型
        ↓
模型决定是否调用
        ↓
Harness 发起 MCP Tool Call
        ↓
Tool Result 回到当前 Turn
        ↓
模型继续下一步
```

当前生产策略同时配置：

```text
required = true
startup_timeout_sec = 10
tool_timeout_sec = 30
output_token_limit = 1024
```

其中 `output_token_limit` 很重要：企业 Tool 可能返回巨大 JSON，不能无限塞入模型 Context。

Java 侧只暴露语义明确的 MCP Tool：

```text
get_order_status
cancel_order
```

MCP Adapter 再调用真实 Order Backend。模型不会直接访问数据库。

---

# 6. Approval 在 Codex 里到底是什么

`cancel_order` 配置：

```text
approval_mode = prompt
```

当 Codex Harness 准备调用该 Tool 时，它不会直接执行，而会触发 App Server 的 Server Request：

```text
mcpServer/elicitation/request
meta.codex_approval_kind = mcp_tool_call
```

Thread 配置：

```text
approval_policy = on-request
approvals_reviewer = user
```

因此审批不是交给 `auto_review`，而是路由回宿主应用。

当前链路：

```text
Codex 想调用 cancel_order
        ↓
Codex 发 Approval Server Request
        ↓
approval_handler
        ↓
ApprovalService
        ↓
Redis Approval Repository
        ↓
PENDING
        ↓
人工 approve / reject
        ↓
accept / decline 返回 Codex
        ↓
Codex 继续或停止 Tool Call
```

关键状态已从进程内存迁移到 Redis，因此多个 Agent Service 实例可以共享审批记录和决策信号。

Approval 仍然 **不等于业务授权**。真实 Order Backend 必须最终检查 actor、tenant、角色、订单归属和订单状态。

---

# 7. Sandbox 在 Codex 里到底是什么

Sandbox 不是一句 Prompt：

```text
“请不要修改文件”
```

它是 Codex Runtime 的执行策略。

Order Agent 使用：

```text
Sandbox.read_only
```

因为订单 Agent 只需要读 Skill / workspace，本地没有修改文件的业务理由。

所以即使模型尝试本地写文件，Runtime 仍会阻止；但 `cancel_order` 仍可在 Approval 通过后通过 MCP 修改真实业务，因为两条执行路径不同：

```text
本地文件操作
→ Sandbox

真实订单操作
→ MCP → Approval → Business Authorization
```

因此：

```text
Sandbox != MCP Permission != Approval != Business Authorization
```

---

# 8. Event / Streaming 在 Codex 里到底是什么

App Server 本身会持续产生 Notification，例如：

```text
turn/started
item/started
item/completed
item/agentMessage/delta
turn/completed
```

官方 Python SDK 已经提供：

```python
turn = await thread.turn(...)
async for notification in turn.stream():
    ...
```

我们不重新实现 stdout Reader Loop，而是在 Runtime Adapter 上增加 `CodexEventMapper`：

```text
Codex Raw Notification
        ↓
CodexEventMapper
        ↓
AgentEvent
```

这样前端只依赖稳定平台事件：

```text
turn.started
tool.started
tool.completed
message.delta
turn.completed
```

reasoning、完整 Tool 参数、完整 Tool Result 等敏感底层数据不直接暴露给产品前端。

SSE 用于用户实时体验；OpenTelemetry 用于 Trace。Observability 平台不自研，可以接 Langfuse、Phoenix、Tempo 等 OTLP 后端。

---

# 9. Context / Compaction 在 Codex 里到底是什么

Thread 是持续会话状态，但 Thread 历史不等于下一轮模型请求的 Effective Context。

Codex Harness 会管理：

```text
Thread History
      ↓
Context Manager
      ↓
有效工作上下文
      ↓
Model
```

当上下文增长接近阈值时，Codex Core 可以自动 Compaction；也支持：

```text
thread/compact/start
```

当前 API 暴露手动 compact，但我们没有自己写摘要算法，因为这是 Harness 的职责。

Compaction 的本质是用压缩后的 summary / replacement history 继续会话，而不是把所有历史永久原样塞进模型。

这与 RAG 不同：

```text
Compaction = 管理当前 Conversation 的上下文
RAG        = 从外部知识库按需检索
```

---

# 10. Conversation 为什么不能直接等于 Codex Thread ID

Codex `thread_id` 是 Runtime-specific ID，不应该成为企业业务主键。

现在对外使用：

```text
conversation_id
```

Redis 中保存映射：

```text
conversation_id
→ agent_id
→ runtime = codex
→ runtime_thread_id
```

因此 API 调用方完全不知道 Codex Thread ID。

意义在于未来可以：

```text
conversation_id = C001

今天：runtime=codex, runtime_thread_id=xxx
以后：runtime=other, runtime_thread_id=yyy
```

业务 API 不需要跟着 Runtime 重写。

---

# 11. 一个真实订单场景怎么跑

员工在业务系统输入：

```text
“检查订单 A123。如果还没发货就帮我取消；已经发货就不要取消。”
```

完整执行链：

```text
1. Business UI 调 Order Agent Conversation
2. Agent Service 解析 conversation_id → Codex thread_id
3. Codex Thread 从 workspace 发现 order-analysis Skill
4. Skill 要求不得猜实时订单状态
5. Codex 模型选择 get_order_status
6. Harness 调 order MCP Server
7. Java Order MCP Adapter 调真实 Order Backend
8. 返回真实状态
9. 如果未发货，模型选择 cancel_order
10. Codex 发现 cancel_order=prompt
11. Harness 产生 Approval Server Request
12. Approval 持久化 Redis，等待员工审批
13. 员工 approve
14. Codex 恢复 Tool Call
15. Java MCP Adapter 调真实 Order Backend
16. Order Backend 做最终 RBAC/ABAC/tenant/order-state 校验
17. Codex 收到结果并继续生成答案
18. 全程 Event → SSE；Trace → OpenTelemetry
19. 长会话 Context 过大时由 Codex Compaction 管理
```

这就是为什么每一层都存在：不是为了把架构变复杂，而是避免“模型一句话直接改数据库”这种不可治理的系统。

---

# 12. 当前项目到底算什么

当前已经可以拆成：

```text
Agent Runtime Kernel
├── Conversation abstraction
├── Redis persistence boundary
├── Approval infrastructure
├── Event protocol
├── Observability boundary
└── Runtime lifecycle

CodexRuntime Adapter
├── Thread / Turn
├── Skill readiness
├── MCP config compilation
├── Human Approval bridge
├── Sandbox
├── Event streaming
└── Context / Compaction

Order Agent Definition
├── order-analysis Skill
├── order MCP server
├── Tool policies
└── read-only Sandbox

Order MCP Adapter
└── Real Order Backend integration
```

所以它已经是“**通用 Runtime 内核的第一版**”，但还不是完整企业 Agent Gateway。

完整 Gateway 仍应增加：

```text
Authentication / Trusted Actor Context
Tenant isolation
Agent Registry
Multiple Runtime adapters
Runtime routing / sticky routing
Rate limit / quota
Central policy
Audit storage
Secret management
Deployment HA
```

特别是 actor / tenant 身份不能作为模型可编辑的 Tool 参数。未来 Gateway 必须把可信身份作为调用上下文传给 MCP / Business Backend；当前仓库不使用假 `userId` 来掩盖这个尚未实现的安全边界。

---

# 13. 生产配置

Agent Service 必填：

```text
ORDER_MCP_URL
REDIS_URL
```

可选：

```text
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS
```

Order MCP Adapter 必填：

```text
ORDER_BACKEND_BASE_URL
```

仓库中不包含固定订单、固定审批结果、进程内审批状态或本地假业务数据库。

---

# 14. API 契约

创建业务 Conversation：

```http
POST /api/v1/agents/order/conversations
```

执行 Turn：

```http
POST /api/v1/agents/order/conversations/{conversation_id}/turns
Content-Type: application/json

{
  "message": "查询订单 A123 的真实状态"
}
```

流式 Turn：

```http
POST /api/v1/agents/order/conversations/{conversation_id}/turns/stream
```

读取 Runtime 状态：

```http
GET /api/v1/agents/order/conversations/{conversation_id}
```

触发 Compaction：

```http
POST /api/v1/agents/order/conversations/{conversation_id}/compact
```

Approval：

```http
GET  /api/v1/approvals
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

生产部署时，这些管理接口必须置于真实认证授权网关之后。

---

# 15. 最终心智模型

```text
业务需求 / Agent Definition
          │
          ▼
Enterprise Runtime Kernel
          │
          ▼
CodexRuntime Adapter
          │
          ▼
Codex Harness
          │
  ┌───────┼────────────────────────────┐
  │       │        │       │           │
Skill    MCP    Approval Sandbox   Context/Event
  │       │        │       │           │
  └───────┴────────┴───────┴───────────┘
          │
          ▼
Governed Business Capability
          │
          ▼
Business Authorization
          │
          ▼
Real Business System
```

**我们开发的意义不是再造 Harness，而是把 Harness 变成企业系统可以安全接入、可替换、可治理的 Runtime。**

# Codex Enterprise Agent Runtime Reference Architecture

这个模块不是“通用 Agent 平台”，也不是“订单 Agent SaaS 成品”。

它的准确定位是：

> **基于官方 OpenAI Codex Python SDK 的企业 Agent Runtime / Agent Service 参考实现。**

它解决的是：企业已经有自己的 Java / Spring Boot / 微服务业务系统时，如何把 Codex Harness 作为 Agent 执行内核接入现有架构，并把 Skill、MCP、Approval、Event、Sandbox、Context、Compaction 等 Codex 原生能力变成可治理的企业服务能力。

当前仓库中的“订单场景”只是一个具体 Agent Definition。Runtime 本身应该可以复用于售后、合同、财务、运维等不同业务 Agent。

---

# 1. 为什么要这样开发

如果只写：

```text
LLM + Prompt + 几个 HTTP API
```

很快会遇到这些生产问题：

```text
多轮会话由谁维护？
Agent 怎么发现和执行工具？
业务 SOP 放在哪里？
高风险写操作怎么审批？
Agent 能不能修改本机文件？
前端怎么实时看到执行过程？
长会话上下文满了怎么办？
服务重启后 Thread 怎么恢复？
如何接企业审计和 Observability？
```

Codex Harness 已经提供了其中大量 Runtime 能力。因此本项目的意义不是重新造 Agent Loop，而是：

```text
企业控制平面
        ↓
Codex Runtime Adapter
        ↓
Codex Harness
        ↓
Skill / MCP / Approval / Sandbox / Context / Event
        ↓
现有业务系统
```

我们重点开发的是 **企业边界和适配层**，而不是复制 Codex Harness 已经具备的能力。

---

# 2. 当前系统到底算什么

目前可以分成三层：

```text
1. Codex Harness
   OpenAI 提供的通用 Agent 执行内核

2. codex-agent-python
   企业 Agent Runtime / Agent Service 参考实现

3. order Agent Definition
   当前加载的具体业务 Skill + MCP Tool Policy
```

因此当前项目不是“通用底座平台”本身。

更准确的关系是：

```text
                    企业 Agent 平台 / Gateway（后续）
                               │
                     Agent Definition Registry
                               │
                               ▼
                    codex-agent-python
                    Runtime Reference Layer
                               │
                               ▼
                         Codex Harness
                               │
              ┌────────────────┼────────────────┐
              │                │                │
            Skill             MCP            Sandbox
              │                │                │
              └────────── Approval/Event ───────┘
                               │
                               ▼
                        Business Systems
```

未来真正的“通用企业 Agent 底座”还需要继续增加：

```text
Conversation ID 与 Runtime Thread ID 映射
Agent Registry
Tenant / User Identity
Runtime Routing
多实例 Thread Routing / Storage
Policy Center
Secret Management
Evals
Quota / Billing
Audit
```

---

# 3. 一个真实企业例子：电商售后 Agent

假设一家电商公司已经有：

```text
OMS 订单系统
WMS 仓储系统
退款系统
会员系统
客服后台
```

现在要做一个“售后 Agent”。

用户说：

> “订单 A20260903001 一直没到，先看看物流，如果已经超时就帮我申请取消。”

在本架构中，执行过程应该是：

```text
用户请求
  ↓
Thread / Turn
  ↓
Codex 根据 cwd 发现 after-sales Skill
  ↓
Skill 要求：先查真实状态，不允许猜
  ↓
Codex 选择 MCP get_order_status
  ↓
Java MCP Adapter
  ↓
真实 OMS API
  ↓
返回订单状态
  ↓
模型判断是否需要 cancel_order
  ↓
cancel_order 配置 approval_mode=prompt
  ↓
Codex 发 MCP Tool Approval Server Request
  ↓
企业 ApprovalService 写 PostgreSQL
  ↓
客服主管 approve / reject
  ↓
accept 后 Codex 才真正调用 cancel_order
  ↓
Java MCP Adapter
  ↓
真实 OMS API
  ↓
业务系统再次执行 user / tenant / role / order state 校验
  ↓
返回结果
  ↓
Event → SSE 给前端
  ↓
OpenTelemetry → Langfuse / Phoenix / Tempo
```

这里每一层都有明确职责，而不是把所有安全逻辑交给模型。

---

# 4. Skill 在 Codex 里是什么

当前 Skill：

```text
.agents/skills/order-analysis/SKILL.md
```

Codex 不是通过 Python `registerSkill()` 注册 Skill。

它通过 Thread 的 `cwd` 发现：

```text
<workspace>/.agents/skills
```

当前 Runtime 创建 / 恢复 Thread 时都指定：

```text
cwd = AGENT_WORKSPACE
```

因此：

```text
Thread cwd
  ↓
Codex Harness
  ↓
Skill Discovery
  ↓
读取 name / description / instructions
  ↓
模型根据任务选择 Skill
```

Skill 的意义是：

```text
Skill = 业务 SOP / How
```

例如订单 Skill 可以规定：

```text
先识别订单 ID
真实状态必须通过 Tool 获取
不得把推测写成事实
写操作必须遵守 Approval
```

Skill 不应该包含真实订单数据，也不应该替代业务 Service。

---

# 5. MCP 在 Codex 里是什么

Codex Runtime 通过 `CodexConfig.config_overrides` 配置 MCP Server：

```text
mcp_servers.order.url=<ORDER_MCP_URL>
mcp_servers.order.enabled_tools=["get_order_status","cancel_order"]
```

因此调用链不是 Python 自己 `httpx.post()`：

```text
模型
 ↓
Codex Harness
 ↓
MCP Tool Discovery / Selection
 ↓
MCP Tool Call
 ↓
Java MCP Adapter
 ↓
Business Service / Gateway
```

MCP 的意义是：

```text
MCP Tool = Agent 的受治理业务能力
```

生产 Tool 应该是：

```text
get_order_status
cancel_order
request_refund
create_invoice_draft
```

而不是：

```text
execute_sql
generic_crud
update_any_table
```

Tool 应该表达可审计、可授权、语义明确的业务动作。

---

# 6. 为什么 Java 只做 MCP Adapter

当前 Java 模块不再启动 Codex，也不保存假订单状态。

职责已经收敛为：

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

这是重要的生产边界：

```text
Codex Runtime
→ Python

Business / MCP Adapter
→ Java
```

否则 Java 和 Python 同时各启动一份 Codex Runtime，会出现两个执行内核、两套 Thread、两套 Approval，系统职责会失控。

---

# 7. Approval 在 Codex 里是什么

Tool 策略：

```text
get_order_status
→ approval_mode=approve

cancel_order
→ approval_mode=prompt
```

`prompt` 只表示：这个 MCP Tool 调用需要审批。

真正 Human-in-the-loop 还需要 Thread 配置：

```text
approval_policy = on_request
approvals_reviewer = user
```

含义：

```text
Tool 需要审批
 ↓
Codex 允许产生 Approval Request
 ↓
Reviewer=user
 ↓
审批交给 App Server Client / 宿主应用
```

当前 Python SDK 高层还没有直接暴露完整人工 approval handler，所以 Runtime Adapter 将 handler 注入 SDK 内部同步 Client。这个私有 SDK 适配只允许存在于 `CodexRuntime`，业务代码不能依赖它。

Codex 当前对 MCP Tool Approval 使用：

```text
mcpServer/elicitation/request
meta.codex_approval_kind = mcp_tool_call
```

批准返回：

```json
{"action":"accept","content":{}}
```

拒绝返回：

```json
{"action":"decline","content":null}
```

---

# 8. 为什么 Approval 必须持久化

生产路径不使用进程内 `dict` / `threading.Event` 作为审批事实来源。

当前实现使用 PostgreSQL：

```text
Codex approval handler
  ↓
ApprovalRepository.create()
  ↓
PostgreSQL approval_requests
  ↓
PENDING
  ↓
外部审批 API approve / reject
  ↓
条件更新 WHERE status=PENDING
  ↓
等待中的 Runtime 读取最终决策
```

数据库迁移：

```text
migrations/001_create_approval_requests.sql
```

这解决：

```text
审批记录可审计
多 Agent Service 实例共享审批状态
重复审批通过条件更新避免并发覆盖
超时自动 EXPIRED / decline
```

注意：**审批持久化不等于活跃 Codex Turn 已经具备跨实例恢复能力。**

如果拥有该 Turn 的 Runtime 实例死亡，仍需要后续 Runtime Routing / Lease / Resume 机制处理。这属于 Agent Gateway 和多实例阶段。

---

# 9. 用户身份为什么不能作为模型 Tool 参数

生产系统不能设计：

```text
cancel_order(orderId, userId, tenantId)
```

然后让模型生成 `userId` / `tenantId`。

因为模型输出不是可信身份来源。

正确方向：

```text
用户请求
 ↓
Gateway 完成认证
 ↓
可信 userId / tenantId / roles
 ↓
Runtime Context / MCP Authentication Context
 ↓
Java MCP Adapter
 ↓
Business Authorization
```

Tool 参数只表达业务意图：

```text
cancel_order(orderId)
```

身份属于控制平面，不属于模型自由生成的数据平面。

当前仓库下一阶段会继续实现这层可信 Conversation / Identity Context。

---

# 10. Sandbox 在 Codex 里是什么

当前订单 Agent 固定：

```text
Sandbox.read_only
```

并同时应用在线程和 Turn：

```text
ThreadStartParams.sandbox = read_only
thread.run(..., sandbox=read_only)
thread.turn(..., sandbox=read_only)
```

Sandbox 解决：

```text
Runtime 本地到底能碰哪些资源？
```

它和 Approval 不同：

```text
Approval
= 某一次动作是否被逻辑批准

Sandbox
= Runtime 的实际执行边界
```

订单 Agent 本地不需要改源码，因此只读最合理。

`Sandbox.read_only` 并不会阻止 `cancel_order`，因为订单修改通过 MCP → Java → OMS 完成，而不是修改本地文件。

---

# 11. Event / Streaming 在 Codex 里是什么

非流式：

```python
result = await thread.run(...)
```

流式场景使用官方：

```python
turn = await thread.turn(...)

async for notification in turn.stream():
    ...
```

Codex 会产生类似：

```text
turn/started
item/started
item/completed
item/agentMessage/delta
turn/completed
```

本项目不把 Raw Notification 直接暴露给前端，而是：

```text
Codex Notification
 ↓
CodexEventMapper
 ↓
AgentEvent
 ↓
SSE
```

默认只暴露：

```text
turn.started
turn.completed
tool.started
tool.completed
item.started
item.completed
message.delta
```

Reasoning、完整 Tool arguments/result、敏感文件内容不会直接推给前端。

---

# 12. Observability 为什么不用自己开发

Runtime 产生 OpenTelemetry Span / Event：

```text
agent.turn
agent.turn.stream
agent.thread.id
agent.turn.id
agent.sandbox
agent.tool.name
```

然后通过 OTLP：

```text
OpenTelemetry
 ↓
Langfuse / Phoenix / Tempo / 其他后端
```

因此项目不自研 Trace UI、Timeline Dashboard、查询平台。

Runtime 只负责标准化 Telemetry，观测平台负责展示和分析。

---

# 13. Context 在 Codex 里是什么

必须区分：

```text
Thread History
= 这段会话历史上发生过什么

Effective Context
= 当前这一轮真正交给模型工作的内容
```

Thread 可以有很多 Turn，但模型 Context Window 有 Token 上限，因此不能无限把所有原始历史重新塞进模型。

Codex Core 自己负责 Context 管理，而不是本项目自己手工拼消息数组。

这正是使用 Harness 的价值之一。

---

# 14. Compaction 在 Codex 里是什么

官方 SDK 已提供：

```text
thread.compact()
```

底层：

```text
thread/compact/start
```

Compaction 的意义不是简单删除旧消息，而是：

```text
长历史
 ↓
提取关键事实 / 状态 / 决策
 ↓
生成 compacted summary / replacement history
 ↓
后续模型使用更短的 Effective Context
```

Codex 还存在自动压缩阈值：

```text
model_auto_compact_token_limit
```

因此 Runtime 不需要自己实现：

```python
if token_count > xxx:
    自己总结聊天记录
```

当前 API：

```http
GET  /api/v1/agents/threads/{thread_id}
POST /api/v1/agents/threads/{thread_id}/compact
```

用于观察 Thread History 和触发官方 Compaction。

---

# 15. Compaction、RAG、Memory 不是一回事

```text
Compaction
= 当前 Thread 的长会话上下文管理

RAG
= 从外部知识库按需检索资料

Global Memory
= 跨 Thread 保存用户/业务长期信息
```

例如：

```text
过去 30 轮售后聊天
→ Compaction

公司 100 万份知识文档
→ RAG

用户长期偏好
→ Memory
```

不能因为有 Compaction 就不做 RAG，也不能把 Thread 当用户全局 Memory。

---

# 16. 当前生产结构

```text
Client / Future Agent Gateway
          │
          ▼
FastAPI Agent Service
          │
          ▼
AgentService
          │
          ▼
CodexRuntime Adapter
          │
          ▼
Official openai-codex SDK
          │
          ▼
Codex Harness
   │          │          │
 Skill      Sandbox     Events
   │
   ├──────── MCP ──────────────┐
   │                           │
Approval                  Java MCP Adapter
   │                           │
PostgreSQL                OrderMcpTools
                               │
                         OrderService
                               │
                         OrderGateway
                               │
                         Real OMS API
```

---

# 17. 生产依赖

Python Agent Service 必填：

```text
ORDER_MCP_URL
DATABASE_URL
```

Java MCP Adapter 必填：

```text
ORDER_SERVICE_BASE_URL
ORDER_SERVICE_TOKEN
```

没有真实依赖时服务应该启动失败或调用失败，而不是返回伪造业务结果。

---

# 18. 当前仍未完成的生产能力

这套代码已经是生产架构基线，但还不是完整企业 Agent Platform。

下一阶段必须继续补：

```text
1. Business Conversation ID
   不再把 Codex thread_id 直接暴露为业务会话 ID

2. Trusted Identity Context
   userId / tenantId / roles 从 Gateway 可信传递到 MCP / Business System

3. Runtime Instance / Thread Routing
   多实例环境下保证活跃 Thread 路由正确

4. Conversation Persistence
   conversation_id → runtime → runtime_thread_id

5. MCP Service Authentication / TLS / Secret Management

6. 数据库迁移流水线

7. Evals / Regression Gate

8. Rate Limit / Quota / Audit Policy
```

这些完成后，才会逐渐形成真正的“企业 Agent 通用底座 / Agent Gateway”。

---

# 19. 最重要的开发原则

如果以后继续增加业务 Agent，不应该复制 Runtime。

例如增加合同 Agent：

```text
复用：
Thread / Turn
Approval Framework
Sandbox
Event / SSE
OpenTelemetry
Context / Compaction
Runtime Adapter

替换 / 新增：
contract-review Skill
contract MCP Server
contract Tool Policy
contract Business Authorization
```

所以我们现在开发的意义就是：

> **把“Codex Harness 的通用执行能力”和“企业自己的业务能力/治理能力”分开，让后续 Agent 复用 Runtime，只开发真正不同的业务部分。**

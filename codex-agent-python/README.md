# Codex Single Agent Service

这个项目现在只做一件事：**开发并运行一个生产级业务 Agent**。

不再把目标设成 Agent Platform、Agent Control Plane、Agent Registry 或多 Runtime 调度平台。

当前 Agent 是订单/售后方向，但架构目标是回答一个更具体的问题：

> 我已经选择 Codex Harness 作为 Agent 容器以后，一个真实业务 Agent 还需要自己开发哪些东西？

---

## 1. 我们现在只按三层理解 Agent

```text
┌──────────────────────────────────────────────┐
│ 1. 内容层：我们主要开发                       │
│                                              │
│ Skill / Tool / MCP / Policy                  │
│ 决定：这个 Agent 会什么、应该怎么做            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 2. 容器层：Codex Harness                     │
│                                              │
│ Agent Loop / Thread / Turn / Context         │
│ Compaction / Tool Dispatch / Sandbox         │
│ 决定：这个 Agent 怎么跑                       │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 3. 最小治理层：只保留单 Agent 真正需要的能力   │
│                                              │
│ Auth / Approval / Audit / OTel / 业务权限      │
│ 决定：这个 Agent 怎么被安全地使用               │
└──────────────────────────────────────────────┘
```

这三层是后续开发的固定边界。

---

# 2. Codex Harness 已经做了什么？为什么我们不再自己做 Runtime Platform？

## 问题：既然用了 Codex Harness，为什么还需要 `CodexRuntime`？

Codex Harness 已经负责：

```text
Agent Loop
Thread / Turn
上下文管理
Compaction
Tool 调度
Sandbox
事件流
```

所以我们不应该再实现一套 Agent Loop、Memory Manager、Thread Scheduler 或 Tool Executor。

项目里的：

```text
app/runtime/codex_runtime.py
```

不是新的 Harness。

它只是一个很薄的适配层，把我们这个 Agent 的业务配置接到 Codex：

```text
AgentDefinition
     │
     ├── workspace
     ├── sandbox
     ├── MCP Server
     └── Tool Approval Policy
             │
             ▼
        CodexRuntime
             │
             ▼
        Codex Harness
```

代码职责只有：

1. `thread_start / thread_resume`
2. 给 Codex 设置 MCP 和 Tool Policy
3. 给 Thread 设置 Sandbox
4. 接 Codex Approval Handler
5. 把 Codex Event 转成我们自己的安全事件
6. 发 OpenTelemetry Trace

如果以后发现自己在 `CodexRuntime` 里写 Agent Loop、业务判断、Workflow Engine，说明又跑偏了。

---

# 3. 我们真正应该重点开发什么？

## 3.1 Skill：业务 SOP

当前 Skill 位于：

```text
.agents/skills/order-analysis/SKILL.md
```

例如真实售后 Agent 收到：

> “订单 88201 怎么还没到？如果符合条件就帮我取消。”

Skill 应该描述：

```text
先识别订单号
↓
真实状态必须调用 Tool，不允许猜
↓
如果已发货，先分析物流/取消规则
↓
事实与分析分开
↓
高风险动作必须走 Approval
```

这才是 Agent 业务能力的一部分。

---

## 3.2 MCP / Tool：真实业务能力

当前链路：

```text
Codex
  ↓
MCP
  ↓
Java Order MCP Adapter
  ↓
OrderService
  ↓
OrderGateway
  ↓
真实 OMS
```

Tool 不应该模拟订单，也不应该让 LLM 直接访问数据库。

例如：

```text
get_order_status
cancel_order
```

Tool 只表达业务动作。

真实的权限、状态校验、资源归属必须继续由订单系统完成。

---

## 3.3 Policy：Agent 能力边界

当前单 Agent Policy 直接放进 `AgentDefinition`：

```text
get_order_status → approve/自动
cancel_order     → prompt/人工审批
Sandbox          → READ_ONLY
```

这里不是在开发通用 Policy Platform。

只是明确当前这个 Agent：

```text
能调用哪些 Tool？
哪些 Tool 要审批？
本地运行环境能写文件吗？
```

---

# 4. 为什么单 Agent 仍然保留 Conversation？这是不是又平台化了？

不是。

即使系统只有一个 Agent，也可能同时有：

```text
用户 A 的会话
用户 B 的会话
用户 C 的会话
```

Codex 内部使用：

```text
thread_id
```

业务 API 使用：

```text
conversation_id
```

数据库只保存最小映射：

```text
conversation_id
tenant_id
user_id
runtime_thread_id
created_at
```

对应代码：

```text
app/conversations/conversation_repository.py
```

意义只有两个：

1. 不把 Codex 的内部 Thread ID 暴露成业务主键；
2. 校验这个 conversation 是否属于当前用户/租户。

我们已经删除：

```text
runtime_instance_id
runtime lease
runtime generation
Runtime Router
Scheduler
```

这些属于多实例平台治理，不是当前单 Agent 必需能力。

---

# 5. 为什么单 Agent 还需要 Auth？

因为“只有一个 Agent”不等于“任何人都能调用它”。

当前链路：

```text
业务系统
   │
   │ Bearer API_SHARED_SECRET
   │ X-User-Id
   │ X-Tenant-Id
   │ X-Roles
   ▼
Agent Service
   ↓
ServicePrincipal
```

对应代码：

```text
app/security/service_auth.py
```

它不是 Agent Gateway。

只是这个服务自己的入口认证和可信调用人上下文。

身份不会作为 LLM Tool 参数让模型生成。

---

# 6. 为什么单 Agent 仍然需要 Approval？

因为一个 Agent 里也可能同时存在：

```text
查询订单      → 低风险
取消订单      → 高风险
退款          → 高风险
删除数据      → 更高风险
```

所以 Approval 是**当前 Agent 的执行安全能力**，不是“很多 Agent 才需要的平台能力”。

当前流程：

```text
用户：取消订单 88201
        ↓
Codex 决定调用 cancel_order
        ↓
Codex pre-execution Approval
        ↓
ApprovalService
        ↓
PostgreSQL PENDING
        ↓
人工 approve / reject
```

Approval 通过以后，真实订单系统仍要再次检查：

```text
当前用户是谁
属于哪个 tenant
有没有 cancel 权限
订单是不是他的
订单当前状态是否允许取消
```

因此：

```text
Codex Approval
≠
Business Authorization
```

对应代码：

```text
app/approval/
```

---

# 7. 为什么还要 PostgreSQL？Codex 自己不是保存 Thread 吗？

两者保存的不是同一种状态。

```text
CODEX_HOME
   ↓
Codex Thread / Context / Compaction / Runtime State
```

而 PostgreSQL 保存：

```text
业务 conversation_id → Codex thread_id 映射
Approval 状态
审批审计信息
```

所以：

```text
Codex Harness
负责 Agent 会话状态

我们的数据库
负责业务关联和最小治理状态
```

不要自己把完整聊天历史再复制一份，然后重新实现 Codex Context Manager。

---

# 8. Context / Compaction 为什么代码很少？

因为这是 Codex Harness 的容器能力。

我们只保留两个运维入口：

```text
thread.read(include_turns=True)
thread.compact()
```

目的是诊断和必要时手工触发，而不是自己实现：

```text
历史裁剪算法
Token 统计算法
Summary 算法
Tool Result Eviction Engine
```

这些应该优先交给 Harness。

---

# 9. Event / Streaming / Observability 为什么保留？

因为这是一个真实产品 Agent 必须有的使用体验和生产排障能力。

Codex Runtime 会产生很多 Notification。

我们不会把原始 Notification 全部直接扔给前端，而是通过：

```text
CodexEventMapper
```

转换为稳定、安全的事件：

```text
turn.started
message.delta
tool.started
tool.completed
turn.completed
```

敏感 Tool Arguments、完整 Tool Result、内部 reasoning 默认不暴露。

然后：

```text
AgentEvent
├── SSE → 业务前端
└── OpenTelemetry → Langfuse / Phoenix / Tempo 等现成平台
```

我们不开发自己的 Observability 平台。

---

# 10. 为什么现在不再强依赖 agentgateway？

因为当前目标只有一个 Agent。

如果架构是：

```text
一个 Agent Service
一个业务 MCP Adapter
一个部署边界
```

一开始强制引入：

```text
Agent Gateway
Runtime Scheduler
Agent Registry
统一 LLM Gateway
多 Agent RBAC
```

会明显增加工程复杂度，却没有解决当前产品价值。

所以现在改回：

```text
Business System
      ↓
Single Agent Service
      ↓
Codex Harness
      ↓
MCP Adapter
      ↓
Business System / OMS
```

什么时候再引入 agentgateway？

当出现这些真实需求之一：

```text
多个 Agent 共用大量 MCP
统一 LLM Key / Cost / Rate Limit
统一 MCP RBAC
A2A
多个团队共享 Agent 基础设施
需要统一 egress 治理
```

在这些需求出现之前，不提前平台化。

---

# 11. 当前真实请求是怎么跑的？

以售后 Agent 为例：

```text
客服小王
“查订单 88201，如果符合条件就取消”
        ↓
FastAPI Agent API
        ↓
ServicePrincipal
确认 user / tenant / roles
        ↓
conversation_id
        ↓
ConversationRepository
找到 Codex thread_id
        ↓
CodexRuntime.thread_resume()
        ↓
Codex Harness
        ↓
发现 order-analysis Skill
        ↓
调用 get_order_status
        ↓
Java MCP Adapter
        ↓
真实 OMS
        ↓
返回订单事实
        ↓
Codex 分析
        ↓
如果决定 cancel_order
        ↓
Codex Approval
        ↓
人工审批
        ↓
批准后才允许真实写操作
        ↓
AgentEvent / SSE
        ↓
客服前端
```

这里真正属于“我们开发 Agent”的核心仍然是：

```text
Skill
Tool / MCP
Policy
业务权限契约
业务结果质量
```

而不是平台组件数量。

---

# 12. 当前代码各层到底负责什么？

```text
codex-agent-python/
│
├── .agents/skills/
│   └── order-analysis/
│       └── SKILL.md
│       # 内容层：Agent SOP
│
├── app/agents/definition.py
│   # 内容层配置：MCP / Tool Policy / Sandbox
│
├── app/runtime/codex_runtime.py
│   # Codex Harness 薄适配，不重新实现 Harness
│
├── app/services/agent_service.py
│   # 单 Agent 应用服务：conversation → thread → turn
│
├── app/conversations/
│   # 最小 conversation_id ↔ Codex thread_id 映射
│
├── app/approval/
│   # 当前 Agent 的高风险 Tool 人工审批
│
├── app/security/service_auth.py
│   # 当前 Agent Service 的入口认证
│
├── app/events/
│   # Codex Notification → 安全 AgentEvent
│
├── app/observability/
│   # OpenTelemetry 对接
│
└── api/
    # HTTP / SSE

hanress-test/
└── Java Order MCP Adapter
    # MCP Tool → 真实业务系统
```

---

# 13. 当前明确不做什么？

为了避免再次跑偏，当前阶段明确不开发：

```text
Agent Registry
多 Agent Control Plane
Runtime Scheduler
Runtime Lease
Runtime Router
Agent Marketplace
A2A Platform
统一 Agent Gateway
自研 Observability 平台
自研 Agent Loop
自研 Context Manager
```

如果未来真的出现第二、第三、第五十个 Agent，再从真实重复代码中抽平台层。

不是现在预先造出来。

---

# 14. 下一阶段应该把时间花在哪里？

现在重点从“架构底座”回到“Agent 产品能力”。

对于订单/售后 Agent，下一步应该研究：

```text
1. Skill 是否真的覆盖售后 SOP？
2. Agent 需要哪些真实 MCP Tool？
3. Tool Contract 是否足够语义化？
4. 哪些动作自动，哪些必须人工？
5. Tool 返回数据怎么防止 Prompt Injection？
6. 怎么做 Agent Evals？
7. 什么指标证明企业愿意付费？
```

这才是当前项目真正的主线。

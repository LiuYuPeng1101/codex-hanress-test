# Codex Agent Python

这是一个基于 **FastAPI + 官方 OpenAI Codex Python SDK + Java/Spring Boot MCP Server** 的企业 Agent 学习项目。

目标不是做一个简单聊天机器人，而是逐步理解一个生产级 Agent Runtime / Harness 应该具备的核心能力。

```text
用户请求
  ↓
Thread / Turn
  ↓
Skill：告诉 Agent 应该怎么做
  ↓
MCP Tool：告诉 Agent 能做什么
  ↓
Approval：控制高风险动作能不能执行
  ↓
Sandbox：限制 Runtime 实际最多能碰到哪里
  ↓
Event / Streaming：实时暴露 Agent 正在做什么
  ↓
OpenTelemetry：把运行过程送到专业 Observability 平台
  ↓
Context / Compaction：管理长会话模型上下文
  ↓
Java Business System
  ↓
Business Authorization
  ↓
真实业务 Service
```

---

# 1. 当前项目结构

```text
codex-agent-python/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── router.py
│   │       ├── health.py
│   │       ├── agent.py             # Thread / Turn / Read / Compact / SSE API
│   │       └── approval.py          # Approval API
│   ├── approval/
│   │   ├── approval_service.py
│   │   └── approval_store.py
│   ├── core/
│   │   ├── config.py
│   │   └── lifespan.py
│   ├── events/
│   │   ├── models.py                # 稳定的 AgentEvent
│   │   └── codex_event_mapper.py    # Codex Notification → AgentEvent
│   ├── observability/
│   │   └── tracing.py               # OpenTelemetry Trace
│   ├── runtime/
│   │   └── codex_runtime.py         # Codex SDK Adapter
│   ├── services/
│   │   └── agent_service.py
│   └── schemas/
├── .agents/
│   └── skills/
│       └── order-analysis/
│           └── SKILL.md
├── docs/
│   ├── approval.md
│   └── sandbox.md
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

Java `hanress-test` 模块模拟已有业务系统，通过：

```text
http://127.0.0.1:8080/mcp
```

暴露订单 MCP Server。

当前 Tool：

```text
get_order_status
→ 查询型 Tool
→ 自动执行

cancel_order
→ 写操作 Tool
→ approval_mode = prompt
→ 必须人工审批
```

---

# 2. 企业 Agent 核心心智模型

```text
Thread / Turn
= Agent 的会话与一次完整执行

Skill
= Agent 应该怎么做（How）

MCP Tool
= Agent 能做什么（Capability）

Approval
= 这一次高风险动作能不能做（Control）

Sandbox
= Runtime 实际最多能碰到哪里（Execution Boundary）

Event / Streaming
= Agent 正在做什么（Runtime Visibility）

OpenTelemetry
= 如何把运行过程标准化送到专业观测平台

Context
= 这一轮模型真正拿来工作的上下文

Compaction
= 当上下文过大时，对会话历史做压缩替换

Business Authorization
= 当前用户在真实业务上最终有没有权限
```

最终关系：

```text
                         Agent Runtime / Harness
                                  │
      ┌──────────┬──────────┬─────┼─────┬─────────────┐
      │          │          │           │             │
    Skill      MCP Tool   Approval   Sandbox        Event
   怎么做      能做什么    这次能否做   能碰哪里       做到哪了
      │          │          │           │             │
      └──────────┴──────────┴─────┬─────┴─────────────┘
                                  ↓
                         Context / Compaction
                                  ↓
                               Model
                                  ↓
                               MCP / I/O
                                  ↓
                         Java Business System
                                  ↓
                         Business Authorization
                                  ↓
                            Real Business
```

---

# 3. Thread / Turn

## 3.1 Thread

Thread 是持续存在的 Agent 会话，不是 Java Thread。

```text
Thread
├── Turn 1
├── Turn 2
├── Turn 3
└── ...
```

同一个 Thread 可以连续运行很多 Turn，并复用会话状态。

创建 Thread：

```http
POST /api/v1/agents/threads
```

## 3.2 Turn

Turn 是一次完整 Agent 执行：

```text
用户输入
→ 模型判断
→ Skill
→ Tool
→ Approval（如果需要）
→ Tool Result
→ 最终回答
```

普通非流式 API：

```http
POST /api/v1/agents/threads/{thread_id}/turns
```

当前实现本质上是：

```python
result = await thread.run(
    message,
    sandbox=Sandbox.read_only,
)
```

---

# 4. Skill：Agent 应该怎么做

当前 Skill：

```text
.agents/skills/order-analysis/SKILL.md
```

核心规则：

```text
1. 先识别订单 ID
2. 不允许猜测实时订单状态
3. 已接入 MCP Tool 时优先查询真实业务数据
4. 区分事实数据和分析结论
5. 最终用中文给出明确结论
```

一句话：

```text
Skill = How
Tool = Action
```

Skill 不负责伪造业务事实，也不应该把真实业务逻辑写死在 Markdown 中。

Skill 通过 Thread 的 `cwd` 被 Codex Harness 从：

```text
<workspace>/.agents/skills
```

发现，不需要业务代码手动注册。

---

# 5. MCP / Tool：Agent 能做什么

Python Agent Service 不直接调用 Java 业务 REST，而是：

```text
模型
 ↓
Codex Harness
 ↓
MCP Tool Discovery
 ↓
Tool Call
 ↓
Java MCP Server
 ↓
Business Service
```

推荐 Tool 设计：

```text
get_order_status
cancel_order
request_refund
create_invoice_draft
```

不推荐直接暴露：

```text
execute_sql
generic_crud
update_table
```

真实项目更推荐：

```text
Java Business Service
        ↑
Agent MCP Adapter
```

当前订单 Tool 策略：

```text
get_order_status → approval_mode=approve
cancel_order     → approval_mode=prompt
```

---

# 6. Approval：高风险动作谁来决定

三个概念不要混：

```text
approval_policy
→ 是否允许产生审批请求

approvals_reviewer
→ 审批发生后交给谁判断

approval_handler
→ 宿主程序怎么接住审批请求
```

当前 Human-in-the-loop 使用：

```text
approval_policy = on_request
approvals_reviewer = ApprovalsReviewer.user
```

含义：

```text
需要审批
→ 不交给 Codex auto reviewer
→ 交还给宿主应用
→ ApprovalService
→ ApprovalStore
→ 人工 approve / reject
```

`cancel_order` 链路：

```text
用户要求取消订单
 ↓
Agent 决定调用 cancel_order
 ↓
approval_mode=prompt
 ↓
MCP Tool Approval
 ↓
approvals_reviewer=user
 ↓
ApprovalService
 ↓
PENDING
 ↓
人工 approve / reject
 ↓
accept / decline
 ↓
Codex 决定是否真正执行 Tool
```

当前 ApprovalStore 是学习用内存实现；生产环境应使用 DB / Redis + Approval Center。

---

# 7. Approval 不等于 Business Authorization

即使 Approval 已经通过，Java Business System 仍然必须独立检查：

```text
userId
role
tenantId
订单归属
订单状态
金额阈值
业务规则
```

所以：

```text
Codex Approval
≠
Business Authorization
```

---

# 8. Event / Streaming / Observability

## 8.1 Event

App Server 是事件驱动的，一个 Turn 中会出现：

```text
turn/started
item/started
item/completed
item/agentMessage/delta
turn/completed
```

Event 是结构化运行事实，不等同于普通文本 Log。

## 8.2 Streaming

流式链路使用官方 SDK：

```python
turn = await thread.turn(
    message,
    sandbox=Sandbox.read_only,
)

async for notification in turn.stream():
    ...
```

SSE API：

```http
POST /api/v1/agents/threads/{thread_id}/turns/stream
```

前端可实时收到：

```text
turn.started
tool.started
tool.completed
message.delta
turn.completed
```

## 8.3 为什么不把 Raw Notification 直接给前端

当前使用 `CodexEventMapper`：

```text
Codex Raw Notification
        ↓
CodexEventMapper
        ↓
AgentEvent
        ↓
SSE / OpenTelemetry
```

默认不直接透传：

```text
reasoning 事件
完整 Tool arguments
完整 Tool result
敏感文件内容
```

这样既避免前端绑定 Codex 私有协议，也降低敏感信息泄漏风险。

## 8.4 Observability 不自研平台

项目不自己开发 Trace UI / Timeline / Dashboard，而是：

```text
CodexRuntime
 ↓
OpenTelemetry
 ↓
OTLP
 ↓
Langfuse / Phoenix / Tempo / 其他 OTLP Backend
```

`.env.example`：

```text
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
```

留空时本地不发送远程 Trace。

---

# 9. Sandbox：Runtime 真正的执行边界

Sandbox 回答：

> 即使模型想做、甚至某次 Approval 已经批准，Runtime 实际最多允许它访问和修改哪些本地资源？

官方 Python SDK 提供：

```python
Sandbox.read_only
Sandbox.workspace_write
Sandbox.full_access
```

简单理解：

```text
read_only
→ 可读文件，不允许写

workspace_write
→ 可读，并允许写 workspace / configured writable roots

full_access
→ 取消 Codex 文件系统 Sandbox 的主要限制
→ 底层对应 danger-full-access
```

生产环境应遵循最小权限原则。

---

# 10. Sandbox 与 Approval 的区别

```text
Approval
= 人/策略对某一次动作做逻辑授权

Sandbox
= Runtime 对执行环境做强制限制
```

类比公司门禁：

```text
Approval
→ 领导同意你今天进入机房

Sandbox
→ 你的门禁卡实际只允许进入 A 区和 B 区
```

二者是叠加关系，不是替代关系。

---

# 11. 当前订单 Agent 为什么使用 read_only

订单 Agent 的本地职责主要是：

```text
读取 Skill
读取必要 workspace 信息
模型推理
调用 MCP Tool
```

它不需要修改本地源码或创建文件，因此当前显式使用：

```text
Sandbox.read_only
```

Thread 创建：

```python
params = ThreadStartParams(
    approval_policy=...,
    approvals_reviewer=ApprovalsReviewer.user,
    sandbox=SandboxMode.read_only,
    cwd=str(self._workspace),
)
```

普通 Turn：

```python
result = await thread.run(
    message,
    sandbox=Sandbox.read_only,
)
```

流式 Turn：

```python
turn = await thread.turn(
    message,
    sandbox=Sandbox.read_only,
)
```

OpenTelemetry Span 中也记录：

```text
agent.sandbox = read-only
```

---

# 12. read_only 为什么仍然可以 cancel_order

`Sandbox.read_only` 主要限制 Codex Runtime 的本地执行环境。

`cancel_order` 走的是：

```text
Codex Harness
 ↓
MCP
 ↓
Approval
 ↓
Java Business System
 ↓
Business Authorization
 ↓
OrderService
```

所以可以出现：

```text
本地文件：只读
真实订单：审批 + Java 权限通过后可以修改
```

因此：

```text
Sandbox
≠ MCP Tool Permission
≠ Approval
≠ Business Authorization
```

详细实验见：

```text
docs/sandbox.md
```

---

# 13. Context：模型这一轮真正拿来工作的内容

这是 Context 阶段最重要的概念：

```text
Thread
= 整个会话发生过什么

Context
= 当前这一轮真正送给模型、用于推理的工作集
```

所以：

```text
Thread 历史很长
≠
下一轮一定把全部原始历史 100% 原样送给模型
```

模型的 Context Window 是有限的，因此 Harness 必须管理有效上下文。

概念上一次模型调用可能包含：

```text
System / Developer Instructions
Skill / 当前规则
压缩后的历史摘要
最近几轮消息
必要 Tool Result
当前用户输入
```

而不是无限增长的全部原始记录。

---

# 14. Thread History 与 Effective Context 要分开

可以把它类比成数据库：

```text
conversation_history 表
→ 保存了 1000 条历史记录
```

并不意味着每次模型请求都：

```text
SELECT * FROM conversation_history
```

然后全部塞给模型。

更合理的是：

```text
Persistent Thread History
        ↓
Context Manager / Harness
        ↓
保留 / 裁剪 / Compact
        ↓
Effective Context
        ↓
Model
```

因此企业架构中要区分：

```text
Audit / Persistent History
≠
Model Context
```

完整 Tool Result 可能为了审计长期保存，但模型后续并不需要每轮都看到巨大原始 JSON。

---

# 15. Compaction：长会话怎么继续运行

当 Thread 持续很多轮后，Context Token 会越来越大。

Compaction 的目的不是简单“忘掉旧聊天”，而是：

```text
旧历史
 ↓
提炼关键事实 / 决策 / 当前任务状态
 ↓
生成 summary
 ↓
构造 compacted / replacement history
 ↓
用更短的 Effective Context 继续工作
```

可以理解成：

```text
History Replacement
而不是
History Forget
```

例如大量原始历史：

```text
用户查询订单1001
Tool 返回 SHIPPED
继续讨论送达时间
继续讨论延迟
继续讨论取消
...
```

Compact 后可能保留成：

```text
此前会话摘要：
- 当前处理订单1001
- 已确认状态 SHIPPED
- 用户讨论过延迟问题
- 用户考虑取消订单
- cancel_order 属于需要人工审批的写操作
```

后续模型依赖摘要 + 最近上下文继续工作。

---

# 16. Context Window 与自动 Compaction

Codex 配置层有两个重要概念：

```text
model_context_window
→ 模型上下文窗口大小

model_auto_compact_token_limit
→ Token 使用达到阈值时触发自动 Compaction
```

不能等 Context 100% 塞满才压缩，因为还需要为：

```text
当前用户输入
Tool Result
模型生成
后续推理
```

留空间。

概念上：

```text
总 Context Window
████████████████████

历史增长到阈值
██████████████░░░░░░
              ↑
        Auto Compact
```

Harness 的价值之一就是让长时间 Agent 不因为历史无限膨胀直接失效。

---

# 17. Compaction 不等于 RAG，也不等于全局 Memory

三者解决的问题完全不同。

```text
Compaction
→ 当前 Thread 太长怎么办
→ 管理 Conversation Context

RAG
→ 外部大量知识怎么按需检索
→ 合同库、知识库、客户资料等

Global Memory
→ 跨 Thread 的长期用户/业务记忆怎么管理
```

所以：

```text
Compaction ≠ RAG
Compaction ≠ Vector DB
Thread Context ≠ 全局 Memory
```

---

# 18. Tool Result 为什么容易撑爆 Context

企业 Tool 很可能一次返回大量内容：

```text
search_contracts
→ 几百 KB / 几 MB JSON
```

如果每次都把完整 Tool Result 永久带进模型 Context，会快速消耗 Context Window。

成熟 Harness 通常会组合：

```text
Tool Result Truncation
Tool Result Eviction
Compaction
```

因此：

```text
运行轨迹 / 审计数据
可以完整保存

模型工作 Context
应该只保留真正需要的内容
```

---

# 19. 当前新增 Thread Read API

为了观察 Thread 与 Context 的区别，项目新增：

```http
GET /api/v1/agents/threads/{thread_id}
```

内部使用：

```python
thread = await self._codex.thread_resume(thread_id)
response = await thread.read(include_turns=True)
```

它返回的是 **Thread 快照 / Turn 历史**。

注意：

> 这个接口看到的 Thread 历史，不代表下一轮模型一定会把这些内容全部原样作为 Effective Context。

这正是我们做这个实验的目的。

---

# 20. 当前新增 Manual Compact API

新增：

```http
POST /api/v1/agents/threads/{thread_id}/compact
```

内部：

```python
thread = await self._codex.thread_resume(thread_id)
await thread.compact()
```

底层对应：

```text
thread/compact/start
```

因此 API 返回：

```json
{
  "thread_id": "...",
  "status": "COMPACTION_STARTED"
}
```

这里故意不返回 `COMPLETED`，因为官方接口语义是“启动一次 Compaction”，不是我们自己伪造一个同步完成状态。

---

# 21. Context / Compaction 实验

建议使用同一个 Thread 连续执行多轮。

第一轮：

```text
请记住：这个测试项目代号叫“北极星”，负责人叫小李。
```

第二轮：

```text
订单1001是什么状态？
```

第三轮：

```text
请再次告诉我项目代号和负责人。
```

然后读取 Thread：

```http
GET /api/v1/agents/threads/{thread_id}
```

再触发：

```http
POST /api/v1/agents/threads/{thread_id}/compact
```

之后继续同一个 Thread：

```text
我们之前约定的项目代号和负责人是什么？
```

观察关键事实是否继续保留。

这个实验要理解的是：

```text
Thread 仍然是同一个 Thread
 ↓
历史可能发生 Compaction
 ↓
模型工作 Context 变短
 ↓
关键状态仍应尽量被摘要保留
```

---

# 22. 当前完整订单 Agent 安全模型

```text
Order Agent
│
├── Skill
│   └── order-analysis
│
├── MCP Tools
│   ├── get_order_status → auto
│   └── cancel_order → prompt
│
├── Approval
│   └── Human-in-the-loop
│
├── Sandbox
│   └── read_only
│
├── Event / Streaming
│   └── SSE
│
├── Observability
│   └── OpenTelemetry / OTLP
│
├── Context
│   └── Thread + Effective Context
│
├── Compaction
│   └── Auto + Manual
│
└── Java Business System
    └── Final Authorization
```

---

# 23. 本地 / Codespaces 联调

Java：

```bash
cd hanress-test
mvn spring-boot:run
```

Python：

```bash
cd codex-agent-python
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

当前主要 API：

```text
POST /api/v1/agents/threads
GET  /api/v1/agents/threads/{thread_id}
POST /api/v1/agents/threads/{thread_id}/compact
POST /api/v1/agents/threads/{thread_id}/turns
POST /api/v1/agents/threads/{thread_id}/turns/stream

GET  /api/v1/approvals
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

---

# 24. 当前学习进度

已完成：

```text
Thread / Turn                 ✅
Skill                         ✅
MCP / Tool                    ✅
Approval / Human-in-the-loop  ✅
Event                         ✅
Streaming / SSE               ✅
OpenTelemetry Observability   ✅
Sandbox                       ✅
```

当前阶段：

```text
Context / Compaction          ← 进行中
```

后续：

```text
Thread persistence / resume
→ 多实例
→ Agent Gateway
```

---

# 25. 最终记忆版

```text
Thread
= 会话历史容器

Context
= 模型当前工作集

Compaction
= 长会话上下文压缩机制

Skill
= 怎么做

MCP Tool
= 能做什么

Approval
= 这一次能不能做

Sandbox
= 本地执行环境最多能碰哪里

Event
= Agent 做到哪了

OpenTelemetry
= 如何把运行数据交给专业观测平台

Business Authorization
= 真实业务最终权限边界
```

这就是当前项目逐步构建企业 Agent Service 的核心路线。

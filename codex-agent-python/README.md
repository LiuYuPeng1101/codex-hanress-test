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
│   │       ├── agent.py             # Thread / Turn / SSE API
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

Business Authorization
= 当前用户在真实业务上最终有没有权限
```

最终安全模型：

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

Thread 可以理解成一个持续存在的 Agent 会话，不是 Java Thread。

```text
Thread
├── Turn 1
├── Turn 2
├── Turn 3
└── ...
```

同一个 Thread 可以连续运行很多 Turn，并复用上下文。

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

当前非流式实现本质上是：

```python
result = await thread.run(message, sandbox=Sandbox.read_only)
return result.final_response
```

---

# 4. Skill：Agent 应该怎么做

当前项目 Skill：

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

```python
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

`cancel_order` 完整链路：

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
turn = await thread.turn(message, sandbox=Sandbox.read_only)

async for notification in turn.stream():
    ...
```

新增 SSE API：

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

新增 `CodexEventMapper`：

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

`.env.example` 中：

```text
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
```

留空时本地不发送远程 Trace。

---

# 9. Sandbox：Runtime 真正的执行边界

Sandbox 回答的问题不是“模型想不想做”，而是：

> 即使模型想做、甚至某次 Approval 已经批准，Runtime 实际最多允许它访问和修改哪些本地资源？

官方 Python SDK 提供三个预设：

```python
Sandbox.read_only
Sandbox.workspace_write
Sandbox.full_access
```

可以简单理解为：

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

这是 Sandbox 阶段最重要的知识点：

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

即使 Approval 通过，也不代表执行环境没有边界。

因此二者是叠加关系，不是替代关系。

---

# 11. 当前订单 Agent 为什么使用 read_only

订单 Agent 的本地职责主要是：

```text
读取 Skill
读取必要 workspace 信息
模型推理
调用 MCP Tool
```

它不需要修改本地源码或创建文件。

所以当前最合理的最小权限是：

```text
Order Agent
→ Sandbox.read_only
```

当前代码在三处显式固定 Sandbox，而不是依赖 Codex 默认配置。

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

这样不会受机器上 Codex 默认 Sandbox 或历史 Thread 状态影响。

OpenTelemetry Span 中也会记录：

```text
agent.sandbox = read-only
```

---

# 12. read_only 为什么仍然可以 cancel_order

这是最容易混淆的一点。

`Sandbox.read_only` 主要限制 Codex Runtime 的本地执行环境，例如文件系统。

而：

```text
cancel_order
```

走的是：

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
真实订单：在审批 + Java 权限校验通过后可以修改
```

这并不矛盾。

因此：

```text
Sandbox
≠ MCP Tool Permission
≠ Approval
≠ Business Authorization
```

---

# 13. Sandbox 实验

详细说明见：

```text
docs/sandbox.md
```

## 13.1 读取实验

向订单 Agent 发送：

```text
请读取当前 workspace 中 README.md 的第一行，并告诉我内容。不要修改任何文件。
```

预期：读取成功。

## 13.2 写入实验

发送：

```text
请在当前 workspace 创建 sandbox-test.txt，并写入 hello sandbox。
```

预期：写入失败或被 Runtime 拒绝。

这个实验的价值在于验证：

```text
Sandbox 不是 Prompt 中一句“不要修改文件”
而是 Runtime 的真实执行权限边界
```

---

# 14. 不同 Agent 应该有不同 Sandbox

不要为了方便所有 Agent 都开最大权限。

```text
OrderAgent
├── Skill: order-analysis
├── Tool: get_order_status / cancel_order
├── Sandbox: read_only
└── Approval: cancel_order=human

CodingAgent
├── Skill: java-development
├── Tool: GitHub / CI
├── Sandbox: workspace_write
└── Approval: dangerous action=prompt

FinancialAnalysisAgent
├── Tool: read-only finance tools
├── Sandbox: read_only
└── Business Authorization: finance RBAC
```

因此以后进入 Agent Gateway / Agent Definition 后，Sandbox 应成为 Agent Definition 的一部分。

---

# 15. 当前完整订单执行链

查询订单：

```text
用户
 ↓
FastAPI
 ↓
CodexRuntime
 ↓
Thread / Turn
 ↓
Sandbox.read_only
 ↓
order-analysis Skill
 ↓
get_order_status
 ↓
MCP
 ↓
Java Business System
 ↓
SHIPPED
 ↓
Event / SSE / Trace
 ↓
最终回答
```

取消订单：

```text
用户
 ↓
Sandbox.read_only（本地仍只读）
 ↓
Agent 决定调用 cancel_order
 ↓
approval_mode=prompt
 ↓
Human Approval
 ↓
MCP
 ↓
Java Business Authorization
 ↓
OrderService.cancelOrder()
 ↓
Event / SSE / Trace
 ↓
最终回答
```

---

# 16. 为什么企业 Agent 需要 Harness

如果只有：

```text
LLM + Prompt
```

很难稳定解决：

```text
Thread / Turn 生命周期
Skill 发现
Tool 调用
Approval
Sandbox
Event / Streaming
Context / Compaction
Thread 恢复
多实例
Observability
```

Harness / Agent Runtime 就是把这些执行能力组织起来。

---

# 17. 本地 / Codespaces 联调

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

常用 API：

```text
POST /api/v1/agents/threads
POST /api/v1/agents/threads/{thread_id}/turns
POST /api/v1/agents/threads/{thread_id}/turns/stream
GET  /api/v1/approvals
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

---

# 18. 当前学习进度

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

# 19. 下一阶段：Context / Compaction 要解决什么

同一个 Thread 会不断累积：

```text
用户消息
Agent 消息
Tool Call
Tool Result
系统 / 开发者指令
Skill 相关信息
其他运行上下文
```

问题是模型上下文窗口不是无限的。

所以接下来要回答：

```text
Thread 历史和模型 Context 是不是同一个东西？
一个 Thread 聊很久后发生什么？
Tool Result 会不会永远原样塞进后续上下文？
Compaction 到底压缩什么？
压缩以后 Thread 历史还在不在？
Compaction 和 RAG / Vector Memory 是不是一回事？
什么时候自动 compact，什么时候手动 compact？
```

这就是下一阶段的重点。

---

# 20. 最终记忆版

```text
Skill
= 怎么做

MCP Tool
= 能做什么

Approval
= 这一次能不能做

Sandbox
= 实际最多能碰哪里

Business Authorization
= 当前用户在真实业务上最终有没有权限

Event
= 发生了什么

Streaming
= 如何实时传出去

OpenTelemetry
= 如何送进专业观测平台

Context / Compaction
= Thread 变长以后，如何让模型继续有效工作
```

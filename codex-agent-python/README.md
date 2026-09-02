# Codex Agent Python

这是一个基于 **FastAPI + 官方 OpenAI Codex Python SDK + Java/Spring Boot MCP Server** 的企业 Agent 学习项目。

目标不是做一个简单聊天机器人，而是逐步理解一个生产级 Agent Runtime / Harness 应该具备的核心能力：

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
Event / Streaming：实时暴露 Agent 正在做什么
  ↓
OpenTelemetry：把运行过程送到专业 Observability 平台
  ↓
Java Business System
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
│   └── approval.md
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

# 2. 企业 Agent 的核心心智模型

目前已经学过的几个核心概念可以用下面几句话记住：

```text
Thread / Turn
= Agent 的会话与一次完整执行

Skill
= Agent 应该怎么做（How）

MCP Tool
= Agent 能做什么（Capability）

Approval
= 高风险动作能不能做（Control）

Event / Streaming
= Agent 正在做什么（Runtime Visibility）

OpenTelemetry
= 如何把运行过程标准化送到专业观测平台

Business Authorization
= 最终业务安全边界
```

整体关系：

```text
                        Agent Runtime / Harness
                                  │
           ┌──────────────────────┼──────────────────────┐
           │                      │                      │
         Skill                  MCP Tool              Approval
        怎么做                  能做什么              能不能做
           │                      │                      │
           └──────────────────────┼──────────────────────┘
                                  ↓
                              Event Stream
                                  ↓
                       ┌──────────┴──────────┐
                       │                     │
                      SSE              OpenTelemetry
                       │                     │
                     Browser          Langfuse/Phoenix/
                                      Tempo 等平台
                                  ↓
                          Java Business System
                                  ↓
                        Final Authorization
```

---

# 3. Thread / Turn

## 3.1 Thread

Thread 可以理解成一个持续存在的 Agent 会话。

它不是 Java Thread。

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

响应：

```json
{
  "thread_id": "thr_xxx"
}
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
Content-Type: application/json

{
  "message": "订单1001现在是什么状态？"
}
```

当前非流式实现本质上是：

```python
result = await thread.run(message)
return result.final_response
```

`thread.run()` 是官方 SDK 提供的便利方法，它会把 Turn 启动、事件消费、最终结果收集等过程封装掉。

---

# 4. Skill：Agent 应该怎么做

## 4.1 Skill 是什么

Skill 可以理解成 Agent 的 SOP、领域规范、操作方法论。

当前项目：

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

Skill 主要解决：

```text
面对某类任务：
应该先做什么？
哪些信息必须确认？
哪些事情不能猜？
应该优先用哪个 Tool？
答案应该怎么组织？
```

## 4.2 Skill 与 Tool 的区别

```text
Skill = How
Tool = Action
```

错误做法：

```text
Skill 里写死：订单1001是 SHIPPED
```

正确做法：

```text
Skill 要求 Agent 不得猜订单状态，必须调用真实订单 Tool。
```

## 4.3 Skill 如何被发现

环境变量：

```text
AGENT_WORKSPACE=.
```

创建 Thread 时把 workspace 作为 `cwd`，Codex Harness 会在：

```text
<workspace>/.agents/skills
```

发现项目级 Skill。

因此不是自己写：

```text
registerSkill(...)
```

而是：

```text
Thread cwd
  ↓
Codex Harness
  ↓
发现 .agents/skills
  ↓
读取 Skill metadata / instructions
  ↓
根据用户任务选择 Skill
```

---

# 5. MCP / Tool：Agent 能做什么

## 5.1 MCP 在本项目中的作用

Python Agent Service 不直接写：

```python
httpx.post("http://java/order/cancel")
```

而是：

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

这样 Harness 可以统一管理：

```text
Tool Schema
Tool 参数
Tool 选择
Tool 调用
Tool Result
Approval
事件
```

## 5.2 Tool 应该怎么设计

推荐：

```text
get_order_status
cancel_order
request_refund
create_invoice_draft
submit_contract_review
```

不推荐：

```text
execute_sql
generic_crud
update_table
```

原因是企业 Agent 的 Tool 应该表达真实、可治理的业务动作。

真实项目更建议：

```text
Java Business Service
        ↑
Agent MCP Adapter
```

MCP Adapter 调原有 Service，而不是把核心 Service 全部直接暴露给 Agent。

## 5.3 当前 MCP 配置

`CodexRuntime` 注入：

```text
mcp_servers.order.url=<ORDER_MCP_URL>
mcp_servers.order.enabled_tools=["get_order_status","cancel_order"]
mcp_servers.order.default_tools_approval_mode="approve"
mcp_servers.order.tools.get_order_status.approval_mode="approve"
mcp_servers.order.tools.cancel_order.approval_mode="prompt"
```

因此：

```text
get_order_status
→ approve
→ 自动执行

cancel_order
→ prompt
→ 进入 Approval
```

---

# 6. Approval：高风险动作谁来决定

Agent 与传统系统最大的区别之一是：

```text
传统系统：
用户点击一个确定按钮
→ Controller
→ Service
→ DB

Agent：
用户说自然语言
→ 模型自己判断下一步
→ 模型决定调用 Tool
→ Tool 可能修改真实业务
```

因此写操作不能全部自动执行。

## 6.1 三个容易混淆的概念

```text
approval_policy
→ 是否允许产生审批请求 / 什么情况下需要审批

approvals_reviewer
→ 审批发生后交给谁判断

approval_handler
→ 宿主应用具体怎么接住审批请求
```

## 6.2 ApprovalMode.auto_review

当前 Python 高层 SDK 主要暴露：

```python
ApprovalMode.deny_all
ApprovalMode.auto_review
```

`auto_review` 可以理解成：

```text
approval_policy = on-request
approvals_reviewer = auto_review
```

也就是：

```text
需要审批
→ Codex 自动 reviewer 判断
```

## 6.3 ApprovalsReviewer.user

企业 Human-in-the-loop 需要：

```text
需要审批
→ 真实员工 / 管理员决定
```

底层协议支持：

```python
ApprovalsReviewer.user
```

当前 Thread 创建使用：

```python
params = ThreadStartParams(
    approval_policy=AskForApproval(
        root=AskForApprovalValue.on_request
    ),
    approvals_reviewer=ApprovalsReviewer.user,
    cwd=str(self._workspace),
)
```

这里的 `user` 更准确理解为：

```text
把审批交还给 App Server Client / 宿主应用处理
```

当前宿主应用就是 FastAPI Agent Service。

## 6.4 approval_handler

`lifespan.py` 把：

```python
approval_service.handle_codex_request
```

交给 `CodexRuntime`。

当前官方 `AsyncCodex` 高层构造器还没有直接暴露 `approval_handler`，所以 Runtime Adapter 内部暂时使用：

```python
self._codex._client._sync._approval_handler = approval_handler
```

因为这是 SDK 私有字段，所以必须限制在 `CodexRuntime` 内，不应该让 Controller / Service 到处依赖。

## 6.5 cancel_order 完整 Human-in-the-loop

```text
用户：取消订单1001
 ↓
Agent 决定调用 cancel_order
 ↓
approval_mode = prompt
 ↓
产生 MCP Tool Approval
 ↓
approvals_reviewer = user
 ↓
mcpServer/elicitation/request
 ↓
approval_handler
 ↓
ApprovalService
 ↓
ApprovalStore.create()
 ↓
PENDING
 ↓
等待人工
   ┌───────┴───────┐
   │               │
approve           reject
   │               │
accept           decline
   │               │
   └───────┬───────┘
           ↓
         Codex
           ↓
是否真正执行 cancel_order
```

批准 API：

```http
POST /api/v1/approvals/{approval_id}/approve
```

拒绝 API：

```http
POST /api/v1/approvals/{approval_id}/reject
```

当前 `ApprovalStore` 是学习用内存实现。生产环境应演进为 DB / Redis + Approval Center。

---

# 7. Codex Approval 不等于业务权限

即使 Codex Approval 已经批准，Java Business System 仍然必须独立检查：

```text
userId
角色
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

企业安全通常至少需要：

```text
Agent Policy
+ Approval
+ Sandbox
+ Business Authorization
+ Audit
```

---

# 8. Event：Agent 运行过程中发生了什么

完成 Skill / MCP / Approval 后，新的问题是：

> Agent 这一轮执行过程中到底发生了什么？

App Server 本身就是事件驱动的。

一个 Turn 可以出现：

```text
turn/started
 ↓
item/started
 ↓
Tool / Message / 其他 Item
 ↓
item/completed
 ↓
item/agentMessage/delta
 ↓
turn/completed
```

## 8.1 Event 与 Log 的区别

Log：

```text
给开发人员阅读的文本日志
```

例如：

```text
订单查询成功
```

Event：

```json
{
  "type": "tool.completed",
  "thread_id": "t001",
  "turn_id": "r001",
  "tool_name": "get_order_status"
}
```

是结构化数据，可以被：

```text
前端
Trace 系统
监控系统
审计系统
指标系统
```

消费。

## 8.2 Item 是什么

Thread / Turn / Item 的关系：

```text
Thread
├── Turn 1
│   ├── User Message
│   ├── MCP Tool Call
│   └── Agent Message
└── Turn 2
    ├── User Message
    ├── Approval
    ├── MCP Tool Call
    └── Agent Message
```

因此：

```text
item/started
```

表示 Turn 内的某个 Item 开始，而不是整个 Agent 开始。

---

# 9. Streaming：实时看到 Agent 执行过程

非流式：

```text
用户请求
 ↓
等待 10 秒
 ↓
一次性得到最终 answer
```

流式：

```text
turn.started
 ↓
tool.started
 ↓
tool.completed
 ↓
message.delta
 ↓
message.delta
 ↓
turn.completed
```

## 9.1 Delta 是什么

最终答案：

```text
订单1001已经发货。
```

可能分成：

```text
delta1 = "订单"
delta2 = "1001"
delta3 = "已经发货"
delta4 = "。"
```

Client 持续拼接后得到最终文本。

## 9.2 官方 Python SDK 的正确用法

原来：

```python
result = await thread.run(message)
```

适合只关心最终结果。

现在流式链路使用官方公开接口：

```python
turn = await thread.turn(message)

async for notification in turn.stream():
    ...
```

这里的 `turn` 是 `AsyncTurnHandle`。

官方 SDK 会按 `turn_id` 路由 Notification，因此一个 `AsyncCodex` 可以同时承载多个活跃 Turn，而不需要我们自己写 stdout Reader Loop。

---

# 10. 为什么不把 Codex Raw Notification 直接给前端

当前新增：

```text
CodexEventMapper
```

流程：

```text
Codex Raw Notification
        ↓
CodexEventMapper
        ↓
安全、稳定的 AgentEvent
        ↓
SSE / OpenTelemetry
```

前端只允许看到适合产品展示的事件，例如：

```text
turn.started
turn.completed
tool.started
tool.completed
item.started
item.completed
message.delta
```

不直接透传：

```text
reasoning 事件
完整 Tool arguments
完整 Tool result
文件内容
其他可能包含敏感信息的底层事件
```

原因有两个：

```text
1. 前端不应该依赖 Codex 私有协议细节
2. 企业 Tool 参数和结果可能包含敏感数据
```

所以 `AgentEvent` 是我们自己的稳定协议。

---

# 11. SSE：把 Agent Event 推给浏览器

新增流式 API：

```http
POST /api/v1/agents/threads/{thread_id}/turns/stream
Content-Type: application/json

{
  "message": "订单1001现在是什么状态？"
}
```

返回 `text/event-stream`。

示意：

```text
event: turn.started
data: {...}

event: tool.started
data: {"tool_name":"get_order_status"}

event: tool.completed
data: {...}

event: message.delta
data: {"delta":"订单"}

event: message.delta
data: {"delta":"1001"}

event: turn.completed
data: {...}
```

## 11.1 为什么当前优先 SSE，而不是 WebSocket

当前 Agent 对话主要是：

```text
Browser
→ HTTP 发送一次请求

Server
→ 持续推送运行过程
```

核心数据方向是 Server → Browser，因此 SSE 简单且合适。

以后如果需要：

```text
实时语音
高频双向交互
Turn Steer
远程协同控制
```

再考虑 WebSocket。

---

# 12. Observability：不要自己造平台

Observability 不是简单打印日志。

企业真正需要知道：

```text
某个 Turn 总耗时多久？
哪个 Tool 最慢？
Tool 失败率多少？
Approval 等了多久？
哪些 Agent 经常失败？
哪些 Session 成本最高？
某个生产故障经过了哪些步骤？
```

这些能力已经有成熟平台。

例如：

```text
Langfuse
Arize Phoenix
Grafana Tempo
以及其他支持 OpenTelemetry / OTLP 的后端
```

因此本项目原则是：

```text
不自研 Trace UI
不自研 Timeline Dashboard
不自研查询平台

Agent Service 只负责产生标准 Telemetry
```

---

# 13. OpenTelemetry：把 Runtime 与观测平台解耦

当前新增：

```text
app/observability/tracing.py
```

`CodexRuntime` 为 Turn 创建 Span，例如：

```text
agent.turn
agent.turn.stream
```

并记录：

```text
agent.thread.id
agent.turn.id
agent.streaming
agent.turn.status
agent.turn.duration_ms
```

流式过程中还可以把：

```text
turn.started
tool.started
tool.completed
message.delta
turn.completed
```

加入 Span Event。

## 13.1 为什么选择 OpenTelemetry

如果直接在业务代码里写：

```python
langfuse.xxx(...)
```

那么 Agent Runtime 会直接依赖某个 Vendor。

现在：

```text
CodexRuntime
 ↓
OpenTelemetry
 ↓
OTLP
 ↓
Langfuse / Phoenix / Tempo / ...
```

以后换平台，Agent 核心代码基本不用改。

## 13.2 OTLP 配置

`.env.example`：

```text
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
```

留空：

```text
不发送远程 Trace
本地仍正常运行
```

配置后：

```text
Agent Service
→ OTLP
→ Observability Backend
```

部分平台还需要：

```text
OTEL_EXPORTER_OTLP_HEADERS=...
```

真实密钥不要提交到 Git。

---

# 14. Event / Streaming / Observability 三者的区别

这是本阶段最重要的一组概念：

```text
Event
= Agent 运行过程中发生了一件什么事

Streaming
= 如何把这些 Event / Delta 实时传出去

Observability
= 如何把运行数据记录、关联、查询、分析和告警
```

例如：

```text
Codex 产生：tool.started
        ↓
这是 Event
        ↓
通过 SSE 推到浏览器
        ↓
这是 Streaming
        ↓
同时记录到 OpenTelemetry Trace
        ↓
在 Langfuse / Phoenix / Tempo 里查询
        ↓
这是 Observability
```

---

# 15. 当前完整执行链

查询订单：

```text
用户
 ↓
FastAPI
 ↓
AgentService
 ↓
CodexRuntime
 ↓
Thread / Turn
 ↓
order-analysis Skill
 ↓
Agent 决定调用 get_order_status
 ↓
tool.started Event
 ↓
MCP
 ↓
Java Business System
 ↓
OrderService
 ↓
SHIPPED
 ↓
tool.completed Event
 ↓
message.delta × N
 ↓
turn.completed
```

取消订单：

```text
用户
 ↓
Skill
 ↓
Agent 决定调用 cancel_order
 ↓
Tool 配置 prompt
 ↓
Approval PENDING
 ↓
人工 approve / reject
 ↓
如果 approve：
MCP → Java → cancel_order
 ↓
Event / SSE / Trace
 ↓
最终回答
```

---

# 16. 为什么企业 Agent 需要 Harness

到现在已经可以看清 Harness 的价值。

如果只是：

```text
LLM + Prompt
```

很难稳定解决：

```text
会话生命周期
Tool 调用
Skill 发现
高风险审批
运行时事件
流式输出
Sandbox
上下文压缩
多实例恢复
可观测性
```

Harness / Agent Runtime 负责把这些能力组织起来。

业务开发者重点开发：

```text
Agent Definition
Prompt / Instructions
Skills
MCP Tools
Policy
Business Authorization
Evals
```

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
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

测试建议：

```text
1. POST /api/v1/agents/threads
2. 保存 thread_id
3. 普通调用：POST /threads/{thread_id}/turns
4. 流式调用：POST /threads/{thread_id}/turns/stream
5. 写操作时配合 /api/v1/approvals API 完成审批
```

---

# 18. 与 Spring Boot 的对应关系

```text
Spring Boot                 FastAPI
--------------------------------------------------
@RestController       ->    APIRouter
@RequestBody          ->    Pydantic BaseModel
@Service              ->    普通 Service 类
@Configuration        ->    core/config.py
application.yml       ->    .env + Settings
Bean 注入             ->    Depends
启动/销毁生命周期     ->    lifespan
```

Runtime 分层：

```text
Controller / API
    ↓
AgentService
    ↓
CodexRuntime Adapter
    ↓
Official Codex SDK
    ↓
Codex Harness
```

Vendor Observability：

```text
CodexRuntime
    ↓
OpenTelemetry
    ↓
OTLP Backend
```

这样业务层不直接依赖 Codex 私有实现，也不直接绑定某个 Observability 平台。

---

# 19. 当前学习进度

已完成：

```text
Thread / Turn                 ✅
Skill                         ✅
MCP / Tool                    ✅
Approval / Human-in-the-loop  ✅
Event                         ✅
Streaming / SSE               ✅
OpenTelemetry Observability   ✅
```

当前阶段：

```text
Sandbox                       ← 进行中
```

后续：

```text
Context / Compaction
→ Thread persistence / resume
→ 多实例
→ Agent Gateway
```

---

# 20. 最终记忆版

如果以后忘记细节，只记住这张图：

```text
                         Agent Runtime / Harness
                                  │
      ┌───────────┬───────────────┼───────────────┬───────────────┐
      │           │               │               │               │
    Skill       MCP Tool       Approval         Event          Sandbox
   怎么做       能做什么        能不能做        做到哪了        能碰哪里
      │           │               │               │               │
      └───────────┴───────────────┼───────────────┴───────────────┘
                                  ↓
                           Business System
                                  ↓
                         Final Authorization
                                  ↓
                           Real Business

Event
 ↓
├── SSE → Browser
└── OpenTelemetry → Langfuse / Phoenix / Tempo
```

这就是当前项目逐步构建企业 Agent Service 的核心路线。

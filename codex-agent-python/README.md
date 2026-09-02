# Codex Agent Python

这是一个标准的 FastAPI Agent Service 示例，用来演示：

> 已有 Java / Spring Boot 业务系统时，如何使用 Python + FastAPI + 官方 OpenAI Codex Python SDK 开发独立 Agent Service，再通过 MCP 调用 Java 业务能力，并通过 Skill 约束 Agent 行为、通过 Approval 控制高风险操作。

这个项目当前重点不是做一个“聊天机器人”，而是学习一个更接近企业生产环境的 Agent Runtime：

```text
用户请求
  ↓
Thread / Turn
  ↓
Skill：告诉 Agent 应该怎么做
  ↓
MCP Tool：告诉 Agent 能做什么
  ↓
Approval：决定高风险动作是否允许执行
  ↓
Java Business System
  ↓
真实业务 Service
```

---

## 目录结构

```text
codex-agent-python/
├── app/
│   ├── main.py                  # FastAPI 应用入口
│   ├── api/
│   │   ├── deps.py              # FastAPI Depends 依赖注入
│   │   └── v1/
│   │       ├── router.py        # V1 总路由
│   │       ├── health.py        # 健康检查
│   │       ├── agent.py         # Agent HTTP API
│   │       └── approval.py      # Approval HTTP API
│   ├── approval/
│   │   ├── approval_service.py  # Codex Approval 与业务审批 API 的桥接层
│   │   └── approval_store.py    # 学习用内存 Approval Center
│   ├── core/
│   │   ├── config.py            # 环境变量 / 配置
│   │   └── lifespan.py          # 应用启动与关闭生命周期
│   ├── runtime/
│   │   └── codex_runtime.py     # Codex SDK 适配层 + MCP + Approval 配置
│   ├── services/
│   │   └── agent_service.py     # Agent 应用服务
│   └── schemas/
│       ├── agent.py             # Agent 请求 / 响应模型
│       └── approval.py          # Approval 请求 / 响应模型
├── .agents/
│   └── skills/
│       └── order-analysis/
│           └── SKILL.md
├── docs/
│   └── approval.md
├── tests/
├── .env.example
├── pyproject.toml
├── Dockerfile
└── README.md
```

---

# 一、当前整体架构

```text
Web / Business Client
        |
        | HTTP
        v
FastAPI Agent Service
        |
        v
AgentService
        |
        v
CodexRuntime
        |
        v
官方 openai-codex Python SDK
        |
        v
Codex Runtime / Harness
        |
        +---------------- Skill
        |
        +---------------- MCP Client
        |                    |
        |                    v
        |            Java Business System
        |                    |
        |                    v
        |               MCP Adapter
        |                    |
        |                    v
        |             Business Service
        |
        +---------------- Approval
                             |
                             v
                     ApprovalService
                             |
                             v
                      ApprovalStore
                             |
                       人工同意 / 拒绝
```

Java `hanress-test` 模块扮演已有业务系统，并通过：

```text
http://127.0.0.1:8080/mcp
```

暴露订单 MCP Server。

当前订单 Tool：

```text
get_order_status
→ 查询型 Tool
→ 自动允许执行

cancel_order
→ 写操作 Tool
→ approval_mode = prompt
→ 必须进入 Approval
```

---

# 二、先记住三个核心概念

如果以后忘记整个项目，只需要先记住下面三句话：

```text
Skill
= Agent 应该怎么做

MCP Tool
= Agent 能做什么

Approval
= Agent 想做高风险动作时，谁决定能不能做
```

三者不是替代关系，而是互相配合。

例如用户说：

```text
“帮我看看订单1001现在什么情况，如果可以的话帮我取消。”
```

完整执行可能是：

```text
用户请求
   ↓
Skill 告诉 Agent：
先识别订单 ID，不要猜实时状态，优先查询真实 Tool
   ↓
Agent 调 get_order_status
   ↓
MCP → Java
   ↓
返回 SHIPPED
   ↓
Agent 判断下一步需要 cancel_order
   ↓
cancel_order 是写操作，approval_mode=prompt
   ↓
产生 Approval
   ↓
人工同意
   ↓
MCP → Java cancel_order
   ↓
订单变为 CANCELLED
```

这就是 Skill + MCP + Approval 的完整协作方式。

---

# 三、Skill：Agent 应该怎么做

## 3.1 Skill 是什么

Skill 可以理解成给 Agent 的 SOP、操作规范、领域方法论。

它不是 Java / Python 函数，也不是业务 API。

Skill 主要解决：

```text
面对某类任务时：
- 应该先做什么？
- 哪些信息必须确认？
- 哪些事情不能猜？
- 应该优先调用哪些 Tool？
- 最终答案应该怎样组织？
```

当前项目 Skill：

```text
.agents/skills/order-analysis/SKILL.md
```

核心规则包括：

```text
1. 先识别订单 ID
2. 不允许猜测实时订单状态
3. 已接入订单 MCP Tool 时优先查询真实业务数据
4. 区分事实数据和分析结论
5. 用中文给出明确结果
```

## 3.2 Skill 与 Prompt 的区别

可以简单理解为：

```text
Prompt
→ 某次调用或某个 Agent 的具体提示

Skill
→ 可发现、可复用的任务能力 / SOP
```

Skill 更适合沉淀：

```text
订单分析规范
合同审查规范
退款处理规范
财务对账规范
客服升级规则
```

## 3.3 Skill 是如何被 Codex 发现的

环境变量：

```text
AGENT_WORKSPACE=.
```

创建 Thread 时，Codex Runtime 会使用 workspace 作为 `cwd`。

当前代码会让 Codex 在：

```text
<workspace>/.agents/skills
```

发现项目级 Skill。

因此这里不是 Java / Python 手动：

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
根据任务自动选择
```

## 3.4 Skill 不是什么

Skill 不负责直接查询数据库，也不应该自己偷偷实现业务逻辑。

例如：

```text
错误：
Skill 里写死订单1001是 SHIPPED

正确：
Skill 要求 Agent 不能猜状态，必须调用真实订单 Tool
```

因此：

```text
Skill = How
Tool = Action
```

---

# 四、MCP / Tool：Agent 能做什么

## 4.1 MCP 在这个项目里的角色

MCP 可以理解成 Agent Runtime 与外部能力之间的标准连接协议。

当前不是 Python 自己直接：

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
Java Business Service
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

## 4.2 当前 Java MCP Tool

Java 业务系统目前暴露：

```text
get_order_status(orderId)
cancel_order(orderId)
```

建议真实企业项目采用：

```text
Business Service
    ↑
Agent MCP Adapter
```

而不是把所有 Service 方法全部暴露给 Agent。

更推荐语义明确的 Tool：

```text
get_order_status
cancel_order
request_refund
create_invoice_draft
submit_contract_review
```

而不是暴露：

```text
updateTable
executeSql
genericCrud
```

Tool 的设计应该体现真实业务动作和治理边界。

## 4.3 CodexRuntime 如何连接 Java MCP

环境变量：

```text
ORDER_MCP_URL=http://127.0.0.1:8080/mcp
```

当前 `CodexRuntime` 通过 `CodexConfig.config_overrides` 注入：

```text
mcp_servers.order.url=<ORDER_MCP_URL>
mcp_servers.order.enabled_tools=["get_order_status","cancel_order"]
mcp_servers.order.default_tools_approval_mode="approve"
mcp_servers.order.tools.get_order_status.approval_mode="approve"
mcp_servers.order.tools.cancel_order.approval_mode="prompt"
```

其中：

```text
get_order_status = approve
```

表示查询 Tool 不需要人工审批。

```text
cancel_order = prompt
```

表示调用前必须产生 Approval。

## 4.4 Tool 与业务权限不是一回事

即使 Codex 允许执行 Tool，Java 业务系统仍然必须自己检查：

```text
用户是谁？
属于哪个 tenant？
有没有取消订单权限？
订单是不是属于当前用户？
订单当前状态还能不能取消？
金额是否超过阈值？
```

所以：

```text
Codex Approval
≠
业务系统 Authorization
```

企业系统中通常两层都需要。

---

# 五、Approval：高风险动作谁来决定

## 5.1 为什么 Agent 特别需要 Approval

传统业务系统通常是：

```text
用户点击按钮
→ Controller
→ Service
→ DB
```

执行路径比较确定。

Agent 系统则可能是：

```text
用户说一句自然语言
→ Agent 自己判断下一步
→ Agent 决定调用 Tool
→ Tool 修改真实业务数据
```

中间出现了模型自主决策，因此企业一般不能让所有写操作直接执行。

所以需要：

```text
Permission / Policy
Approval
Business Authorization
Audit
Sandbox
```

## 5.2 Approval 相关的三个概念

这是当前代码最重要的知识点之一：

```text
1. approval_policy
   → 是否允许产生审批请求 / 什么情况下需要审批

2. approvals_reviewer
   → 审批发生以后交给谁审

3. approval_handler
   → 如果交给用户审，宿主程序具体怎么接住审批请求
```

不要把它们理解成同一个东西。

---

# 六、ApprovalMode 与 ApprovalsReviewer.user

官方 Python 高层 SDK 当前主要暴露：

```python
ApprovalMode.deny_all
ApprovalMode.auto_review
```

其中：

```text
ApprovalMode.auto_review
```

大致会映射为：

```text
approval_policy = on-request
approvals_reviewer = auto_review
```

含义是：

```text
需要审批时
→ 可以产生审批
→ 交给 Codex 自动 reviewer 判断
```

但企业 Human-in-the-loop 需要的是：

```text
需要审批时
→ 交给真实用户 / 管理员
```

底层协议已经支持：

```python
ApprovalsReviewer.user
```

因此当前项目创建 Thread 时使用：

```python
params = ThreadStartParams(
    approval_policy=AskForApproval(
        root=AskForApprovalValue.on_request
    ),
    approvals_reviewer=ApprovalsReviewer.user,
    cwd=str(self._workspace),
)
```

可以理解成：

```text
approval_policy = on_request
→ 允许需要审批的动作提出 Approval

approvals_reviewer = user
→ Approval 不交给自动 reviewer
→ 交回宿主应用处理
```

这里的 `user` 不是指 OpenAI 自动弹出某个网页。

更准确地说是：

```text
把审批交给 App Server Client / 宿主应用
```

在当前项目中，宿主应用就是：

```text
FastAPI Agent Service
```

---

# 七、approval_handler 是什么

`ApprovalsReviewer.user` 只表示：

```text
这个审批由用户侧处理
```

但 Python 程序还需要一个入口真正接住 App Server 发来的 Server Request。

这就是：

```text
approval_handler
```

当前 `lifespan.py` 创建：

```text
ApprovalStore
   ↓
ApprovalService
   ↓
CodexRuntime
```

并把：

```python
approval_service.handle_codex_request
```

传给 `CodexRuntime`。

当前官方 `AsyncCodex` 高层构造器暂时没有直接暴露 `approval_handler`，所以 Runtime 内部做了一层 SDK Adapter：

```python
self._codex._client._sync._approval_handler = approval_handler
```

这属于内部 SDK 适配代码，因此只放在：

```text
app/runtime/codex_runtime.py
```

业务 API / Service 不直接依赖这些私有字段。

未来如果官方 SDK 直接支持：

```python
AsyncCodex(
    config=config,
    approval_handler=approval_handler,
)
```

只需要修改 `CodexRuntime`，其他业务代码不用改。

---

# 八、一次 cancel_order Approval 的完整流程

用户：

```text
“取消订单1001”
```

完整链路：

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
Codex Harness
 ↓
模型决定调用 cancel_order
 ↓
cancel_order approval_mode=prompt
 ↓
需要审批
 ↓
Thread approval_policy=on_request
 ↓
允许发起 Approval
 ↓
approvals_reviewer=user
 ↓
App Server 向 Client 发送 Server Request
 ↓
mcpServer/elicitation/request
 ↓
approval_handler
 ↓
ApprovalService.handle_codex_request()
 ↓
确认 codex_approval_kind=mcp_tool_call
 ↓
ApprovalStore.create()
 ↓
status=PENDING
 ↓
等待人工决定
```

当前 `ApprovalStore` 使用 `threading.Event`：

```text
Codex SDK reader thread
→ wait_for_decision()
→ 暂停等待
```

FastAPI 自己的 event loop 没有被阻塞，所以仍然可以访问：

```http
GET /api/v1/approvals
```

查看待审批记录。

批准：

```http
POST /api/v1/approvals/{approval_id}/approve
```

拒绝：

```http
POST /api/v1/approvals/{approval_id}/reject
```

批准以后：

```text
ApprovalStore
PENDING → APPROVED
 ↓
threading.Event.set()
 ↓
唤醒 approval_handler
 ↓
返回：
{"action":"accept","content":{}}
 ↓
Codex Harness
 ↓
真正执行 cancel_order
 ↓
Java MCP
 ↓
OrderService
```

拒绝则返回：

```json
{
  "action": "decline",
  "content": null
}
```

于是 Tool 不会执行。

---

# 九、Skill + MCP + Approval 的关系

可以用下面这张图统一理解：

```text
                 用户任务
                    ↓
               Codex Harness
                    ↓
        ┌──────── Skill ────────┐
        │  告诉 Agent 怎么做     │
        └──────────┬────────────┘
                   ↓
            Agent 决定下一步
                   ↓
        ┌──────── MCP Tool ─────┐
        │   告诉 Agent 能做什么  │
        └──────────┬────────────┘
                   ↓
          Tool 是否需要审批？
             ┌─────┴─────┐
             │           │
            否           是
             │           │
             │       Approval
             │       人工决策
             │           │
             └─────┬─────┘
                   ↓
              Java Business
                   ↓
              Business Service
```

一句话记忆：

```text
Skill = How
MCP Tool = Capability
Approval = Control
Business Authorization = Final business security boundary
```

---

# 十、Thread / Turn

Thread 可以理解成一个持续存在的 Agent 会话。

Turn 是 Thread 中的一轮完整执行：

```text
用户输入
→ 模型推理
→ Skill
→ Tool
→ Approval
→ Tool Result
→ 最终回答
```

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

执行 Turn：

```http
POST /api/v1/agents/threads/{thread_id}/turns
Content-Type: application/json

{
  "message": "订单1001现在是什么状态？"
}
```

同一个 Thread 可以连续运行很多 Turn，并复用上下文。

---

# 十一、为什么使用 AsyncCodex

FastAPI 是异步 Web 框架，因此当前使用官方 SDK 的 `AsyncCodex`。

FastAPI 启动时创建一份 Runtime：

```text
FastAPI startup
      ↓
ApprovalStore / ApprovalService
      ↓
CodexRuntime
      ↓
AsyncCodex start
      ↓
整个应用生命周期复用
      ↓
FastAPI shutdown
      ↓
AsyncCodex close
```

不是每个 HTTP 请求重新启动 Codex Runtime。

---

# 十二、本地 / Codespaces 联调

先启动 Java：

```bash
cd hanress-test
mvn spring-boot:run
```

MCP 地址：

```text
http://127.0.0.1:8080/mcp
```

再启动 Python：

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

查询测试：

```text
1. POST /api/v1/agents/threads
2. 保存 thread_id
3. POST /api/v1/agents/threads/{thread_id}/turns
4. 输入：请查询订单1001的真实状态
```

Approval 测试：

```text
1. 在 Turn 中输入：请取消订单1001
2. 原 Turn 会等待 Approval
3. GET /api/v1/approvals
4. 找到 PENDING approval_id
5. POST /api/v1/approvals/{approval_id}/approve
   或
   POST /api/v1/approvals/{approval_id}/reject
6. 原 Turn 继续执行并返回最终结果
```

---

# 十三、与 Spring Boot 的对应关系

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

当前 Runtime 分层可以理解为：

```text
Controller / API
    ↓
AgentService
    ↓
CodexRuntime Adapter
    ↓
Official Codex SDK
```

这样未来即使替换 Agent Runtime，也不需要让业务层直接依赖 Codex 私有实现。

---

# 十四、当前 Approval 实现为什么只是学习版

当前：

```text
ApprovalStore = 内存
```

适合学习：

```text
Turn 暂停
→ PENDING
→ approve / reject
→ Turn 恢复
```

但生产环境不能只使用内存，因为：

```text
Agent Service 重启会丢数据
多个实例无法共享审批状态
无法做完整审计
无法支持超时、转交、审批人、组织权限
```

生产版本通常演进成：

```text
Approval Center
├── DB / Redis
├── approval_request
├── applicant
├── approver
├── tenant_id
├── risk_level
├── tool_name
├── tool_arguments
├── PENDING / APPROVED / REJECTED / EXPIRED
├── timeout
├── audit log
└── message / event notification
```

而 Java 业务系统仍然保留最终 RBAC / ABAC / Tenant / Business Rule 校验。

---

# 十五、当前学习进度

已经完成：

```text
Thread / Turn                 ✅
Skill                         ✅
MCP / Tool                    ✅
Approval / Human-in-the-loop  ✅
```

下一阶段：

```text
Event / Streaming / Observability
```

目标是能够看到 Agent 一轮 Turn 内真正发生了什么：

```text
turn started
skill used
tool started
approval requested
approval resolved
tool completed
agent message delta
turn completed
```

再往后继续：

```text
Sandbox
→ Context / Compaction
→ Thread persistence / resume
→ 多实例
→ Agent Gateway
```

---

# 十六、最后的核心心智模型

不要把企业 Agent 理解成：

```text
LLM + Prompt
```

更准确的理解是：

```text
                  Agent Runtime / Harness
                           │
          ┌────────────────┼────────────────┐
          │                │                │
        Skill             Tool           Approval
      怎么做             能做什么          能不能做
          │                │                │
          └────────────────┼────────────────┘
                           ↓
                    Business System
                           ↓
                  Final Authorization
                           ↓
                     Real Business
```

这也是当前项目继续演进成企业级 Agent Service 的基础。

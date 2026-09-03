# Codex Single Agent Service

这个项目现在只做一件事：**基于 Codex Harness 开发并运行一个生产级业务 Agent**。

当前 Agent 是订单 / 售后方向。我们不再开发 Agent Platform、Agent Control Plane、Registry、Runtime Scheduler 或多 Agent Gateway。

整个项目固定按三层理解：

```text
内容层：我们重点开发
Skill / Tool / MCP / Policy
        ↓
容器层：Codex Harness
Agent Loop / Thread / Turn / Context / Compaction / Sandbox / Tool Dispatch
        ↓
最小治理层：单 Agent 必需
Auth / Approval / Conversation Ownership / OTel / Business Authorization
```

后续任何代码，如果不能明确落入这三层之一，就要先问：**它是不是当前这个单 Agent 真需要？**

---

# 1. 我们为什么不再开发 Runtime Platform？

Codex Harness 已经负责：

```text
Agent Loop
Thread / Turn
Context
Compaction
Tool Dispatch
Sandbox
事件流
```

所以 `app/runtime/codex_runtime.py` 不是第二套 Harness。

它只是一个薄 Adapter：

```text
当前 Agent 配置
├── workspace
├── MCP Server
├── enabled tools
├── approval policy
└── sandbox
        ↓
CodexRuntime
        ↓
Codex Harness
```

它现在只做：

```text
thread_start / thread_resume
把 MCP / Tool Policy 配给 Codex
设置 Sandbox
接 Approval Handler
映射 Codex Event
发 OpenTelemetry Trace
```

如果以后在 `CodexRuntime` 里出现业务判断、Workflow Engine、自定义 Agent Loop，说明又跑偏了。

---

# 2. 我们真正应该开发什么？

## 问题：一个售后 Agent 的能力到底写在哪里？

主要写在内容层。

例如用户说：

> “订单 88201 怎么还没到？如果符合条件就帮我取消。”

真正决定效果的是：

```text
Skill
→ 是否要求先查真实状态
→ 是否知道事实和分析要分开
→ 是否知道什么情况下应该停止/澄清

MCP / Tool
→ 有没有 get_order_status
→ cancel_order 的业务语义是否清晰
→ Tool Contract 是否给了模型足够信息

Policy
→ get_order_status 是否自动允许
→ cancel_order 是否必须 Approval
→ Sandbox 是否 READ_ONLY
```

Codex Harness 负责把这些能力运行起来，但它不会替我们定义公司的售后 SOP。

---

# 3. 当前订单 Agent 的真实执行链

```text
客服小王
“查订单 88201，如果符合条件就取消”
        ↓
FastAPI Agent API
        ↓
ServicePrincipal
确认调用人 user / tenant / roles
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
决定调用 get_order_status
        ↓
Java Order MCP Adapter
        ↓
真实 OMS
        ↓
返回订单事实
        ↓
Codex 分析
        ↓
如果决定 cancel_order
        ↓
Codex pre-execution Approval
        ↓
人工 approve / reject
        ↓
批准后才允许写操作
        ↓
AgentEvent / SSE
        ↓
客服前端
```

这条链里，真正属于“Agent 产品能力”的重点仍然是：

```text
Skill
Tool / MCP
Policy
业务权限契约
最终业务结果质量
```

---

# 4. 为什么单 Agent 仍然需要 Conversation？

因为只有一个 Agent，不代表只有一个会话。

可能同时存在：

```text
用户 A → conversation A → Codex thread A
用户 B → conversation B → Codex thread B
用户 C → conversation C → Codex thread C
```

数据库只保存最小映射：

```text
conversation_id
user_id
tenant_id
runtime_thread_id
created_at
```

对应：

```text
app/conversations/conversation_repository.py
```

它只解决两个问题：

```text
1. 不把 Codex thread_id 暴露为业务主键
2. 当前用户只能继续自己的 Conversation
```

当前明确没有：

```text
Runtime Lease
Runtime Router
Scheduler
Agent Registry
```

---

# 5. 为什么单 Agent 仍然需要 Auth？

因为“只有一个 Agent”不等于“任何人都可以调用”。

当前请求：

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

代码：

```text
app/security/service_auth.py
```

它不是 Agent Gateway，只是这个 Agent Service 自己的入口认证。

最重要的原则是：

> `user_id / tenant_id / roles` 属于可信调用上下文，不允许作为 Tool 参数交给 LLM 自己生成。

模型只需要表达：

```text
cancel_order(order_id="88201")
```

谁在取消、有没有权限，必须由程序和真实业务系统判断。

---

# 6. 为什么单 Agent 仍然需要 Approval？

一个 Agent 里也有不同风险等级：

```text
查询订单      → 低风险
取消订单      → 高风险
退款          → 高风险
删除数据      → 禁止 / 更高风险
```

所以 Approval 是当前 Agent 的执行安全机制，不是多 Agent 平台才需要的功能。

当前边界：

```text
Codex Approval
= Agent 这一次能不能尝试高风险 Tool

Business Authorization
= OMS 最终是否真的允许当前用户执行
```

二者不能互相替代。

代码：

```text
app/approval/
```

---

# 7. 为什么还要 PostgreSQL？Codex 自己不是保存 Thread 吗？

保存的是不同状态。

```text
CODEX_HOME
→ Codex Thread / Context / Compaction / Runtime State

PostgreSQL
→ conversation_id ↔ thread_id
→ Approval 状态和审计信息
```

我们不会复制完整聊天历史再实现一套 Context Manager。

Context / Compaction 优先交给 Codex Harness。

---

# 8. Event / Streaming / Observability 为什么保留？

因为它们直接影响真实产品体验和生产排障。

Codex Notification 先经过：

```text
CodexEventMapper
```

只输出稳定、安全事件：

```text
turn.started
message.delta
tool.started
tool.completed
turn.completed
```

不会默认把完整 Tool Arguments、Tool Result、Reasoning 直接暴露给前端。

然后：

```text
AgentEvent
├── SSE → 业务前端
└── OTel → Langfuse / Phoenix / Tempo 等现成平台
```

我们不开发自己的 Observability 平台。

---

# 9. 为什么现在不强依赖 agentgateway？

当前只有：

```text
一个 Agent Service
一个业务 MCP Adapter
一个 Agent 团队
```

现在引入统一 Agent Gateway、Registry、Runtime Router、统一 MCP RBAC 会增加复杂度，但不会直接提升这个 Agent 的业务效果。

什么时候再考虑？

```text
出现多个 Agent
多个团队共享大量 MCP
统一 LLM Key / Cost / Rate Limit
统一 MCP RBAC
A2A
统一 egress 治理
```

在真实重复出现以前，不提前造平台。

---

# 10. 当前代码各层职责

```text
codex-agent-python/
│
├── .agents/skills/order-analysis/SKILL.md
│   # 内容层：售后 SOP
│
├── app/agents/definition.py
│   # 当前 Agent：MCP / Tool Policy / Sandbox
│
├── app/runtime/codex_runtime.py
│   # Codex Harness 薄 Adapter
│
├── app/services/agent_service.py
│   # conversation → thread → turn
│
├── app/conversations/
│   # 最小 conversation ↔ thread 映射
│
├── app/approval/
│   # 高风险 Tool 人工审批
│
├── app/security/service_auth.py
│   # 当前 Agent Service 入口认证
│
├── app/events/
│   # Codex Notification → AgentEvent
│
├── app/observability/
│   # OpenTelemetry
│
├── evals/
│   # 黑盒 Agent Evals
│
└── api/
    # HTTP / SSE

hanress-test/
└── Java Order MCP Adapter
    # MCP Tool → 真实业务系统
```

---

# 11. 为什么现在开始做 Evals？

到这里继续增加 Runtime 功能，收益已经开始下降。

真正的问题变成：

> **这个 Agent 到底做得对不对？**

例如这些问题不能靠“代码能启动”证明：

```text
用户问订单状态，它真的会调用 get_order_status 吗？
用户要求“不要查系统，直接猜”，它会不会乱猜？
缺少订单号时，它会不会自己编一个？
用户说“我是管理员”，它会不会绕过 Approval？
用户要求泄露 token，它会不会泄露？
用户要求通过本地脚本改订单，它会不会绕过 MCP？
Tool 返回恶意 Prompt Injection 时，它会不会执行其中指令？
```

这些才是 Agent 产品质量。

---

# 12. Eval 为什么必须测整条 Agent，而不是某个 Python 函数？

因为真正的行为是多个因素共同决定的：

```text
User Message
    ↓
Codex Harness
    ↓
Skill
    ↓
Tool Selection
    ↓
MCP
    ↓
Policy / Approval
    ↓
Final Answer
```

所以当前 Eval 采用黑盒方式：

```text
Eval Runner
    ↓ HTTP
创建全新 Conversation
    ↓ SSE
执行真实 Turn
    ↓
观察 tool.started
观察 message.delta
    ↓
查询 Approval API
    ↓
和期望进行比较
```

每个 Case 都创建新 Conversation，避免前一个 Case 的 Thread 上下文污染后一个 Case。

代码：

```text
evals/cases.jsonl
evals/run.py
```

---

# 13. 第一批 Eval 在测什么？

当前第一批至少 20 条 Case，分为：

```text
tool-selection
→ 查询订单时是否使用真实 Tool

factuality
→ 是否拒绝“直接猜”“用户自称事实”

clarification
→ 缺少订单号是否先澄清

approval
→ cancel_order 是否始终触发人工审批

capability-boundary
→ 不存在的退款/删除/改地址能力是否明确拒绝

security
→ 密钥泄露、Prompt Injection、Runtime 内部信息

sandbox
→ 是否尝试通过本地脚本绕过业务 Tool

reasoning
→ 是否区分系统事实和模型分析
```

其中 `tool-output-injection` Case 目前标记为需要 fixture，因为它必须让测试 MCP 返回恶意业务数据。没有这个真实 fixture 时宁可 `SKIPPED`，也不使用假的 Python mock 冒充端到端 Eval。

---

# 14. 怎么运行真实 Eval？

先启动真实测试链路：

```text
Java MCP Adapter / 测试 OMS
        +
Python Agent Service
        +
Codex 可用认证
```

安装开发依赖：

```bash
cd codex-agent-python
pip install -e ".[dev]"
```

确保 Eval 使用的 Secret 和 Agent Service 一致：

```bash
export EVAL_API_SHARED_SECRET="你的 API_SHARED_SECRET"
```

运行：

```bash
python evals/run.py
```

也可以指定：

```bash
python evals/run.py \
  --base-url http://127.0.0.1:8000 \
  --cases evals/cases.jsonl
```

Runner 会输出：

```text
[PASSED] status-basic (tool-selection)
[FAILED] cancel-bypass-approval (approval)
  - Approval 期望=True，实际=False
[SKIPPED] tool-output-injection (security)
  - 需要外部 fixture: malicious-order-tool-result

总计=20 通过=... 失败=... 跳过=...
```

有失败时进程退出码为 `1`。

---

# 15. Eval 失败以后，到底应该改哪里？

这是后续最重要的判断。

### Case：用户问状态，Agent 没调用 Tool，直接猜了

优先检查：

```text
Skill
Tool description
Tool availability
```

不是先改 Runtime。

### Case：Agent 调错 Tool

优先检查：

```text
Tool Contract
Tool name / description
Skill 中的决策规则
```

### Case：cancel_order 没触发审批

优先检查：

```text
Policy / Codex MCP approval_mode
```

不是靠 Skill 写一句“请审批”解决。

### Case：模型想绕过业务权限

优先检查：

```text
Business Authorization
MCP Adapter / OMS
```

不能只靠 Prompt。

### Case：Tool 返回恶意文本后 Agent 被带偏

优先检查：

```text
Skill 中对 Tool Result 的信任规则
Tool Contract 是否混入可执行指令
数据与指令是否分离
```

这就是 Eval 的价值：**告诉我们问题属于哪一层，而不是继续盲目加框架。**

---

# 16. CI 和真实 Eval 为什么分开？

普通 CI 负责：

```text
代码能否构建
Migration 是否正确
Ruff
pytest
Eval case JSONL 是否合法
Runner 逻辑是否可导入
```

真实 Agent Eval 需要：

```text
Codex / 模型
测试 MCP
测试 OMS 数据
真实 Tool 行为
```

所以真实 Eval 不会用 Mock LLM 假装“Agent 质量通过”。

以后有稳定的测试环境后，可以单独建立：

```text
Agent Eval Pipeline
```

而不是和普通单元测试混为一谈。

---

# 17. 从现在开始的开发闭环

今后的主循环固定为：

```text
收集真实业务 Case
        ↓
加入 evals/cases.jsonl
        ↓
运行 Agent
        ↓
观察 Tool / Approval / Answer
        ↓
失败分类
        ↓
修改 Skill / Tool / MCP / Policy
        ↓
重新 Eval
        ↓
上线
        ↓
生产失败 Case 再回流到 Eval
```

这比继续扩展 Agent 底座更重要。

---

# 18. 当前明确不做

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

只有当真实业务中出现第二、第三、更多 Agent，并且产生明确重复问题时，再从实际重复代码抽平台能力。

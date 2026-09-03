# Codex Single Agent Project

这个仓库现在只做 **一个生产级业务 Agent**。

核心边界固定为：

```text
内容层
Skill / Tool / MCP / Policy
        ↓
容器层
Codex Harness
Agent Loop / Thread / Turn / Context / Compaction / Sandbox
        ↓
最小治理层
Auth / Approval / Audit / OTel / Business Authorization
```

不再把目标设成 Agent Platform、Agent Control Plane、Agent Registry、Runtime Scheduler 或多 Runtime Router。

## 运行链路

```text
Business System
      ↓
codex-agent-python
Single Agent Service
      ↓
Codex Harness
      ↓
Skill + MCP + Tool Policy
      ↓
hanress-test
Order MCP Adapter
      ↓
Real OMS / Business System
```

## `codex-agent-python/`

负责当前唯一 Agent 的：

```text
AgentDefinition
Skill workspace
MCP / Tool Policy
Codex Thread / Turn / Resume
Conversation → Codex Thread 映射
Approval
Sandbox
Event / SSE
OpenTelemetry
Context / Compaction 运维入口
API Auth
```

它不是新的 Harness。Agent Loop、Context 管理、Compaction、Tool Dispatch 等容器能力继续交给 Codex Harness。

详细的“为什么这样开发、代码怎么解决”见 `codex-agent-python/README.md`。

## 如果以后开发第二个 Agent，哪些可以直接复用？

例如现在是订单 / 售后 Agent，以后再开发合同 Agent、财务 Agent 或客服 Agent，下面这些工程能力原则上可以直接复用：

```text
FastAPI Service 结构
app/runtime/codex_runtime.py
Conversation → Codex Thread 映射
Service Auth
Approval Framework
Codex Event Mapper
SSE API
OpenTelemetry
Dockerfile / 部署骨架
PostgreSQL 基础能力
Eval Runner
```

其中最核心的是：

```text
CodexRuntime
= 把当前 Agent 的 MCP / Tool Policy / Sandbox 接到 Codex Harness

Conversation
= 业务 conversation_id ↔ Codex thread_id

Approval / Auth / Event / OTel
= 单 Agent 的最小生产治理
```

这些能力和“订单”本身没有强业务绑定，所以第二个 Agent 不应该重新实现一遍。

## 第二个 Agent 必须自己开发什么？

真正需要重新开发的是内容层和对应的业务能力：

```text
Skill
MCP / Tool
Tool Contract
Tool Policy
Sandbox Policy
业务授权契约
Eval Cases
```

例如：

```text
订单 Agent
├── Skill: order-analysis
├── Tool: get_order_status / cancel_order
└── Policy: cancel_order → approval

合同 Agent
├── Skill: contract-review
├── Tool: get_contract / search_clause / submit_review
└── Policy: submit_review → approval
```

所以以后开发第二个 Agent 的正确方式不是复制整套 Runtime，而是：

```text
复用工程壳
        +
重新开发 Skill / MCP / Tool / Policy / Eval
```

如果未来多个 Agent 真的产生大量重复代码，再从真实重复中抽共享库或平台能力；现在不提前做 Agent Platform。

## 单 Agent 很多人使用时，怎么扩容？

一个 Agent 可以同时服务很多用户：

```text
用户 A → conversation A → Codex thread A
用户 B → conversation B → Codex thread B
用户 C → conversation C → Codex thread C
```

“单 Agent”表示只有一种 Agent 能力定义，不表示只能有一个用户或一个 Thread。

### 术语 1：Thread

可以理解成“一个用户的一本独立聊天记录”。

所以：

```text
一个售后 Agent
可以有很多 Thread
```

不同用户的上下文互不混淆。

### 第一阶段：只有一个 Runtime 时

当前就是：

```text
用户
 ↓
Agent API
 ↓
PostgreSQL
conversation_id → runtime_thread_id
 ↓
当前唯一 Codex Runtime
 ↓
thread_resume(thread_id)
```

这时候不需要 `runtime_slot`。

一个 `AsyncCodex` 可以服务很多不同 Thread，但生产上必须设置并发上限，不能无限接收 Turn。

例如：

```text
最多同时运行 30 个 Turn
第 31 个以后短暂等待
队列也满了就返回“当前繁忙，请稍后再试”
```

术语：`Concurrency Limit`，就是“同时最多处理多少个请求”。

### 第二阶段：一个 Runtime 不够用了

假设一个 Runtime 最多稳定跑 30 个并发，但业务同时有 150 个活跃 Turn，就增加 Runtime：

```text
Runtime-0
Runtime-1
Runtime-2
Runtime-3
Runtime-4
```

术语：`Horizontal Scaling`，就是“不是把一台机器无限加大，而是多开几台一样的 Runtime”。

这时候数据库里的 Conversation 增加：

```text
runtime_slot
```

例如：

```text
conversation_id = conv-A
runtime_thread_id = thread-abc
runtime_slot = 2
```

`runtime_slot = 2` 的意思就是：

> 这个 Conversation 分配给 Runtime-2。

Agent API 收到下一条消息时：

```text
用户继续 conv-A
 ↓
Agent API
 ↓
查 PostgreSQL
 ↓
thread_id = abc
runtime_slot = 2
 ↓
把请求送到 Runtime-2
 ↓
Runtime-2 执行 thread_resume(abc)
```

所以扩容后的 Agent API 主要做：

```text
1. Auth：你是谁？
2. Conversation Ownership：这个会话是不是你的？
3. 查 PostgreSQL：thread_id + runtime_slot
4. 把请求送给正确 Runtime
5. 把 SSE 结果返回给前端
```

### 术语 2：Persistent Volume

每个 Runtime 都需要自己的持久化磁盘保存 `CODEX_HOME`。

可以理解成：

```text
Runtime-0 → 自己的永久文件柜
Runtime-1 → 自己的永久文件柜
Runtime-2 → 自己的永久文件柜
```

如果 Runtime-2 进程挂了，重启后的 Runtime-2 重新挂载原来的磁盘，就还能继续恢复以前的 Thread。

不要让多个 Runtime 同时写同一个 `CODEX_HOME`。

### 术语 3：Redis Lock

同一个 Conversation 同一时间不要执行两个 Turn。

例如用户连续点两次：

```text
“取消订单 1001”
“取消订单 1001”
```

需要保证：

```text
conv-A 的 Turn-1 正在执行
→ Turn-2 先等待或直接返回“正在处理中”
```

但：

```text
conv-A
conv-B
conv-C
```

可以并行。

这类“同一 Conversation 串行、不同 Conversation 并行”的控制，可以用 Redis 分布式锁实现。

### 术语 4：Load Balancer

以后 Agent API 自身也可能有多台：

```text
API-1
API-2
API-3
```

前面放一个 Load Balancer，把用户请求分给不同 API 实例。

API 本身不保存 Codex Thread 状态，所以哪一台 API 接到请求都可以；真正的 Thread 会根据 PostgreSQL 里的 `runtime_slot` 被送到正确 Runtime。

### 最终扩容图

```text
                    用户
                     │
                     ▼
              Load Balancer
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
        API-1      API-2      API-3
                     │
                     ▼
                PostgreSQL
          conversation → thread
          conversation → runtime_slot
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
  Runtime-0       Runtime-1       Runtime-2
      │              │              │
 CODEX_HOME-0    CODEX_HOME-1    CODEX_HOME-2
      │              │              │
      └──────────── MCP ────────────┘
                     │
                     ▼
                 业务系统

Redis
→ 只负责同一 conversation 的并发锁、限流等短期状态
```

### 扩容顺序

```text
V1：现在
一个 Agent Service + 一个 AsyncCodex + PostgreSQL + 持久化 CODEX_HOME

V2：单 Runtime 真到瓶颈
API 和 Runtime 拆开 + 多 Runtime + runtime_slot + 每个 Runtime 独立持久盘 + Redis Lock

V3：业务再扩大
多 API、副本自动扩容、托管 PostgreSQL / Redis、OTel、告警、压测和容量规划
```

关键结论：

> **用户多，是单 Agent 的扩容问题；Agent 多，才是多 Agent 平台问题。**

## 为什么现在没有向量数据库和图数据库？

因为当前订单 Agent 的主要事实来自实时业务系统，而不是海量非结构化知识。

例如用户问：

> “订单 1001 到哪了？”

最正确的数据源是：

```text
get_order_status
→ OMS
```

而不是先去向量数据库搜索“订单 1001”。

所以当前 Agent 的核心知识来源是：

```text
Skill
→ 告诉 Agent 售后 SOP 和做事规则

MCP / Tool
→ 获取实时订单事实、执行真实业务动作

Codex Thread / Context
→ 保存当前会话上下文
```

这三个已经覆盖当前订单 Agent 的主要需求。

### 什么时候才需要向量数据库？

术语：`Vector Database`，向量数据库。

可以把它理解成：

> 当公司有很多文档，而用户的问题不适合精确 SQL 查询时，用“语义相似度”从大量文档里找最相关片段。

例如以后售后 Agent 要回答：

```text
“这款产品进水后还保修吗？”
“海外订单的退货期限是多少？”
“去年双十一活动购买的商品适用哪个售后规则？”
```

公司可能有：

```text
5000 页售后政策
产品说明书
活动规则
FAQ
内部 SOP
```

这时候可以增加：

```text
文档
 ↓
切片 + Embedding
 ↓
Vector DB
 ↓
knowledge_search Tool / MCP
 ↓
Codex
```

也就是说，向量数据库不是 Harness 必需组件，而是某个 Agent 出现“海量语义知识检索”需求时新增的一种 Tool 后端。

### 什么时候才需要图数据库？

术语：`Graph Database`，图数据库。

可以理解成：

> 当问题重点不是“哪段文字最像”，而是“实体之间有复杂关系，需要沿关系查询和推理”。

例如风控 Agent：

```text
用户 A
→ 使用手机号 X
→ 关联设备 D
→ 设备 D 又登录过用户 B
→ 用户 B 关联商户 M
→ 商户 M 已被标记高风险
```

这种问题很适合图数据库。

或者供应链 Agent：

```text
订单
→ 商品
→ 供应商
→ 工厂
→ 批次
→ 质检记录
→ 召回事件
```

如果经常问：

> “这个异常订单和哪些供应商、批次、历史事故有关？”

图数据库会比单纯向量检索更自然。

### Harness 和这些数据库是什么关系？

Codex Harness 不要求一定使用：

```text
Vector DB
Graph DB
Redis
Elasticsearch
```

Harness 负责的是：

```text
Agent 怎么思考和运行
Thread / Turn
Context
Tool Dispatch
Sandbox
Compaction
```

而外部数据库属于“Agent 能访问什么能力”。

通常通过 Tool / MCP 暴露：

```text
Codex Harness
      │
      ├── order_mcp → OMS
      ├── knowledge_mcp → Vector DB
      └── relation_mcp → Graph DB
```

所以不是“有了 Harness 就不需要向量数据库/图数据库”，而是：

> **Harness 不替代数据库；只有业务真的需要某类数据检索时，才把相应数据库通过 Tool/MCP 接给 Agent。**

## `hanress-test/`

当前只作为 **Order MCP Adapter**：

```text
MCP Tool
→ OrderService
→ OrderGateway
→ Real OMS
```

Java 不运行第二套 Codex Runtime，也不维护虚假订单状态。

## 当前明确不做

```text
Agent Registry
多 Agent Control Plane
Runtime Scheduler
Runtime Lease
Runtime Router
Agent Marketplace
统一 Agent Gateway
自研 Agent Loop
自研 Context Manager
自研 Observability Platform
```

等真正出现多个 Agent、多个团队、统一 MCP/LLM 治理等需求时，再从真实重复能力中抽平台层。

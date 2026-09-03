# Codex Single Agent Project

这个仓库只做 **一个基于 Codex Harness 的生产级业务 Agent**。当前示例是订单 / 售后 Agent。

> 当前状态：**已经形成生产级架构基线，但尚未完成全部生产就绪验证。**

详细生产审计见：`codex-agent-python/docs/PRODUCTION_READINESS.md`。

## 三层边界

```text
内容层：我们重点开发
Skill / Tool / MCP / Policy
        ↓
容器层：Codex Harness
Agent Loop / Thread / Turn / Context / Compaction / Sandbox / Tool Dispatch
        ↓
最小治理层：单 Agent 必需
Auth / Approval / Conversation / Event / OTel / Business Authorization
```

不重新实现 Agent Loop、Context Manager、Runtime Platform，也不因为用户多就提前开发 Agent Control Plane。

## 当前运行链路

```text
Business System / 客服前端
          ↓
     Agent Service
          ↓
     Codex Harness
          ↓
Skill + MCP + Tool Policy
          ↓
   Order MCP Adapter
          ↓
          OMS
```

`codex-agent-python/` 负责当前 Agent 的 Python Service、Codex Runtime Adapter、Conversation、Approval、Event/SSE、Auth、OTel 和 Evals；`hanress-test/` 当前只作为 Java Order MCP Adapter。

详细架构问答见：`codex-agent-python/README.md`。

## 如果以后开发第二个 Agent，哪些可以复用？

可以复用的工程壳：

```text
FastAPI Service 结构
CodexRuntime
Conversation → Codex Thread 映射
Service Auth
Approval Framework
Codex Event Mapper / SSE
OpenTelemetry
Docker / PostgreSQL 基础能力
LangSmith Eval Target / Evaluator 模式
```

第二个 Agent 必须重新开发的主要是：

```text
Skill
MCP / Tool
Tool Contract
Tool Policy
Sandbox Policy
业务授权契约
Eval Dataset / 业务评分标准
```

例如合同 Agent 不应该复制第二套 Codex Runtime，而是复用工程壳，重新开发 `contract-review Skill + Contract MCP + Contract Policy + Contract Evals`。

## 单 Agent 很多人使用时怎么扩容？

一个 Agent 可以有很多独立 Thread：

```text
用户 A → conversation A → thread A
用户 B → conversation B → thread B
用户 C → conversation C → thread C
```

当前 V1 只有一个 Runtime：

```text
用户
 ↓
Agent API
 ↓
PostgreSQL
conversation → thread_id
 ↓
唯一 Codex Runtime
```

此时不需要 `runtime_slot`。先通过并发限制保证一个 Runtime 不被无限请求拖垮。

只有单 Runtime 真到容量瓶颈时才进入 V2：

```text
Agent API
 ↓
PostgreSQL
conversation → thread_id + runtime_slot
 ↓
Runtime-0 / Runtime-1 / Runtime-2
 ↓
每个 Runtime 独立 CODEX_HOME 持久盘
```

`runtime_slot=2` 就表示这个 Conversation 以后送到 Runtime-2。

同时需要保证：

```text
同一 Conversation → 同时只执行一个 Turn
不同 Conversation → 可以并行
```

多实例后可以用 Redis Lock 或 PostgreSQL advisory lock 做这件事。

用户多是扩容问题；真正出现多个 Agent / 多团队 / 统一 MCP 治理时，才重新评估 Gateway / Registry / Control Plane。

## 为什么现在没有 Vector DB / Graph DB？

因为当前订单 Agent 的实时事实来自 OMS：

```text
“订单 1001 到哪了？”
→ get_order_status
→ OMS
```

不应该用向量数据库搜索实时订单状态。

以后如果 Agent 需要从几千份售后政策、说明书、FAQ 中按语义找知识，再增加：

```text
Knowledge MCP
→ RAG
→ Vector DB（例如 Milvus）
```

如果业务重点变成实体关系查询，例如用户—设备—银行卡—商户或订单—批次—供应商—质检事件，再考虑 Graph DB。

Codex Harness 不替代这些数据库；它只负责 Agent 怎么运行。数据库按业务需要通过 Tool / MCP 暴露给 Agent。

## Evals：正式接入 LangSmith

`cases.jsonl + run.py` 不再承担完整 Eval Platform 职责。现在正式结构是：

```text
人工 Golden / Seed
生产失败 Case
人工标注 Case
合成变体
        ↓
LangSmith Dataset（版本化题库）
        ↓
LangSmithAgentTarget
        ↓
真实 Codex Agent HTTP/SSE
        ↓
Tool / Approval / Answer
        ↓
Evaluators
        ↓
Experiment
```

当前 Evaluator 包括：

```text
tool_policy
→ Tool 是否选对

approval_policy
→ 风险动作是否正确触发 Approval

response_contract
→ 最低业务回答契约 / 敏感信息泄露

business_quality（可选 LLM Judge）
→ 事实性、边界、回答质量
```

详细使用说明见：`codex-agent-python/evals/README.md`。

核心原则：

> 能确定性判断的安全规则，不交给 LLM Judge；主观质量才使用 LLM-as-a-Judge。

LangSmith 负责 Dataset、版本、Experiment 和结果比较；Agent 仍然是 Codex Harness，不需要改成 LangChain Agent。

## 当前还不是完全生产就绪的地方

专家审计后的 P0 缺口是：

```text
1. 同 Conversation 串行锁
2. 全局 Agent Turn 并发限制 / 背压
3. cancel_order 等写 Tool 的端到端幂等
4. 每个 Tool 的 timeout / retry / degradation policy
5. 从 shared secret + trusted headers 升级到正式身份边界
6. Secret Manager / 密钥轮换
7. CODEX_HOME 持久卷 + crash recovery 实际演练
8. Java MCP Adapter CI 清零
```

P1 包括：

```text
LangSmith Eval 发布门禁
SLO / Alert / 成本指标
Graceful shutdown / draining
PostgreSQL backup / restore
SSE 断线与反向代理验证
PII / Trace 脱敏策略
```

多 Runtime + `runtime_slot` 属于容量真的达到瓶颈后的 P2，不提前实现。

完整原因、风险和处理方案见：`codex-agent-python/docs/PRODUCTION_READINESS.md`。

## 当前明确不做

```text
Agent Registry
多 Agent Control Plane
Runtime Scheduler
Agent Marketplace
统一 Agent Gateway
自研 Agent Loop
自研 Context Manager
自研 Observability Platform
```

我们的目标不是把一个 Agent 做成平台，而是把这个 Agent 的 Skill、Tool、Policy、Evals 和生产安全闭环真正做到可靠。

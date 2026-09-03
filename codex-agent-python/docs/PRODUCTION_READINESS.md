# 单 Agent 生产就绪审计

本文不是重新设计 Agent Platform，而是审视当前这个 **Codex 单 Agent** 距离真实生产上线还差什么。

结论先说：

> 当前项目已经形成生产级架构基线，但还不能称为完全生产就绪。下一阶段重点不是继续增加平台组件，而是补齐并发、幂等、安全、故障恢复、部署和真实 Eval 等上线闭环。

## 状态说明

```text
✅ 已具备：当前实现已经有明确代码承载
🟡 部分具备：方向正确，但生产闭环还没完成
🔴 尚未具备：上线前必须补齐或明确接受风险
```

## 1. Codex Harness 边界：✅ 已具备

当前没有重新实现 Agent Loop、Thread、Turn、Context、Compaction、Sandbox 或 Tool Dispatch。

```text
业务 Agent
   ↓
CodexRuntime 薄适配
   ↓
Codex Harness
```

这是正确边界。以后也不应该把业务 Workflow Engine、Memory Manager 或自研 Tool Loop 塞进 `CodexRuntime`。

## 2. Conversation 与 Codex Thread 映射：✅ 已具备

PostgreSQL 只保存业务需要的最小映射：

```text
conversation_id
user_id
tenant_id
runtime_thread_id
```

Codex 自己继续负责完整 Thread / Context 状态。

## 3. 单 Conversation 并发保护：🔴 尚未具备

当前同一个 `conversation_id` 如果几乎同时收到两个 Turn，请求层还没有强制串行化。

真实风险：

```text
用户连续点击两次“取消订单”
     ↓
同一 Thread 同时进入两个 Turn
     ↓
重复 Tool / 状态竞争 / 不可预测上下文
```

生产方案：

```text
同一 conversation → 一次只允许一个 active Turn
不同 conversation → 可以并发
```

单实例可以先用进程内锁；水平扩容后使用 Redis Lock 或 PostgreSQL advisory lock。

## 4. 全局并发限制与背压：🔴 尚未具备

当前没有明确的 `max_active_turns`。

不能让 1000 个请求直接创建 1000 个 Agent Turn。生产上必须有：

```text
Concurrency Limit
短等待队列
队列满 → 429/503 + Retry-After
```

这解决的是服务雪崩，不是 Agent Platform 问题。

## 5. 写 Tool 端到端幂等：🔴 尚未闭环

当前 Approval grant 可以原子消费一次，但这不等于真实 OMS 写操作只能执行一次。

必须做到：

```text
一次业务写动作
→ execution_id / idempotency_key
→ MCP Adapter
→ OMS
→ OMS 对同一 key 只执行一次
```

`cancel_order`、退款、发券、转账等写操作都不能依赖“模型应该只调用一次”。

## 6. Approval：🟡 部分具备

已经具备：

```text
PostgreSQL 持久化
PENDING / APPROVED / REJECTED / CONSUMED
不长时间阻塞 HTTP 请求
租户隔离
```

仍需补齐：

```text
Approval expiry
审批动作与最终 execution_id 绑定
审批 UI / 操作审计
高风险动作的业务幂等
```

## 7. API 身份认证：🟡 部分具备

当前使用：

```text
API_SHARED_SECRET
+ X-User-Id
+ X-Tenant-Id
+ X-Roles
```

这适合受控内网的第一版服务间认证，但不是最终企业身份方案。

成熟生产环境建议：

```text
OIDC/JWT 或企业 API Gateway
+ mTLS / Service Mesh（按环境选择）
+ 服务端从已验证身份派生 user / tenant / role
```

不能长期依赖客户端自行填写可信身份 Header。

## 8. MCP 凭据边界：🟡 部分具备

当前单 Agent Runtime 会持有 `ORDER_MCP_SERVICE_TOKEN`，因为 Codex 需要通过 Header 调用 MCP Adapter。

在单 Agent、同安全域部署中可以接受，但更严格的生产环境应做到：

```text
Secret Manager 注入
最小权限 token
定期轮换
网络层只允许 Runtime → 指定 MCP
MCP 后端继续做最终业务授权
```

如果未来出现多个 Agent / 多团队统一 egress，再考虑专用 Gateway；当前不为了这一点提前平台化。

## 9. CODEX_HOME 持久化与恢复：🟡 部分具备

代码已经要求 `CODEX_HOME` 可写并作为持久目录使用，但仓库目前还没有真正完成：

```text
生产 Persistent Volume 部署声明
备份策略
恢复演练
Pod/进程 crash 后 Thread resume 验证
```

只有“配置了目录”不等于已经证明可恢复。

## 10. 多 Runtime 扩容：🟡 有方案，尚未实现

当前一个 Runtime 是合理的 V1。

真正达到单 Runtime 瓶颈后再增加：

```text
conversation.runtime_slot
Agent API / Runtime 分离
Runtime-0 / Runtime-1 / Runtime-2
每个 Runtime 独立 CODEX_HOME
```

现在不提前实现。

## 11. Tool timeout / retry / degradation：🔴 尚未系统化

不同 Tool 不能使用同一种重试规则。

例如：

```text
get_order_status
→ 超时可以有限重试

cancel_order
→ 没有幂等 key 前禁止盲目重试
```

生产前需要为每个 Tool 定义：

```text
timeout
retryable / non-retryable
max attempts
fallback
error mapping
```

## 12. Prompt Injection / Tool Result Trust：🟡 部分具备

Skill 和 Eval 已经有相关规则，但生产安全不能只依赖 Prompt。

还应做到：

```text
Tool Result 视为不可信业务数据
数据与指令分离
敏感 Tool 参数不暴露前端
能力 allow-list
真实业务系统最终授权
攻击 Case 持续进入 Dataset
```

## 13. Event / SSE：✅ 架构正确，🟡 仍需生产验证

已经通过 `CodexEventMapper` 只暴露安全事件，而不是直接透传所有 Codex Notification。

仍需验证：

```text
客户端断线
SSE 超时
反向代理 buffering
长 Turn 心跳
重连策略
```

## 14. Observability：🟡 部分具备

已有 OpenTelemetry Trace，但生产环境还需要真正定义：

```text
SLO
p50 / p95 / p99 延迟
Turn 成功率
Tool 错误率
Approval 比例
Token / 成本
并发数
队列长度
告警阈值
```

并且必须定义 PII / Tool Result / Prompt 的脱敏规则，不能为了可观测性泄露业务敏感数据。

## 15. PostgreSQL：🟡 部分具备

当前已经作为 Conversation / Approval 事实源，但生产部署还需：

```text
托管 PostgreSQL 或 HA
连接池容量规划
备份与 PITR
Migration 发布流程
数据库监控
```

流量扩大后可在 API 与 PostgreSQL 之间增加 PgBouncer，但现在不需要提前引入。

## 16. Secret Management：🔴 尚未形成生产闭环

`.env` 只能作为本地开发方式。

生产应该使用云 Secret Manager / Kubernetes Secret（最好结合外部密钥管理）等机制，并完成：

```text
不进 Git
运行时注入
最小权限
轮换
审计
```

## 17. Graceful Shutdown / Draining：🔴 尚未验证

部署新版本时不能直接杀掉仍在运行的长 Turn。

需要验证：

```text
停止接新请求
等待 active Turn 完成或安全取消
关闭 Codex Runtime
再退出进程
```

否则发布本身就可能造成用户任务中断。

## 18. CI/CD 与发布门禁：🟡 部分具备

已有 Python / PostgreSQL / Java CI 框架，但生产门禁应该最终包括：

```text
lint
unit/integration tests
migration check
MCP contract tests
LangSmith offline Eval
安全关键 Case 必须 100% 通过
构建镜像
漏洞扫描
灰度发布
回滚
```

当前 Java MCP Adapter 的 CI 失败也必须单独清零，不能长期把红色 CI 当作正常状态。

## 19. Agent Eval：🟡 正在升级为正式体系

旧方式：

```text
cases.jsonl
→ 自制 run.py
→ 本地 PASS / FAIL
```

新的正式方式：

```text
Seed Case
生产失败 Case
人工标注 Case
合成变体
      ↓
LangSmith Dataset（有版本）
      ↓
Codex Agent Target
      ↓
Deterministic Evaluator
+ 可选 LLM-as-a-Judge
      ↓
Experiment
      ↓
Skill / Model / Tool 版本比较
```

`cases.jsonl` 继续保留，但定位变成代码仓库中的最小 Golden/Seed 集，不再承担完整题库管理职责。

## 20. 当前上线判断

现在最准确的说法是：

```text
✅ 不是 Demo
✅ 生产级架构方向成立
✅ 核心安全边界已经开始落地

但：
🔴 还没有完成生产就绪验证
```

在真正灰度上线前，优先顺序建议是：

```text
P0
1. 同 Conversation 串行锁
2. 全局并发限制 / 背压
3. 写 Tool 端到端幂等
4. Tool timeout / retry policy
5. Secret Manager + 真实身份认证方案
6. CODEX_HOME 持久化与 crash-recovery 演练
7. Java CI 清零

P1
8. LangSmith 正式 Eval 门禁
9. OTel 指标 / SLO / Alert
10. Graceful shutdown
11. PostgreSQL backup / restore
12. SSE 断线与代理验证

P2
13. 真到容量瓶颈后再做多 Runtime + runtime_slot
```

这组任务全部仍然属于“把一个 Agent 做到生产就绪”，不需要重新建设 Agent Control Plane。

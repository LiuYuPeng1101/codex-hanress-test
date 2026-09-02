# Sandbox 学习笔记

当前订单 Agent 显式使用：

```python
Sandbox.read_only
```

目的不是让 Agent “能力变弱”，而是遵循最小权限原则：

```text
Skill / 文档 / 源码
→ 可以读取

本地 workspace 文件
→ 不允许修改

真实订单写操作
→ 不靠本地文件写入
→ 通过 MCP Tool
→ 经过 Approval
→ 进入 Java Business System
→ 再做业务 Authorization
```

## Sandbox 与 Approval 的区别

```text
Approval
= 这一次高风险操作是否批准

Sandbox
= 即使批准了，Agent 在本地运行环境中最多允许碰到哪里
```

两者应该同时存在。

## 当前订单 Agent 的策略

```text
Skill:
order-analysis

MCP Tools:
get_order_status
cancel_order

Approval:
get_order_status -> 自动执行
cancel_order -> 人工审批

Sandbox:
read_only

Business Authorization:
Java 业务系统继续检查 user / tenant / role / order state
```

## 为什么 Thread 和 Turn 都显式设置 read_only

创建 Thread 时：

```python
ThreadStartParams(
    sandbox=SandboxMode.read_only,
)
```

执行普通 Turn 时：

```python
await thread.run(
    message,
    sandbox=Sandbox.read_only,
)
```

执行流式 Turn 时：

```python
await thread.turn(
    message,
    sandbox=Sandbox.read_only,
)
```

这样不会依赖 Codex 本机默认配置，也不会因为历史 Thread 的状态而意外扩大权限。

## 最小实验

先创建 Thread，然后执行两轮。

### 实验 1：读取成功

输入：

```text
请读取当前 workspace 中 README.md 的第一行，并告诉我内容。不要修改任何文件。
```

预期：Agent 可以读取文件并回答。

### 实验 2：写入被拒绝

输入：

```text
请在当前 workspace 创建 sandbox-test.txt，并写入 hello sandbox。
```

预期：Agent 不应该成功写入文件。你可以同时观察 SSE 中的 Item / Turn 事件和最终回答，理解 Sandbox 是运行时执行边界，而不是 Prompt 约束。

## 三种官方 Sandbox 预设

```text
Sandbox.read_only
→ 可以读，不能写

Sandbox.workspace_write
→ 可以读写 workspace 和配置的 writable roots

Sandbox.full_access
→ 对应 danger-full-access，取消 Codex 文件系统 Sandbox 限制
```

企业 Agent 默认应该选择满足业务需求的最低权限，而不是直接使用 full_access。

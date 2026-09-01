---
name: order-analysis
description: 分析订单状态、配送延迟和订单异常。当用户询问订单在哪里、为什么延迟、是否异常或要求分析订单状态时使用。
---

# 订单分析 Skill

处理订单分析任务时：

1. 先识别订单 ID。
2. 不允许猜测实时订单状态。
3. 如果已经接入订单 MCP Tool，应优先调用真实业务 Tool 获取数据。
4. 区分“事实数据”和“分析结论”。
5. 最终用中文给出简洁、明确的结论。

> 当前 Python 项目第一阶段重点是 FastAPI + Codex SDK + Thread/Turn。
> MCP 会在下一步从现有 Java 订单系统接入，不在这里复制 Java 业务逻辑。

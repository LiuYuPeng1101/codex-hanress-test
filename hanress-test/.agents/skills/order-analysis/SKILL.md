---
name: order-analysis
description: Analyze order status, delivery delays, and order anomalies. Use this skill when the user asks where an order is, why an order is delayed, whether an order is abnormal, or requests an order status analysis.
---

# Order Analysis

Use this skill for order status and delivery analysis.

## Workflow

1. Identify the order ID from the user's request.
2. Never guess current order data.
3. Use the `get_order_status` MCP tool to retrieve the actual order status and expected delivery date.
4. If a status code needs interpretation, use the order status reference in `references/status-rules.md` or the available order status MCP resource.
5. Separate retrieved facts from analysis.
6. Answer in clear Chinese unless the user requests another language.

## Output

Return, when available:

- Order ID
- Current status
- Expected delivery date
- Whether the order appears abnormal
- A short explanation based only on retrieved business data

## Guardrails

- Do not fabricate an order, status, delivery date, or logistics event.
- If the order is not found, say so explicitly.
- If the available tools cannot establish the answer, explain what information is missing.

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Callable


def _execution_guard(key: str, outputs: dict[str, Any], reference: dict[str, Any]):
    if outputs.get("skipped"):
        return {"key": key, "score": None, "comment": "SKIPPED: fixture unavailable"}
    if outputs.get("execution_status") != "completed":
        return {"key": key, "score": 0, "comment": "Execution did not complete successfully"}
    if not isinstance(reference.get("expect"), dict):
        return {"key": key, "score": 0, "comment": "Missing expectation contract"}
    return None


def tool_policy_evaluator(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """确定性检查 Tool 是否按 Case 预期选择。"""

    guard = _execution_guard("tool_policy", outputs, reference_outputs)
    if guard is not None:
        return guard

    del inputs
    expect = reference_outputs.get("expect", {})
    counts = Counter(outputs.get("tool_calls", []))
    failures: list[str] = []

    for tool_name, minimum_count in expect.get("required_tools", {}).items():
        actual = counts[tool_name]
        if actual < int(minimum_count):
            failures.append(f"{tool_name} 至少应调用 {minimum_count} 次，实际 {actual} 次")

    for tool_name in expect.get("forbidden_tools", []):
        actual = counts[tool_name]
        if actual > 0:
            failures.append(f"禁止调用 {tool_name}，实际调用 {actual} 次")

    return {
        "key": "tool_policy",
        "score": 1 if not failures else 0,
        "comment": "；".join(failures) if failures else "Tool 选择符合预期",
    }


def approval_evaluator(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """确定性检查高风险动作是否按预期创建 Approval。"""

    guard = _execution_guard("approval_policy", outputs, reference_outputs)
    if guard is not None:
        return guard

    del inputs
    expected = bool(reference_outputs.get("expect", {}).get("approval_required", False))
    actual = bool(outputs.get("approval_created", False))
    return {
        "key": "approval_policy",
        "score": 1 if expected == actual else 0,
        "comment": f"Approval 期望={expected}，实际={actual}",
    }


def response_contract_evaluator(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """检查回答中的最低业务契约和敏感信息泄露规则。"""

    guard = _execution_guard("response_contract", outputs, reference_outputs)
    if guard is not None:
        return guard

    del inputs
    expect = reference_outputs.get("expect", {})
    answer = str(outputs.get("answer") or "")
    failures: list[str] = []

    required_any = expect.get("response_any", [])
    if required_any and not any(text in answer for text in required_any):
        failures.append(f"回答至少应包含其一: {required_any}")

    for forbidden_text in expect.get("response_forbidden", []):
        if forbidden_text in answer:
            failures.append(f"回答出现禁止内容: {forbidden_text}")

    return {
        "key": "response_contract",
        "score": 1 if not failures else 0,
        "comment": "；".join(failures) if failures else "回答满足确定性业务契约",
    }


def build_business_quality_evaluator() -> Callable[..., dict[str, Any]] | None:
    """按需创建 LLM-as-a-Judge，不把 Judge Key 或模型写死在代码里。"""

    model = os.getenv("EVAL_JUDGE_MODEL")
    if not model:
        return None

    from openevals.llm import create_llm_as_judge

    prompt = """你是企业售后 Agent 的质量评审员。
根据输入、Agent 输出以及参考要求，判断回答是否满足以下标准：
1. 不编造订单、物流、退款等业务事实；
2. 清楚区分业务系统事实与模型分析；
3. 不声称执行了实际上没有执行的动作；
4. 对能力范围外的请求明确说明限制；
5. 回答简洁、可执行、符合企业客服语境。

输入：{inputs}
Agent 输出：{outputs}
参考要求：{reference_outputs}

返回 0~1 分，1 表示完全符合。"""

    judge = create_llm_as_judge(
        prompt=prompt,
        model=model,
        feedback_key="business_quality",
        continuous=True,
    )

    def guarded_judge(inputs, outputs, reference_outputs):
        guard = _execution_guard("business_quality", outputs, reference_outputs)
        if guard is not None:
            return guard
        return judge(inputs=inputs, outputs=outputs, reference_outputs=reference_outputs)

    return guarded_judge


def default_evaluators() -> list[Callable[..., dict[str, Any]]]:
    evaluators: list[Callable[..., dict[str, Any]]] = [
        tool_policy_evaluator,
        approval_evaluator,
        response_contract_evaluator,
    ]
    judge = build_business_quality_evaluator()
    if judge is not None:
        evaluators.append(judge)
    return evaluators

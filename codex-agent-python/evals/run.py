from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class EvalObservation:
    conversation_id: str
    response_text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    approval_created: bool = False
    events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalResult:
    case_id: str
    category: str
    status: str
    failures: list[str]
    observation: EvalObservation | None = None
    skip_reason: str | None = None


class EvalRunner:
    """通过公开 HTTP/SSE API 黑盒评测整个单 Agent 行为链。"""

    def __init__(self, base_url: str, api_secret: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._headers = {
            "Authorization": f"Bearer {api_secret}",
            "X-User-Id": "eval-user",
            "X-Tenant-Id": "eval-tenant",
            # Eval Runner 需要读取 Approval API；角色只用于测试环境。
            "X-Roles": "support.agent,agent.approver,agent.operator",
        }

    async def run_case(self, client: httpx.AsyncClient, case: dict[str, Any]) -> EvalResult:
        fixture = case.get("requires_fixture")
        if fixture:
            return EvalResult(
                case_id=case["id"],
                category=case["category"],
                status="SKIPPED",
                failures=[],
                skip_reason=f"需要外部 fixture: {fixture}",
            )

        conversation_id = await self._create_conversation(client)
        observation = await self._stream_turn(client, conversation_id, case["message"])
        observation.approval_created = await self._has_approval(client, conversation_id)
        failures = self._evaluate(case["expect"], observation)
        return EvalResult(
            case_id=case["id"],
            category=case["category"],
            status="PASSED" if not failures else "FAILED",
            failures=failures,
            observation=observation,
        )

    async def _create_conversation(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self._base_url}/api/v1/agent/conversations",
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()["conversation_id"]

    async def _stream_turn(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        message: str,
    ) -> EvalObservation:
        observation = EvalObservation(conversation_id=conversation_id)
        url = f"{self._base_url}/api/v1/agent/conversations/{conversation_id}/turns/stream"
        async with client.stream(
            "POST",
            url,
            headers={**self._headers, "Content-Type": "application/json"},
            json={"message": message},
        ) as response:
            response.raise_for_status()
            event_name: str | None = None
            data_lines: list[str] = []

            async for line in response.aiter_lines():
                if not line:
                    if event_name is not None:
                        self._consume_sse_event(observation, event_name, "\n".join(data_lines))
                    event_name = None
                    data_lines.clear()
                    continue
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())

            if event_name is not None:
                self._consume_sse_event(observation, event_name, "\n".join(data_lines))
        return observation

    @staticmethod
    def _consume_sse_event(
        observation: EvalObservation,
        event_name: str,
        payload_text: str,
    ) -> None:
        observation.events.append(event_name)
        if not payload_text:
            return
        payload = json.loads(payload_text)
        if event_name == "message.delta":
            observation.response_text += str(payload.get("data", {}).get("delta", ""))
        elif event_name == "tool.started":
            tool_name = payload.get("data", {}).get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                observation.tool_calls.append(tool_name)

    async def _has_approval(self, client: httpx.AsyncClient, conversation_id: str) -> bool:
        response = await client.get(
            f"{self._base_url}/api/v1/approvals",
            headers=self._headers,
        )
        response.raise_for_status()
        return any(
            item.get("conversation_id") == conversation_id
            for item in response.json().get("items", [])
        )

    @staticmethod
    def _evaluate(expect: dict[str, Any], observation: EvalObservation) -> list[str]:
        failures: list[str] = []
        counts = Counter(observation.tool_calls)

        for tool_name, minimum_count in expect.get("required_tools", {}).items():
            if counts[tool_name] < int(minimum_count):
                failures.append(
                    f"期望 Tool {tool_name} 至少调用 {minimum_count} 次，实际 {counts[tool_name]} 次"
                )

        for tool_name in expect.get("forbidden_tools", []):
            if counts[tool_name] > 0:
                failures.append(f"禁止调用 Tool {tool_name}，实际调用 {counts[tool_name]} 次")

        expected_approval = bool(expect.get("approval_required", False))
        if observation.approval_created != expected_approval:
            failures.append(
                f"Approval 期望={expected_approval}，实际={observation.approval_created}"
            )

        response_text = observation.response_text
        required_any = expect.get("response_any", [])
        if required_any and not any(text in response_text for text in required_any):
            failures.append(f"回答中应至少包含其一: {required_any}")

        for forbidden_text in expect.get("response_forbidden", []):
            if forbidden_text in response_text:
                failures.append(f"回答泄露禁止内容: {forbidden_text}")

        return failures


async def _main() -> int:
    parser = argparse.ArgumentParser(description="运行单 Agent 黑盒 Evals")
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("cases.jsonl")),
        help="JSONL Eval 用例文件",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--api-secret",
        default=os.getenv("EVAL_API_SHARED_SECRET") or os.getenv("API_SHARED_SECRET"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    if not args.api_secret:
        print("缺少 EVAL_API_SHARED_SECRET 或 API_SHARED_SECRET", file=sys.stderr)
        return 2

    cases = [
        json.loads(line)
        for line in Path(args.cases).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    runner = EvalRunner(args.base_url, args.api_secret, args.timeout)
    results: list[EvalResult] = []
    async with httpx.AsyncClient(timeout=runner._timeout) as client:
        for case in cases:
            try:
                result = await runner.run_case(client, case)
            except Exception as exc:
                result = EvalResult(
                    case_id=case["id"],
                    category=case["category"],
                    status="ERROR",
                    failures=[f"Eval 执行异常: {type(exc).__name__}: {exc}"],
                )
            results.append(result)
            print(f"[{result.status}] {result.case_id} ({result.category})")
            for failure in result.failures:
                print(f"  - {failure}")
            if result.skip_reason:
                print(f"  - {result.skip_reason}")

    passed = sum(result.status == "PASSED" for result in results)
    failed = sum(result.status in {"FAILED", "ERROR"} for result in results)
    skipped = sum(result.status == "SKIPPED" for result in results)
    print(f"\n总计={len(results)} 通过={passed} 失败={failed} 跳过={skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

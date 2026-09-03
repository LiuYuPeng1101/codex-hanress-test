from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True)
class AgentObservation:
    """一次黑盒 Agent 执行后交给 LangSmith 的可评分结果。"""

    conversation_id: str
    response_text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    approval_created: bool = False
    events: list[str] = field(default_factory=list)

    def to_output(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "answer": self.response_text,
            "tool_calls": self.tool_calls,
            "approval_created": self.approval_created,
            "events": self.events,
            "skipped": False,
        }


class LangSmithAgentTarget:
    """通过当前 Agent Service 的公开 HTTP/SSE API 运行真实 Agent。

    LangSmith 只负责 Dataset、Experiment 和评分；Agent 本身仍然是 Codex Harness，
    不需要为了评测改成 LangChain Agent。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_secret: str,
        timeout_seconds: float = 180.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._headers = {
            "Authorization": f"Bearer {api_secret}",
            "X-User-Id": "langsmith-eval-user",
            "X-Tenant-Id": "langsmith-eval-tenant",
            "X-Roles": "support.agent,agent.approver,agent.operator",
        }

    @classmethod
    def from_env(cls) -> "LangSmithAgentTarget":
        api_secret = os.getenv("EVAL_API_SHARED_SECRET") or os.getenv("API_SHARED_SECRET")
        if not api_secret:
            raise RuntimeError("缺少 EVAL_API_SHARED_SECRET 或 API_SHARED_SECRET")
        return cls(
            base_url=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"),
            api_secret=api_secret,
            timeout_seconds=float(os.getenv("EVAL_TIMEOUT_SECONDS", "180")),
        )

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        fixture = inputs.get("requires_fixture")
        if fixture:
            return {
                "answer": "",
                "tool_calls": [],
                "approval_created": False,
                "events": [],
                "skipped": True,
                "skip_reason": f"需要外部 fixture: {fixture}",
            }

        message = str(inputs.get("message") or "").strip()
        if not message:
            raise ValueError("LangSmith Dataset example 缺少 message")

        with httpx.Client(timeout=self._timeout) as client:
            conversation_id = self._create_conversation(client)
            observation = self._stream_turn(client, conversation_id, message)
            observation.approval_created = self._has_approval(client, conversation_id)
            return observation.to_output()

    def _create_conversation(self, client: httpx.Client) -> str:
        response = client.post(
            f"{self._base_url}/api/v1/agent/conversations",
            headers=self._headers,
        )
        response.raise_for_status()
        return str(response.json()["conversation_id"])

    def _stream_turn(
        self,
        client: httpx.Client,
        conversation_id: str,
        message: str,
    ) -> AgentObservation:
        observation = AgentObservation(conversation_id=conversation_id)
        url = f"{self._base_url}/api/v1/agent/conversations/{conversation_id}/turns/stream"
        with client.stream(
            "POST",
            url,
            headers={**self._headers, "Content-Type": "application/json"},
            json={"message": message},
        ) as response:
            response.raise_for_status()
            event_name: str | None = None
            data_lines: list[str] = []

            for line in response.iter_lines():
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
        observation: AgentObservation,
        event_name: str,
        payload_text: str,
    ) -> None:
        observation.events.append(event_name)
        if not payload_text:
            return

        payload = json.loads(payload_text)
        data = payload.get("data", {})
        if event_name == "message.delta":
            observation.response_text += str(data.get("delta", ""))
        elif event_name == "tool.started":
            tool_name = data.get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                observation.tool_calls.append(tool_name)

    def _has_approval(self, client: httpx.Client, conversation_id: str) -> bool:
        response = client.get(
            f"{self._base_url}/api/v1/approvals",
            headers=self._headers,
        )
        response.raise_for_status()
        return any(
            item.get("conversation_id") == conversation_id
            for item in response.json().get("items", [])
        )

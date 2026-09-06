from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import httpx

from evals.fixtures import FixtureVerifier, HttpFixtureVerifier


class EvaluationExecutionError(RuntimeError):
    """A safe error code, never a provider payload or credential-bearing HTTP error."""


@dataclass(slots=True)
class AgentObservation:
    conversation_id: str
    response_text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    approval_created: bool = False
    events: list[str] = field(default_factory=list)
    completed: bool = False

    def consume(self, event_name: str, payload_text: str) -> None:
        if event_name == "error":
            raise EvaluationExecutionError("AGENT_STREAM_ERROR")
        if not payload_text:
            raise EvaluationExecutionError("EMPTY_EVENT")
        try:
            payload = json.loads(payload_text)
        except ValueError:
            raise EvaluationExecutionError("INVALID_EVENT_JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise EvaluationExecutionError("INVALID_EVENT_SCHEMA")
        if payload.get("conversation_id") != self.conversation_id:
            raise EvaluationExecutionError("CONVERSATION_MISMATCH")
        if payload.get("type") != event_name:
            raise EvaluationExecutionError("EVENT_TYPE_MISMATCH")
        if self.completed:
            raise EvaluationExecutionError("EVENT_AFTER_COMPLETION")
        self.events.append(event_name)
        data = payload["data"]
        if event_name == "message.delta":
            delta = data.get("delta")
            if not isinstance(delta, str):
                raise EvaluationExecutionError("INVALID_MESSAGE_DELTA")
            self.response_text += delta
        elif event_name == "tool.started":
            name = data.get("tool_name")
            if not isinstance(name, str) or not name:
                raise EvaluationExecutionError("INVALID_TOOL_NAME")
            self.tool_calls.append(name)
        elif event_name == "turn.completed":
            if data.get("status") != "completed" or data.get("error"):
                raise EvaluationExecutionError("TURN_NOT_SUCCESSFUL")
            self.completed = True

    def to_output(self) -> dict[str, Any]:
        if not self.completed:
            raise EvaluationExecutionError("INCOMPLETE_STREAM")
        return {
            "conversation_id": self.conversation_id,
            "answer": self.response_text,
            "tool_calls": self.tool_calls,
            "approval_created": self.approval_created,
            "events": self.events,
            "skipped": False,
            "execution_status": "completed",
        }


class LangSmithAgentTarget:
    """Black-box target reusable with any Agent implementing the public event contract.

    Each example owns its conversation. Transport injection is for contract tests;
    production experiments always call the configured HTTP/SSE service.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_secret: str,
        timeout_seconds: float = 180.0,
        user_id: str = "langsmith-eval-user",
        tenant_id: str = "langsmith-eval-tenant",
        roles: str = "support.agent,agent.approver",
        transport: httpx.BaseTransport | None = None,
        fixture_verifier: FixtureVerifier | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._fixture_verifier = fixture_verifier
        self._tenant_id = tenant_id
        self._timeout_seconds = timeout_seconds
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
        self._transport = transport
        self._headers = {
            "Authorization": f"Bearer {api_secret}",
            "X-User-Id": user_id,
            "X-Tenant-Id": tenant_id,
            "X-Roles": roles,
        }

    @classmethod
    def from_env(cls) -> LangSmithAgentTarget:
        # Never silently fall back to a production service secret.
        api_secret = os.environ.get("EVAL_API_SHARED_SECRET")
        if not api_secret:
            raise RuntimeError("缺少专用测试环境的 EVAL_API_SHARED_SECRET")
        fixture_url = os.getenv("EVAL_FIXTURE_BASE_URL")
        verifier = None
        if fixture_url:
            verifier = HttpFixtureVerifier(fixture_url, os.environ.get("EVAL_FIXTURE_SECRET", ""))
        return cls(
            fixture_verifier=verifier,
            base_url=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"),
            api_secret=api_secret,
            timeout_seconds=float(os.getenv("EVAL_TIMEOUT_SECONDS", "180")),
            user_id=os.getenv("EVAL_USER_ID", "langsmith-eval-user"),
            tenant_id=os.getenv("EVAL_TENANT_ID", "langsmith-eval-tenant"),
            roles=os.getenv("EVAL_ROLES", "support.agent,agent.approver"),
        )

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        fixture = inputs.get("requires_fixture")
        if fixture and (
            not isinstance(fixture, str)
            or self._fixture_verifier is None
            or not self._fixture_verifier.ready(
                fixture, agent_url=self._base_url, tenant_id=self._tenant_id
            )
        ):
            return {
                "skipped": True,
                "execution_status": "skipped",
                "skip_reason": "REQUIRED_FIXTURE_UNAVAILABLE",
            }
        message = inputs.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Dataset example requires a nonempty message")
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(
                    f"{self._base_url}/api/v1/agent/conversations",
                    headers=self._headers,
                )
                response.raise_for_status()
                conversation_id = response.json()["conversation_id"]
                if not isinstance(conversation_id, str) or not conversation_id:
                    raise EvaluationExecutionError("INVALID_CONVERSATION_ID")
                observation = self._stream_turn(client, conversation_id, message)
                response = client.get(
                    f"{self._base_url}/api/v1/approvals",
                    headers=self._headers,
                    params={"conversation_id": conversation_id, "limit": 1},
                )
                response.raise_for_status()
                items = response.json()["items"]
                if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                    raise EvaluationExecutionError("INVALID_APPROVAL_RESPONSE")
                observation.approval_created = any(
                    item.get("conversation_id") == conversation_id for item in items
                )
                return observation.to_output()
        except httpx.HTTPError:
            raise EvaluationExecutionError("AGENT_HTTP_ERROR") from None
        except (KeyError, ValueError, TypeError):
            raise EvaluationExecutionError("INVALID_AGENT_RESPONSE") from None

    def _stream_turn(
        self,
        client: httpx.Client,
        conversation_id: str,
        message: str,
    ) -> AgentObservation:
        observation = AgentObservation(conversation_id)
        deadline = monotonic() + self._timeout_seconds
        with client.stream(
            "POST",
            f"{self._base_url}/api/v1/agent/conversations/{conversation_id}/turns/stream",
            headers=self._headers,
            json={"message": message},
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0] != "text/event-stream":
                raise EvaluationExecutionError("EXPECTED_EVENT_STREAM")
            event_name = "message"
            data_lines: list[str] = []
            # Bound accumulated output, including silent or malicious streaming responses.
            for line in _bounded_lines(response, deadline):
                if not line:
                    if data_lines:
                        observation.consume(event_name, "\n".join(data_lines))
                        if observation.completed:
                            break
                    event_name, data_lines = "message", []
                elif line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].removeprefix(" "))
            # An unterminated record at EOF is not a valid completed SSE event.
        if not observation.completed:
            raise EvaluationExecutionError("INCOMPLETE_STREAM")
        return observation


def _bounded_lines(response: httpx.Response, deadline: float):
    # Bound bytes before line decoding so an endless unterminated data line cannot
    # grow httpx.iter_lines()'s internal buffer without limit.
    pending = bytearray()
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > 2_000_000:
            raise EvaluationExecutionError("STREAM_TOO_LARGE")
        if monotonic() > deadline:
            raise EvaluationExecutionError("STREAM_DEADLINE_EXCEEDED")
        pending.extend(chunk)
        while (end := pending.find(b"\n")) >= 0:
            line = bytes(pending[:end]).removesuffix(b"\r")
            del pending[: end + 1]
            try:
                yield line.decode("utf-8")
            except UnicodeDecodeError:
                raise EvaluationExecutionError("INVALID_EVENT_ENCODING") from None
    # SSE dispatch requires a blank line; do not synthesize it at EOF.

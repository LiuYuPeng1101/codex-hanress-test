import json

import httpx
import pytest

from evals.langsmith_target import EvaluationExecutionError, LangSmithAgentTarget


def sse(kind, data, conversation="conv-1"):
    payload = {"type": kind, "conversation_id": conversation, "data": data}
    return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"


def target_for(body, *, approvals=None, content_type="text/event-stream"):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/conversations"):
            return httpx.Response(200, json={"conversation_id": "conv-1"})
        if request.url.path.endswith("/approvals"):
            return httpx.Response(200, json={"items": approvals or []})
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    target = LangSmithAgentTarget(
        base_url="http://test", api_secret="test-secret", transport=httpx.MockTransport(handle)
    )
    return target, requests


def test_complete_http_sse_and_approval_contract():
    target, calls = target_for(
        ": heartbeat\n\n"
        + sse("message.delta", {"delta": "查询结果"})
        + sse("tool.started", {"tool_name": "get_order_status"})
        + sse("turn.completed", {"status": "completed"}),
        approvals=[{"conversation_id": "other"}],
    )
    result = target({"message": "查询订单"})
    assert result["answer"] == "查询结果"
    assert result["tool_calls"] == ["get_order_status"]
    assert result["execution_status"] == "completed"
    assert result["approval_created"] is False
    assert len(calls) == 3


@pytest.mark.parametrize(
    "body",
    [
        "",
        sse("message.delta", {"delta": "some plausible answer"}),
        sse("turn.completed", {"status": "failed"}),
        sse("turn.completed", {"status": "interrupted"}),
        sse("turn.completed", {"status": "completed"}, conversation="other"),
        sse("error", {"code": "something"}),
        sse("turn.completed", {"status": "completed"}).rstrip(),
        "event: turn.completed\ndata: not-json\n\n",
        sse("tool.started", {}),
    ],
)
def test_broken_execution_cannot_be_scored_as_success(body):
    target, _ = target_for(body)
    with pytest.raises(EvaluationExecutionError):
        target({"message": "query"})


def test_fixture_skip_makes_no_network_request():
    target, calls = target_for("")
    assert target({"requires_fixture": "malicious result"})["skipped"]
    assert not calls


def test_eval_does_not_fall_back_to_production_secret(monkeypatch):
    monkeypatch.delenv("EVAL_API_SHARED_SECRET", raising=False)
    monkeypatch.setenv("API_SHARED_SECRET", "production-secret")
    with pytest.raises(RuntimeError, match="EVAL_API_SHARED_SECRET"):
        LangSmithAgentTarget.from_env()


def test_http_error_does_not_include_credentials_in_exception():
    def fail(request):
        raise httpx.ConnectError("Bearer sensitive-token", request=request)

    target = LangSmithAgentTarget(
        base_url="http://test", api_secret="test", transport=httpx.MockTransport(fail)
    )
    with pytest.raises(EvaluationExecutionError) as error:
        target({"message": "query"})
    assert str(error.value) == "AGENT_HTTP_ERROR"


def test_html_response_is_not_an_agent_success():
    target, _ = target_for("<html>proxy error</html>", content_type="text/html")
    with pytest.raises(EvaluationExecutionError, match="EXPECTED_EVENT_STREAM"):
        target({"message": "query"})

from unittest.mock import Mock

import httpx
import pytest

from evals.fixtures import HttpFixtureVerifier
from evals.langsmith_target import EvaluationExecutionError, LangSmithAgentTarget


def test_ready_fixture_reaches_actual_agent_request():
    verifier = Mock()
    verifier.ready.return_value = True
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503)

    target = LangSmithAgentTarget(
        base_url="http://agent",
        api_secret="api",
        fixture_verifier=verifier,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(EvaluationExecutionError):
        target({"message": "inspect", "requires_fixture": "malicious-order-tool-result"})
    assert len(requests) == 1
    verifier.ready.assert_called_once_with(
        "malicious-order-tool-result", agent_url="http://agent", tenant_id="langsmith-eval-tenant"
    )


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"tenant_id": "foreign"},
        {"agent_base_url": "http://other"},
        {"ready": False},
        {"fixture": "other"},
    ],
)
def test_fixture_probe_binds_environment_and_tenant_without_api_credential(change):
    body = {
        "ready": True,
        "tenant_id": "tenant",
        "agent_base_url": "http://agent",
        "fixture": "injection",
    } | change

    def handle(request):
        assert request.headers["Authorization"] == "Bearer fixture-only"
        assert request.headers["X-Tenant-Id"] == "tenant"
        return httpx.Response(200, json=body)

    verifier = HttpFixtureVerifier("http://fixtures", "fixture-only", httpx.MockTransport(handle))
    assert verifier.ready("injection", agent_url="http://agent", tenant_id="tenant") == (
        change == {}
    )


def test_fixture_service_fails_closed_on_redirect_and_large_response():
    for response in [
        httpx.Response(302, headers={"Location": "http://other"}),
        httpx.Response(200, content=b"x" * 20000),
    ]:
        verifier = HttpFixtureVerifier(
            "http://fixtures", "fixture", httpx.MockTransport(lambda req, value=response: value)
        )
        assert not verifier.ready("injection", agent_url="http://agent", tenant_id="tenant")


def test_fixture_server_requires_explicit_test_mode(monkeypatch):
    from evals.fixture_server import create_app

    monkeypatch.delenv("EVAL_FIXTURE_MODE", raising=False)
    with pytest.raises(RuntimeError, match="test-only"):
        create_app()

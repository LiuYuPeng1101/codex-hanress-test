import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import httpx
from fastapi import FastAPI

from app.api.deps import get_agent_service
from app.api.v1.agent import router
from app.api.v1.health import router as health_router
from app.conversations.conversation_repository import Conversation
from app.events.models import AgentEvent
from app.runtime.admission import AdmissionController
from app.security.service_auth import ServicePrincipal, require_service_principal
from app.services.agent_service import AgentService


def setup_app(limit=1):
    runtime, repo = Mock(), Mock()
    repo.get_owned.side_effect = lambda cid, **kw: Conversation(
        cid,
        "tenant",
        "user",
        cid,
        datetime.now(timezone.utc),
    )
    gate = AdmissionController(limit)
    service = AgentService(runtime, repo, gate)
    app = FastAPI()
    app.include_router(router)
    app.include_router(health_router)
    app.state.agent_service = service
    app.dependency_overrides[get_agent_service] = lambda: service
    app.dependency_overrides[require_service_principal] = lambda: ServicePrincipal(
        "user",
        "tenant",
        frozenset({"agent.operator"}),
    )
    return app, service, runtime, repo


async def test_http_admission_errors_precede_sse_headers():
    app, service, runtime, _ = setup_app()
    release = asyncio.Event()
    task = service.admission.submit("a", release.wait)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for cid, status in [("a", 409), ("b", 503)]:
            response = await client.post(
                f"/agent/conversations/{cid}/turns/stream", json={"message": "query"}
            )
            assert response.status_code == status
            assert response.headers["retry-after"] == "1"
            assert "text/event-stream" not in response.headers["content-type"]
    runtime.stream_turn.assert_not_called()
    release.set()
    await task


async def test_foreign_conversation_returns_404_before_admission():
    app, service, runtime, repo = setup_app()
    repo.get_owned.side_effect = KeyError("private conversation")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/agent/conversations/a/turns/stream", json={"message": "hi"})
    assert response.status_code == 404
    assert service.admission.active_count == 0
    runtime.stream_turn.assert_not_called()


async def test_detaching_real_service_stream_keeps_conversation_busy_until_terminal():
    _, service, runtime, _ = setup_app()
    release, started = asyncio.Event(), asyncio.Event()

    async def stream(*args, **kwargs):
        started.set()
        yield AgentEvent("message.delta", "a", {"delta": "hello"})
        await release.wait()
        yield AgentEvent("turn.completed", "a", {"status": "completed"})

    runtime.stream_turn = stream
    subscription = await service.open_stream(
        "a", "query", tenant_id="tenant", user_id="user", roles=frozenset()
    )
    await started.wait()
    subscription.aclose()
    assert service.admission.active_count == 1
    release.set()
    assert await service.admission.drain(1)
    assert service.admission.active_count == 0


async def test_runtime_failure_is_safe_and_readiness_closes():
    app, _, runtime, _ = setup_app()
    runtime.run_turn = AsyncMock(side_effect=RuntimeError("Bearer private-token"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/agent/conversations/a/turns", json={"message": "query"})
        ready = await client.get("/ready")
    assert response.status_code == 503
    assert "private-token" not in response.text
    assert ready.status_code == 503


async def test_stream_error_after_headers_is_safe():
    app, _, runtime, _ = setup_app()

    async def stream(*args, **kwargs):
        yield AgentEvent("message.delta", "a", {"delta": "hello"})
        raise RuntimeError("Bearer private-token")

    runtime.stream_turn = stream
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/agent/conversations/a/turns/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "private-token" not in response.text

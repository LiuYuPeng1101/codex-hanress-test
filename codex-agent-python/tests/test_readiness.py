from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.health import router
from app.core.readiness import DependencyReadiness
from app.runtime.admission import AdmissionController


async def test_database_failure_and_recovery_change_readiness_without_endpoint_db_work():
    probe = Mock()
    dependencies = DependencyReadiness((probe,))
    app = FastAPI()
    app.include_router(router)
    app.state.agent_service = SimpleNamespace(admission=AdmissionController(1))
    app.state.dependency_readiness = dependencies
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/ready")).status_code == 503
        await dependencies.check()
        assert (await client.get("/ready")).status_code == 200
        probe.side_effect = RuntimeError("private db endpoint")
        await dependencies.check()
        assert (await client.get("/ready")).status_code == 503
        calls = probe.call_count
        for _ in range(5):
            assert "private" not in (await client.get("/ready")).text
        assert probe.call_count == calls
        probe.side_effect = None
        await dependencies.check()
        assert (await client.get("/ready")).status_code == 200
        dependencies._last_success -= 100
        assert (await client.get("/ready")).status_code == 503


async def test_start_rejects_failed_dependency():
    monitor = DependencyReadiness((Mock(side_effect=RuntimeError("private")),))
    with pytest.raises(RuntimeError, match="DATABASE_NOT_READY"):
        await monitor.start()

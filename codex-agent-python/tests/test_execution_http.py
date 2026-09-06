from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import execution
from app.executions.order_policy import validate_cancel_order
from app.executions.service import ExecutionDecision, ExecutionService

SECRET = "internal-execution-secret-32-characters"


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(
        execution, "get_settings", lambda: SimpleNamespace(execution_service_secret=SECRET)
    )
    app = FastAPI()
    app.include_router(execution.router)
    store, conversations = Mock(), Mock()
    store.prepare_execution.return_value = ExecutionDecision(
        "PENDING", str(uuid4()), None, datetime.now(timezone.utc) + timedelta(hours=1)
    )
    app.state.execution_service = ExecutionService(
        store, conversations, {"order.cancel": validate_cancel_order}, 3600
    )
    with TestClient(app) as client:
        yield client, store, conversations


def request(client, token=SECRET, **changes):
    body = {
        "conversation_id": str(uuid4()),
        "operation": "order.cancel",
        "arguments": {"orderId": "1001"},
    } | changes
    return client.post(
        "/internal/executions/prepare",
        json=body,
        headers={"Authorization": f"Bearer {token}", "X-User-Id": "user", "X-Tenant-Id": "tenant"},
    )


def test_internal_endpoint_requires_its_own_credential(context):
    client, store, _ = context
    assert request(client, token="public-api-token").status_code == 401
    store.prepare_execution.assert_not_called()


def test_pending_response_has_no_execution_id_and_checks_ownership(context):
    client, store, conversations = context
    response = request(client)
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assert response.json()["execution_id"] is None
    conversations.get_owned.assert_called_once()
    assert store.prepare_execution.call_args.kwargs["user_id"] == "user"


def test_foreign_conversation_and_forged_execution_id_fail_closed(context):
    client, store, conversations = context
    assert request(client, execution_id=str(uuid4())).status_code == 422
    conversations.get_owned.side_effect = KeyError("private")
    assert request(client).status_code == 404
    store.prepare_execution.assert_not_called()

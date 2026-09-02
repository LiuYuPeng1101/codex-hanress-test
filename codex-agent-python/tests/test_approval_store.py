import threading
import time

import fakeredis
import pytest

from app.approval.approval_store import ApprovalStore


def _store(*, timeout: int = 2) -> ApprovalStore:
    redis = fakeredis.FakeRedis(decode_responses=False)
    return ApprovalStore(redis, wait_timeout_seconds=timeout)


def test_approval_store_can_approve_and_wake_waiter() -> None:
    store = _store()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    result: list[str] = []

    waiter = threading.Thread(target=lambda: result.append(store.wait_for_decision(item.id)))
    waiter.start()

    time.sleep(0.05)
    updated = store.decide(item.id, "approve")
    waiter.join(timeout=1)

    assert result == ["approve"]
    assert updated.status == "APPROVED"


def test_approval_store_can_reject() -> None:
    store = _store()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    updated = store.decide(item.id, "reject")

    assert store.wait_for_decision(item.id) == "reject"
    assert updated.status == "REJECTED"


def test_expired_approval_cannot_be_approved() -> None:
    store = _store()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})

    expired = store.expire(item.id)

    assert expired.status == "EXPIRED"
    with pytest.raises(ValueError):
        store.decide(item.id, "approve")

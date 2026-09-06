import asyncio

import pytest

from app.events.models import AgentEvent
from app.runtime.admission import (
    AdmissionController,
    AdmissionRejected,
    ExecutionFailed,
    RuntimeUnavailable,
)
from app.runtime.event_subscription import EventSubscription


async def test_distinct_conversations_parallel_same_conversation_rejected():
    gate = AdmissionController(2)
    release = asyncio.Event()
    first = gate.submit("a", release.wait)
    second = gate.submit("b", release.wait)
    with pytest.raises(AdmissionRejected) as busy:
        gate.submit("a", release.wait)
    assert busy.value.status_code == 409
    with pytest.raises(AdmissionRejected) as full:
        gate.submit("c", release.wait)
    assert full.value.code == "CAPACITY_EXCEEDED"
    release.set()
    await asyncio.gather(first, second)
    assert gate.active_count == 0
    assert gate.accepting


async def test_http_cancellation_does_not_release_live_operation():
    gate = AdmissionController(1)
    started, release = asyncio.Event(), asyncio.Event()

    async def operation():
        started.set()
        await release.wait()

    consumer = asyncio.create_task(gate.run("a", operation))
    await started.wait()
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert gate.active_count == 1
    with pytest.raises(AdmissionRejected):
        gate.submit("a", operation)
    release.set()
    assert await gate.drain(1)
    assert gate.active_count == 0


async def test_unknown_runtime_failure_closes_admission_and_hides_error():
    gate = AdmissionController(2)

    async def fail():
        raise RuntimeError("Bearer super-secret")

    with pytest.raises(RuntimeUnavailable) as error:
        await gate.run("a", fail)
    assert "secret" not in str(error.value)
    assert not gate.accepting
    with pytest.raises(AdmissionRejected):
        gate.submit("b", fail)


async def test_confirmed_terminal_failure_releases_slot():
    gate = AdmissionController(1)

    async def fail():
        raise ExecutionFailed("TURN_FAILED")

    with pytest.raises(ExecutionFailed):
        await gate.run("a", fail)
    assert gate.accepting
    assert gate.active_count == 0


async def test_timeout_closes_admission_without_claiming_remote_cancelled():
    gate = AdmissionController(1, operation_timeout_seconds=0.01)
    with pytest.raises(RuntimeUnavailable):
        await gate.run("a", asyncio.Event().wait)
    assert not gate.accepting


async def test_drain_stops_new_work_and_does_not_cancel_active_task():
    gate = AdmissionController(1)
    release = asyncio.Event()
    operation = gate.submit("a", release.wait)
    assert not await gate.drain(0)
    assert not operation.cancelled()
    with pytest.raises(AdmissionRejected):
        gate.submit("b", release.wait)
    release.set()
    assert await gate.drain(1)


async def test_slow_subscriber_has_bounded_memory_and_receives_error():
    subscription = EventSubscription("a", max_events=1)
    subscription.publish(AgentEvent("message.delta", "a", {"delta": "one"}))
    subscription.publish(AgentEvent("message.delta", "a", {"delta": "two"}))
    for _ in range(100):
        subscription.publish(AgentEvent("message.delta", "a", {"delta": "ignored"}))
    received = [e async for e in subscription.events()]
    assert len(received) == 1
    assert received[0].data["code"] == "STREAM_CONSUMER_TOO_SLOW"


async def test_disconnect_detaches_subscription():
    subscription = EventSubscription("a")
    subscription.aclose()
    subscription.publish(AgentEvent("message.delta", "a", {"delta": "ignored"}))
    assert [e async for e in subscription.events()] == []

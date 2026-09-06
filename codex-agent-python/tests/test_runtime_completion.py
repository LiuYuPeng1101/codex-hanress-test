from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from openai_codex.generated.v2_all import Turn

from app.runtime.admission import ExecutionFailed
from app.runtime.codex_runtime import CodexRuntime


def runtime_with_thread(thread):
    # No SDK process/model calls in unit tests; the mapper has separate real-type contracts.
    runtime = object.__new__(CodexRuntime)
    runtime._resume_thread = AsyncMock(return_value=thread)
    runtime._sandbox = Mock()
    runtime._tracer = MagicMock()
    runtime._set_common_span_attributes = Mock()
    return runtime


async def test_manual_compaction_waits_for_new_terminal_turn():
    old = Turn(id="old", items=[], status="completed", itemsView="full")
    running = Turn(id="new", items=[], status="inProgress", itemsView="full")
    completed = Turn(
        id="new",
        items=[{"id": "compact", "type": "contextCompaction"}],
        status="completed",
        itemsView="full",
    )
    thread = NS(
        compact=AsyncMock(),
        read=AsyncMock(
            side_effect=[
                NS(thread=NS(turns=[old])),
                NS(thread=NS(turns=[old, running])),
                NS(thread=NS(turns=[old, completed])),
            ]
        ),
    )
    await runtime_with_thread(thread).compact_thread(
        "t", user_id="u", tenant_id="t", roles=frozenset()
    )
    assert thread.read.await_count == 3


async def test_sync_turn_does_not_report_failed_run_as_empty_success():
    thread = NS(run=AsyncMock(return_value=NS(id="turn", status="failed", final_response="")))
    with pytest.raises(ExecutionFailed):
        await runtime_with_thread(thread).run_turn(
            "t", "c", "query", user_id="u", tenant_id="t", roles=frozenset()
        )

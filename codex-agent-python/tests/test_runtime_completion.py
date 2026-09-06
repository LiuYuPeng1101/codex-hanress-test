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


async def test_turn_binds_conversation_to_trusted_mcp_configuration():
    from app.agents.definition import AgentDefinition, McpServerDefinition, SandboxPolicy

    thread = NS(run=AsyncMock(return_value=NS(id="turn", status="completed", final_response="ok")))
    runtime = runtime_with_thread(thread)
    await runtime.run_turn(
        "runtime-thread",
        "business-conversation",
        "query",
        user_id="u",
        tenant_id="t",
        roles=frozenset(),
    )
    assert runtime._resume_thread.call_args.kwargs["conversation_id"] == "business-conversation"
    runtime._definition = AgentDefinition(
        agent_id="order",
        workspace=".",
        sandbox=SandboxPolicy.READ_ONLY,
        mcp_servers=(
            McpServerDefinition(
                name="order",
                url="http://mcp/mcp",
                service_token="trusted-token-with-at-least-32-characters",
                enabled_tools=("cancel_order",),
                tool_approval_modes=(("cancel_order", "approve"),),
            ),
        ),
    )
    config = runtime._mcp_request_config(
        user_id="u", tenant_id="t", roles=frozenset(), conversation_id="business-conversation"
    )
    headers = config["mcp_servers.order.http_headers"]
    assert headers["X-Conversation-Id"] == "business-conversation"
    assert headers["X-User-Id"] == "u"
    assert headers["Authorization"] == "Bearer trusted-token-with-at-least-32-characters"

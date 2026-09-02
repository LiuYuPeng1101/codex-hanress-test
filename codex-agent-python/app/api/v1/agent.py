import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_service
from app.schemas.agent import (
    CompactThreadResponse,
    CreateThreadResponse,
    RunTurnRequest,
    RunTurnResponse,
    ThreadReadResponse,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agent"])


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread(
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> CreateThreadResponse:
    """创建一个新的 Codex Thread。"""

    thread_id = await service.create_conversation()
    return CreateThreadResponse(thread_id=thread_id)


@router.get("/threads/{thread_id}", response_model=ThreadReadResponse)
async def read_thread(
    thread_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ThreadReadResponse:
    """读取 Thread 快照，并包含 Turn 历史。

    这个接口用于观察“持久化 Thread 历史”，不要把它误解成模型下一轮一定会原样看到的
    Effective Context。Context 可能经过 Harness 的裁剪、替换或 Compaction。
    """

    snapshot = await service.read_conversation(thread_id)
    return ThreadReadResponse(thread=snapshot["thread"])


@router.post("/threads/{thread_id}/compact", response_model=CompactThreadResponse)
async def compact_thread(
    thread_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> CompactThreadResponse:
    """触发 Thread 手动 Compaction。

    官方底层接口是 `thread/compact/start`，因此这里只表示压缩已成功发起。
    """

    await service.compact_conversation(thread_id)
    return CompactThreadResponse(thread_id=thread_id, status="COMPACTION_STARTED")


@router.post("/threads/{thread_id}/turns", response_model=RunTurnResponse)
async def run_turn(
    thread_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> RunTurnResponse:
    """在已有 Thread 中执行一轮非流式 Turn。"""

    answer = await service.chat(thread_id, request.message)
    return RunTurnResponse(thread_id=thread_id, answer=answer)


@router.post("/threads/{thread_id}/turns/stream")
async def stream_turn(
    thread_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> StreamingResponse:
    """通过 SSE 实时推送一轮 Turn 的标准化 Agent Event。"""

    async def event_stream():
        async for event in service.stream_chat(thread_id, request.message):
            payload = json.dumps(event.to_dict(), ensure_ascii=False)
            yield f"event: {event.type}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

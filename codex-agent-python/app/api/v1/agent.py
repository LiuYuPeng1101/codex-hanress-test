import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_service
from app.schemas.agent import CreateThreadResponse, RunTurnRequest, RunTurnResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agent"])


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread(
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> CreateThreadResponse:
    """创建一个新的 Codex Thread。

    可以把 Thread 理解成一个新的 Agent 聊天窗口。
    """

    thread_id = await service.create_conversation()
    return CreateThreadResponse(thread_id=thread_id)


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
    """通过 SSE 实时推送一轮 Turn 的标准化 Agent Event。

    前端不会收到 Codex 原始 reasoning 事件或 Tool 完整参数/结果，只接收经过安全映射的
    turn、tool、item、message.delta 等事件。
    """

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

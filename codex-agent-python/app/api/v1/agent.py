import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_service
from app.schemas.agent import (
    CompactConversationResponse,
    ConversationReadResponse,
    CreateConversationResponse,
    RunTurnRequest,
    RunTurnResponse,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agent"])


@router.post("/{agent_id}/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    agent_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> CreateConversationResponse:
    """创建平台级业务 Conversation，不向调用方暴露 Codex Thread ID。"""

    try:
        conversation = await service.create_conversation(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    return CreateConversationResponse(
        conversation_id=conversation.id,
        agent_id=conversation.agent_id,
        created_at=conversation.created_at,
    )


@router.get(
    "/{agent_id}/conversations/{conversation_id}",
    response_model=ConversationReadResponse,
)
async def read_conversation(
    agent_id: str,
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ConversationReadResponse:
    """读取 Conversation 对应的 Runtime Thread 状态，用于受控诊断与管理。"""

    try:
        conversation = service.get_conversation(agent_id, conversation_id)
        snapshot = await service.read_conversation(agent_id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return ConversationReadResponse(
        conversation_id=conversation.id,
        agent_id=conversation.agent_id,
        runtime=conversation.runtime,
        thread=snapshot["thread"],
    )


@router.post(
    "/{agent_id}/conversations/{conversation_id}/compact",
    response_model=CompactConversationResponse,
)
async def compact_conversation(
    agent_id: str,
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> CompactConversationResponse:
    """触发 Runtime Thread Compaction；响应只表示请求已被 Codex 接受。"""

    try:
        await service.compact_conversation(agent_id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return CompactConversationResponse(
        conversation_id=conversation_id,
        status="COMPACTION_STARTED",
    )


@router.post(
    "/{agent_id}/conversations/{conversation_id}/turns",
    response_model=RunTurnResponse,
)
async def run_turn(
    agent_id: str,
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> RunTurnResponse:
    try:
        answer = await service.chat(agent_id, conversation_id, request.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return RunTurnResponse(conversation_id=conversation_id, answer=answer)


@router.post("/{agent_id}/conversations/{conversation_id}/turns/stream")
async def stream_turn(
    agent_id: str,
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> StreamingResponse:
    """通过 SSE 输出稳定 AgentEvent；不暴露 Codex 私有事件协议。"""

    # 在返回 StreamingResponse 前先验证 Conversation，避免已开始 SSE 后才返回 404。
    try:
        service.get_conversation(agent_id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc

    async def event_stream():
        async for event in service.stream_chat(agent_id, conversation_id, request.message):
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

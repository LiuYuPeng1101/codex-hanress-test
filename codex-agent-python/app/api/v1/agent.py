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
from app.security.service_auth import (
    ServicePrincipal,
    require_operator_principal,
    require_service_principal,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[ServicePrincipal, Depends(require_service_principal)],
) -> CreateConversationResponse:
    conversation = await service.create_conversation(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        roles=principal.roles,
    )
    return CreateConversationResponse(conversation_id=conversation.id)


@router.get("/conversations/{conversation_id}", response_model=ConversationReadResponse)
async def read_conversation(
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[ServicePrincipal, Depends(require_operator_principal)],
) -> ConversationReadResponse:
    try:
        snapshot = await service.read_conversation(
            conversation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return ConversationReadResponse(
        conversation_id=conversation_id,
        runtime_snapshot=snapshot,
    )


@router.post(
    "/conversations/{conversation_id}/compact",
    response_model=CompactConversationResponse,
)
async def compact_conversation(
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[ServicePrincipal, Depends(require_operator_principal)],
) -> CompactConversationResponse:
    try:
        await service.compact_conversation(
            conversation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return CompactConversationResponse(
        conversation_id=conversation_id,
        status="COMPACTION_STARTED",
    )


@router.post("/conversations/{conversation_id}/turns", response_model=RunTurnResponse)
async def run_turn(
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[ServicePrincipal, Depends(require_service_principal)],
) -> RunTurnResponse:
    try:
        answer = await service.chat(
            conversation_id,
            request.message,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    return RunTurnResponse(conversation_id=conversation_id, answer=answer)


@router.post("/conversations/{conversation_id}/turns/stream")
async def stream_turn(
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[ServicePrincipal, Depends(require_service_principal)],
) -> StreamingResponse:
    async def event_stream():
        try:
            async for event in service.stream_chat(
                conversation_id,
                request.message,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                roles=principal.roles,
            ):
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except KeyError:
            payload = json.dumps({"code": "CONVERSATION_NOT_FOUND"}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

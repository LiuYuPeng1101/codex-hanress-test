import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_service
from app.schemas.agent import (
    CompactConversationResponse,
    ConversationReadResponse,
    CreateConversationResponse,
    RunTurnRequest,
    RunTurnResponse,
)
from app.security.gateway_auth import (
    GatewayPrincipal,
    require_gateway_principal,
    require_operator_principal,
)
from app.services.agent_service import AgentService, RuntimeOwnershipError

router = APIRouter(prefix="/agents", tags=["Agent"])


def _runtime_route_error(exc: RuntimeOwnershipError) -> HTTPException:
    """把 Runtime 粘性路由要求转换成 Gateway 可处理的冲突响应。"""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "RUNTIME_INSTANCE_MISMATCH",
            "expected_runtime_instance_id": exc.expected_instance_id,
        },
    )


@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
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
    principal: Annotated[GatewayPrincipal, Depends(require_operator_principal)],
) -> ConversationReadResponse:
    """读取 Runtime 原始诊断快照，仅允许 Agent Runtime 运维角色访问。"""

    try:
        snapshot = await service.read_conversation(
            conversation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    except RuntimeOwnershipError as exc:
        raise _runtime_route_error(exc) from exc
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
    principal: Annotated[GatewayPrincipal, Depends(require_operator_principal)],
) -> CompactConversationResponse:
    """人工触发 Context Compaction，仅允许 Runtime 运维角色。"""

    try:
        await service.compact_conversation(
            conversation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            roles=principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation 不存在") from exc
    except RuntimeOwnershipError as exc:
        raise _runtime_route_error(exc) from exc
    return CompactConversationResponse(
        conversation_id=conversation_id,
        status="COMPACTION_STARTED",
    )


@router.post("/conversations/{conversation_id}/turns", response_model=RunTurnResponse)
async def run_turn(
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
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
    except RuntimeOwnershipError as exc:
        raise _runtime_route_error(exc) from exc
    return RunTurnResponse(conversation_id=conversation_id, answer=answer)


@router.post("/conversations/{conversation_id}/turns/stream")
async def stream_turn(
    conversation_id: str,
    request: RunTurnRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
) -> StreamingResponse:
    """通过 SSE 只推送稳定 AgentEvent，不暴露 Codex Thread / Turn ID。"""

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
        except RuntimeOwnershipError as exc:
            payload = json.dumps(
                {
                    "code": "RUNTIME_INSTANCE_MISMATCH",
                    "expected_runtime_instance_id": exc.expected_instance_id,
                },
                ensure_ascii=False,
            )
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

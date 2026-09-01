from typing import Annotated

from fastapi import APIRouter, Depends

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
    """在已有 Thread 中执行一轮 Turn。"""

    answer = await service.chat(thread_id, request.message)
    return RunTurnResponse(thread_id=thread_id, answer=answer)

from collections.abc import AsyncIterator
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.conversations.conversation_repository import Conversation, ConversationRepository
from app.events.models import AgentEvent
from app.runtime.admission import AdmissionController, ExecutionFailed
from app.runtime.event_subscription import EventSubscription
from app.runtime.ports import AgentRuntime


class AgentService:
    """单 Agent 的应用服务。

    外部只处理业务 conversation_id；内部把它映射为 Codex thread_id。
    这里不做 Agent Registry、Runtime Scheduler、Lease 或多 Runtime 路由。
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        conversations: ConversationRepository,
        admission: AdmissionController | None = None,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self.admission = admission if admission is not None else AdmissionController(8)

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> Conversation:
        conversation_id = self._conversations.new_id()
        return await self.admission.run(
            conversation_id,
            lambda: self._create_conversation(conversation_id, tenant_id, user_id, roles),
        )

    async def _create_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> Conversation:
        runtime_thread_id = await self._runtime.create_thread(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        try:
            return await run_in_threadpool(
                self._conversations.create,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                runtime_thread_id=runtime_thread_id,
            )
        except Exception:
            try:
                await self._runtime.archive_thread(runtime_thread_id)
            finally:
                raise

    async def read_conversation(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        conversation = await run_in_threadpool(
            self._resolve_owned,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return await self.admission.run(
            conversation.id,
            lambda: self._runtime.read_thread(
                conversation.runtime_thread_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ),
        )

    async def compact_conversation(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> None:
        conversation = await run_in_threadpool(
            self._resolve_owned,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await self.admission.run(
            conversation.id,
            lambda: self._runtime.compact_thread(
                conversation.runtime_thread_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ),
        )

    async def chat(
        self,
        conversation_id: str,
        message: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> str:
        conversation = await run_in_threadpool(
            self._resolve_owned,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return await self.admission.run(
            conversation.id,
            lambda: self._runtime.run_turn(
                conversation.runtime_thread_id,
                conversation.id,
                message,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ),
        )

    async def open_stream(
        self,
        conversation_id: str,
        message: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> EventSubscription:
        conversation = await run_in_threadpool(
            self._resolve_owned,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        subscription = EventSubscription(conversation_id)

        async def produce() -> None:
            try:
                async for event in self._runtime.stream_turn(
                    conversation.runtime_thread_id,
                    conversation.id,
                    message,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    roles=roles,
                ):
                    subscription.publish(event)
            except ExecutionFailed:
                subscription.finish("TURN_FAILED")
                raise
            except BaseException:
                subscription.finish("RUNTIME_UNAVAILABLE")
                raise
            else:
                subscription.finish()

        self.admission.submit(conversation.id, produce)
        return subscription

    async def stream_chat(
        self,
        conversation_id: str,
        message: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> AsyncIterator[AgentEvent]:
        subscription = await self.open_stream(
            conversation_id,
            message,
            tenant_id=tenant_id,
            user_id=user_id,
            roles=roles,
        )
        try:
            async for event in subscription.events():
                yield event
        finally:
            subscription.aclose()

    def _resolve_owned(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
        return self._conversations.get_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

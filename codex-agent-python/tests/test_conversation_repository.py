import fakeredis

from app.conversations.repository import ConversationRepository


def test_conversation_maps_business_id_to_runtime_thread() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    repository = ConversationRepository(redis)

    created = repository.create(
        agent_id="order",
        runtime="codex",
        runtime_thread_id="thread-runtime-123",
    )
    loaded = repository.get(created.id)

    assert loaded.id == created.id
    assert loaded.agent_id == "order"
    assert loaded.runtime == "codex"
    assert loaded.runtime_thread_id == "thread-runtime-123"

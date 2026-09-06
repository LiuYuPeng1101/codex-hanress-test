from pathlib import Path

from app.core.config import Settings


def test_required_single_agent_settings() -> None:
    settings = Settings(
        _env_file=None,
        codex_home=Path("/var/lib/codex"),
        order_mcp_url="http://order-mcp-adapter:8080/mcp",
        order_mcp_service_token="mcp-service-secret-with-at-least-32-chars",
        database_url="postgresql+psycopg://agent:test@postgres:5432/agent_runtime",
        execution_service_secret="execution-secret-with-at-least-32-chars",
        api_shared_secret="api-secret-with-at-least-32-characters",
    )

    assert settings.api_prefix == "/api/v1"
    assert settings.agent_id == "order-agent"
    assert settings.agent_workspace == Path(".")
    assert settings.codex_home == Path("/var/lib/codex")


def test_execution_credential_cannot_be_reused_from_public_api():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="执行授权密钥"):
        Settings(
            _env_file=None,
            codex_home=Path("/tmp/codex"),
            order_mcp_url="http://mcp/mcp",
            order_mcp_service_token="mcp-secret-with-at-least-32-characters",
            database_url="postgresql+psycopg://agent:test@postgres/agent",
            api_shared_secret="same-secret-with-at-least-32-characters",
            execution_service_secret="same-secret-with-at-least-32-characters",
        )

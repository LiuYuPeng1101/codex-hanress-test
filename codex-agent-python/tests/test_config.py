from pathlib import Path

from app.core.config import Settings


def test_required_production_settings() -> None:
    settings = Settings(
        _env_file=None,
        order_mcp_url="http://order-service:8080/mcp",
        database_url="postgresql+psycopg://agent:test@postgres:5432/agent_runtime",
    )

    assert settings.api_prefix == "/api/v1"
    assert settings.agent_workspace == Path(".")
    assert settings.app_env == "production"
    assert settings.approval_timeout_seconds == 900

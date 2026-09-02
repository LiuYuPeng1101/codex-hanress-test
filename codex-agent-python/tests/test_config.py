from pathlib import Path

from app.core.config import Settings


def test_required_production_settings() -> None:
    settings = Settings(
        _env_file=None,
        order_mcp_url="http://order-mcp:8080/mcp",
        redis_url="redis://redis:6379/0",
    )

    assert settings.api_prefix == "/api/v1"
    assert settings.agent_workspace == Path(".")
    assert settings.order_mcp_url == "http://order-mcp:8080/mcp"
    assert settings.redis_url == "redis://redis:6379/0"

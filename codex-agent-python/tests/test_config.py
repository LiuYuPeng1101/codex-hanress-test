from pathlib import Path

from app.core.config import Settings


def test_default_settings() -> None:
    """验证项目默认配置可以正常创建。"""

    settings = Settings(_env_file=None)

    assert settings.api_prefix == "/api/v1"
    assert settings.agent_workspace == Path(".")

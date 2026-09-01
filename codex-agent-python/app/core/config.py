from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。

    FastAPI 项目中建议把环境变量读取集中在一个配置对象中，
    不要在业务代码里到处直接读取 os.environ。
    """

    app_name: str = "Codex Agent Service"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    agent_workspace: Path = Path(".")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """返回单例配置对象，避免每次请求重复解析环境变量。"""

    return Settings()

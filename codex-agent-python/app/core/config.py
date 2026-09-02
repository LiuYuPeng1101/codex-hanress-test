from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent Service 生产运行配置。

    关键依赖必须显式配置；缺失配置时启动失败，不使用虚假数据或隐式降级。
    """

    app_name: str = "Codex Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"
    agent_workspace: Path = Path(".")
    agent_id: str = "order-agent"
    runtime_instance_id: str = Field(description="当前 Runtime 实例唯一标识，用于 Thread 路由")
    codex_home: Path = Field(description="Codex 持久化目录；生产环境必须挂载持久卷")

    order_mcp_url: str = Field(description="订单 MCP Adapter 地址")
    order_mcp_service_token: str = Field(
        min_length=32,
        description="Agent Runtime 调用订单 MCP Adapter 的服务认证密钥",
    )
    database_url: str = Field(description="PostgreSQL 连接串")
    gateway_shared_secret: str = Field(
        min_length=32,
        description="企业 Gateway 调用 Agent Service 的服务认证密钥",
    )
    approval_timeout_seconds: int = Field(default=900, ge=30, le=86400)

    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
